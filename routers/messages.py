from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from database import get_db
from dependencies import require_auth
from models import Conversation, ConversationParticipant, Message, Post, Reel, User
from schemas.message import ConversationCreate, MessageCreate, SharePostRequest, ShareReelRequest
from services.notifications import create_notification
from utils import conversation_dict, message_dict
from ws_manager import manager as ws_manager

router = APIRouter(prefix="/api/messages")


def _require_participant(
    conversation_id: int, current_user_id: int, db: Session
) -> tuple[Conversation, list[int]]:
    """
    Fetch conversation + all participant IDs in two queries.
    Raises 404/403 if invalid. Returns (conv, participant_ids) so
    callers can reuse participant_ids without an extra query.
    """
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="conversation not found")

    participants = (
        db.query(ConversationParticipant)
        .filter(ConversationParticipant.conversation_id == conversation_id)
        .all()
    )
    participant_ids = [p.user_id for p in participants]

    if current_user_id not in participant_ids:
        raise HTTPException(status_code=403, detail="not a participant")

    return conv, participant_ids


@router.post("/conversations", status_code=201)
def create_or_get_conversation(
    body: ConversationCreate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    target = db.query(User).filter(User.id == body.user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="user not found")
    if target.id == current_user_id:
        raise HTTPException(status_code=400, detail="cannot message yourself")

    # Find an existing conversation that contains both users
    my_conv_ids = (
        db.query(ConversationParticipant.conversation_id)
        .filter(ConversationParticipant.user_id == current_user_id)
        .subquery()
    )
    existing = (
        db.query(ConversationParticipant)
        .filter(
            ConversationParticipant.user_id == body.user_id,
            ConversationParticipant.conversation_id.in_(my_conv_ids),
        )
        .first()
    )

    if existing:
        conv = db.query(Conversation).filter(Conversation.id == existing.conversation_id).first()
        last_msg = (
            db.query(Message)
            .filter(Message.conversation_id == conv.id)
            .order_by(Message.created_at.desc())
            .first()
        )
        return {"conversation": conversation_dict(conv, target, last_msg)}

    # Create conversation and add both participants atomically
    conv = Conversation()
    db.add(conv)
    db.flush()
    db.add(ConversationParticipant(conversation_id=conv.id, user_id=current_user_id))
    db.add(ConversationParticipant(conversation_id=conv.id, user_id=body.user_id))
    db.commit()
    db.refresh(conv)

    create_notification(db, body.user_id, current_user_id, "message_request", conv.id, ws_manager=ws_manager)

    return {"conversation": conversation_dict(conv, target)}


@router.get("/conversations")
def get_conversations(
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    conv_ids = [
        row.conversation_id
        for row in db.query(ConversationParticipant.conversation_id)
        .filter(ConversationParticipant.user_id == current_user_id)
        .all()
    ]

    if not conv_ids:
        return {"conversations": []}

    conversations = (
        db.query(Conversation)
        .filter(Conversation.id.in_(conv_ids))
        .all()
    )

    # Fetch all "other" participants in one query
    other_participants = (
        db.query(ConversationParticipant)
        .options(joinedload(ConversationParticipant.user))
        .filter(
            ConversationParticipant.conversation_id.in_(conv_ids),
            ConversationParticipant.user_id != current_user_id,
        )
        .all()
    )
    other_user_map = {p.conversation_id: p.user for p in other_participants}

    # Fetch the most recent message per conversation in one query
    max_msg_sq = (
        db.query(Message.conversation_id, func.max(Message.id).label("max_id"))
        .filter(Message.conversation_id.in_(conv_ids))
        .group_by(Message.conversation_id)
        .subquery()
    )
    last_msgs = db.query(Message).join(max_msg_sq, Message.id == max_msg_sq.c.max_id).all()
    last_msg_map = {m.conversation_id: m for m in last_msgs}

    result = [
        conversation_dict(
            conv,
            other_user=other_user_map.get(conv.id),
            last_message=last_msg_map.get(conv.id),
        )
        for conv in conversations
    ]

    result.sort(
        key=lambda c: (c["last_message"] or {}).get("created_at") or c["created_at"] or "",
        reverse=True,
    )

    return {"conversations": result}


@router.get("/conversations/{conversation_id}/messages")
def get_messages(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    _require_participant(conversation_id, current_user_id, db)

    msgs = (
        db.query(Message)
        .options(
            joinedload(Message.shared_post).joinedload(Post.user),
            joinedload(Message.shared_reel).joinedload(Reel.user),
        )
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
        .all()
    )

    return {"messages": [message_dict(m) for m in msgs]}


@router.post("/conversations/{conversation_id}/messages", status_code=201)
def send_message(
    conversation_id: int,
    body: MessageCreate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    # _require_participant returns participant_ids — reuse for broadcast, no extra query
    _, participant_ids = _require_participant(conversation_id, current_user_id, db)

    if not body.body.strip():
        raise HTTPException(status_code=400, detail="message body cannot be empty")

    msg = Message(
        conversation_id=conversation_id,
        sender_id=current_user_id,
        body=body.body.strip(),
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)

    msg_data = message_dict(msg)
    ws_manager.broadcast_sync(
        participant_ids,
        {"type": "new_message", "conversation_id": conversation_id, "message": msg_data},
    )

    return {"message": msg_data}


@router.post("/share/post/{post_id}", status_code=201)
def share_post(
    post_id: int,
    body: SharePostRequest,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    post = (
        db.query(Post)
        .options(joinedload(Post.user))
        .filter(Post.id == post_id)
        .first()
    )
    if not post:
        raise HTTPException(status_code=404, detail="post not found")
    if not body.conversation_ids:
        raise HTTPException(status_code=400, detail="conversation_ids required")

    results = []
    for conv_id in body.conversation_ids:
        _, participant_ids = _require_participant(conv_id, current_user_id, db)

        msg = Message(
            conversation_id=conv_id,
            sender_id=current_user_id,
            body="",
            message_type="shared_post",
            shared_post_id=post_id,
        )
        db.add(msg)
        db.commit()
        db.refresh(msg)

        # Attach the already-loaded post so message_dict can serialize it
        msg.shared_post = post
        msg_data = message_dict(msg)
        ws_manager.broadcast_sync(
            participant_ids,
            {"type": "new_message", "conversation_id": conv_id, "message": msg_data},
        )
        results.append(msg_data)

    return {"messages": results}


@router.post("/share/reel/{reel_id}", status_code=201)
def share_reel(
    reel_id: int,
    body: ShareReelRequest,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    reel = (
        db.query(Reel)
        .options(joinedload(Reel.user))
        .filter(Reel.id == reel_id)
        .first()
    )
    if not reel:
        raise HTTPException(status_code=404, detail="reel not found")
    if not body.conversation_ids:
        raise HTTPException(status_code=400, detail="conversation_ids required")

    results = []
    for conv_id in body.conversation_ids:
        _, participant_ids = _require_participant(conv_id, current_user_id, db)

        msg = Message(
            conversation_id=conv_id,
            sender_id=current_user_id,
            body="",
            message_type="shared_reel",
            shared_reel_id=reel_id,
        )
        db.add(msg)
        db.commit()
        db.refresh(msg)

        msg.shared_reel = reel
        msg_data = message_dict(msg)
        ws_manager.broadcast_sync(
            participant_ids,
            {"type": "new_message", "conversation_id": conv_id, "message": msg_data},
        )
        results.append(msg_data)

    return {"messages": results}


@router.delete("/{message_id}")
def delete_message(
    message_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    msg = db.query(Message).filter(Message.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="message not found")
    if msg.sender_id != current_user_id:
        raise HTTPException(status_code=403, detail="not your message")

    msg.is_deleted_for_everyone = True
    db.commit()
    db.refresh(msg)

    msg_data = message_dict(msg)

    participant_ids = [
        p.user_id
        for p in db.query(ConversationParticipant)
        .filter(ConversationParticipant.conversation_id == msg.conversation_id)
        .all()
    ]
    ws_manager.broadcast_sync(
        participant_ids,
        {"type": "message_deleted", "conversation_id": msg.conversation_id, "message": msg_data},
    )

    return {"message": msg_data}
