from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from database import get_db
from dependencies import require_auth
from models import Conversation, ConversationParticipant, Follow, Message, Post, Reel, User
from schemas.message import ConversationCreate, MessageCreate, SharePostRequest, ShareReelRequest
from services.notifications import create_notification
from utils import conversation_dict, message_dict
from ws_manager import manager as ws_manager

router = APIRouter(prefix="/api/messages")


def _require_participant(
    conversation_id: int, current_user_id: int, db: Session
) -> tuple[Conversation, list[int]]:
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

    # Find all existing conversations between these two users
    my_conv_ids = (
        db.query(ConversationParticipant.conversation_id)
        .filter(ConversationParticipant.user_id == current_user_id)
        .subquery()
    )
    shared_conv_ids = [
        row.conversation_id
        for row in db.query(ConversationParticipant.conversation_id)
        .filter(
            ConversationParticipant.user_id == body.user_id,
            ConversationParticipant.conversation_id.in_(my_conv_ids),
        )
        .all()
    ]

    if shared_conv_ids:
        # Pick the best non-rejected conversation (prefer accepted, then request)
        conv = (
            db.query(Conversation)
            .filter(
                Conversation.id.in_(shared_conv_ids),
                Conversation.status != "rejected",
            )
            .order_by(Conversation.id.desc())
            .first()
        )
        if conv:
            last_msg = (
                db.query(Message)
                .filter(Message.conversation_id == conv.id)
                .order_by(Message.created_at.desc())
                .first()
            )
            return {"conversation": conversation_dict(conv, target, last_msg)}

    # Determine status based on whether the sender follows the recipient
    is_sender_follower = (
        db.query(Follow)
        .filter(Follow.follower_id == current_user_id, Follow.following_id == body.user_id)
        .first()
        is not None
    )
    status = "accepted" if is_sender_follower else "request"
    requester_id = current_user_id if status == "request" else None

    # Create conversation and add both participants atomically
    conv = Conversation(status=status, requester_id=requester_id)
    db.add(conv)
    db.flush()
    db.add(ConversationParticipant(conversation_id=conv.id, user_id=current_user_id))
    db.add(ConversationParticipant(conversation_id=conv.id, user_id=body.user_id))
    db.commit()
    db.refresh(conv)

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

    from sqlalchemy import or_, and_
    conversations = (
        db.query(Conversation)
        .filter(
            Conversation.id.in_(conv_ids),
            or_(
                Conversation.status == "accepted",
                # Show request conversations only to the person who sent them
                and_(
                    Conversation.status == "request",
                    Conversation.requester_id == current_user_id,
                ),
            ),
        )
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

    # Deduplicate: keep only the most recent conversation per other user
    seen_user_ids: set[int] = set()
    deduped = []
    for c in result:
        uid = (c.get("other_user") or {}).get("id")
        if uid is None or uid not in seen_user_ids:
            deduped.append(c)
            if uid is not None:
                seen_user_ids.add(uid)

    return {"conversations": deduped}


@router.get("/requests")
def get_message_requests(
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    """Returns incoming message requests (conversations where current_user is the recipient)."""
    conv_ids = [
        row.conversation_id
        for row in db.query(ConversationParticipant.conversation_id)
        .filter(ConversationParticipant.user_id == current_user_id)
        .all()
    ]

    if not conv_ids:
        return {"conversations": []}

    request_convs = (
        db.query(Conversation)
        .filter(
            Conversation.id.in_(conv_ids),
            Conversation.status == "request",
            Conversation.requester_id != current_user_id,
        )
        .all()
    )

    if not request_convs:
        return {"conversations": []}

    req_conv_ids = [c.id for c in request_convs]

    other_participants = (
        db.query(ConversationParticipant)
        .options(joinedload(ConversationParticipant.user))
        .filter(
            ConversationParticipant.conversation_id.in_(req_conv_ids),
            ConversationParticipant.user_id != current_user_id,
        )
        .all()
    )
    other_user_map = {p.conversation_id: p.user for p in other_participants}

    max_msg_sq = (
        db.query(Message.conversation_id, func.max(Message.id).label("max_id"))
        .filter(Message.conversation_id.in_(req_conv_ids))
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
        for conv in request_convs
    ]

    result.sort(
        key=lambda c: (c["last_message"] or {}).get("created_at") or c["created_at"] or "",
        reverse=True,
    )

    # Deduplicate: keep only the most recent request per other user
    seen_user_ids: set[int] = set()
    deduped = []
    for c in result:
        uid = (c.get("other_user") or {}).get("id")
        if uid is None or uid not in seen_user_ids:
            deduped.append(c)
            if uid is not None:
                seen_user_ids.add(uid)

    return {"conversations": deduped}


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
    conv, participant_ids = _require_participant(conversation_id, current_user_id, db)

    if not body.body.strip():
        raise HTTPException(status_code=400, detail="message body cannot be empty")

    # Enforce one-message limit for request conversations (sender side only)
    is_first_request_message = False
    if conv.status == "request" and conv.requester_id == current_user_id:
        existing_count = (
            db.query(Message)
            .filter(
                Message.conversation_id == conversation_id,
                Message.sender_id == current_user_id,
            )
            .count()
        )
        if existing_count > 0:
            raise HTTPException(status_code=403, detail="Awaiting approval")
        is_first_request_message = True

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

    # On the first request message: notify recipient and push the full conversation
    # object so their Requests tab updates in real-time without a page refresh.
    if is_first_request_message:
        recipient_id = next(pid for pid in participant_ids if pid != current_user_id)
        create_notification(db, recipient_id, current_user_id, "message_request", conv.id, ws_manager=ws_manager)

        sender = db.query(User).filter(User.id == current_user_id).first()
        conv_data = conversation_dict(conv, other_user=sender, last_message=msg)
        ws_manager.broadcast_sync(
            [recipient_id],
            {"type": "new_conversation_request", "conversation": conv_data},
        )

    return {"message": msg_data}


@router.post("/conversations/{conversation_id}/accept")
def accept_message_request(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    """Accept an incoming message request. Only the recipient (non-requester) can accept."""
    conv, participant_ids = _require_participant(conversation_id, current_user_id, db)

    if conv.status != "request":
        raise HTTPException(status_code=400, detail="conversation is not a request")
    if conv.requester_id == current_user_id:
        raise HTTPException(status_code=403, detail="cannot accept your own request")

    conv.status = "accepted"
    db.commit()

    # Notify the requester
    if conv.requester_id:
        create_notification(db, conv.requester_id, current_user_id, "message_request_accepted", conv.id, ws_manager=ws_manager)

    ws_manager.broadcast_sync(
        participant_ids,
        {"type": "conversation_accepted", "conversation_id": conv.id},
    )

    return {"ok": True}


@router.delete("/conversations/{conversation_id}/request")
def reject_message_request(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    """Reject (delete) an incoming message request."""
    conv, _ = _require_participant(conversation_id, current_user_id, db)

    if conv.status != "request":
        raise HTTPException(status_code=400, detail="conversation is not a request")
    if conv.requester_id == current_user_id:
        raise HTTPException(status_code=403, detail="cannot reject your own request")

    conv.status = "rejected"
    db.commit()

    return {"ok": True}


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
        conv, participant_ids = _require_participant(conv_id, current_user_id, db)

        # Enforce one-message limit if this is a request conversation
        if conv.status == "request" and conv.requester_id == current_user_id:
            existing_count = (
                db.query(Message)
                .filter(Message.conversation_id == conv_id, Message.sender_id == current_user_id)
                .count()
            )
            if existing_count > 0:
                continue  # Skip this conversation silently

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
        conv, participant_ids = _require_participant(conv_id, current_user_id, db)

        if conv.status == "request" and conv.requester_id == current_user_id:
            existing_count = (
                db.query(Message)
                .filter(Message.conversation_id == conv_id, Message.sender_id == current_user_id)
                .count()
            )
            if existing_count > 0:
                continue

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
