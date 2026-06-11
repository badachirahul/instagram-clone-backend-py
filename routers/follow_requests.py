from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from database import get_db
from dependencies import require_auth
from models import Conversation, ConversationParticipant, Follow, FollowRequest
from services.notifications import create_notification
from utils import fmt_dt, user_dict
from ws_manager import manager as ws_manager

router = APIRouter(prefix="/api/follow-requests")


@router.get("")
def get_follow_requests(
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    requests = (
        db.query(FollowRequest)
        .options(joinedload(FollowRequest.requester))
        .filter(FollowRequest.recipient_id == current_user_id)
        .order_by(FollowRequest.created_at.desc())
        .all()
    )
    return {
        "requests": [
            {
                "id": r.id,
                "requester": user_dict(r.requester),
                "created_at": fmt_dt(r.created_at),
            }
            for r in requests
            if r.requester
        ]
    }


@router.post("/{request_id}/accept")
def accept_follow_request(
    request_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    req = db.query(FollowRequest).filter(
        FollowRequest.id == request_id,
        FollowRequest.recipient_id == current_user_id,
    ).first()
    if not req:
        raise HTTPException(status_code=404, detail="follow request not found")

    requester_id = req.requester_id
    recipient_id = req.recipient_id

    # Create the follow row (guard against duplicate)
    existing = db.query(Follow).filter(
        Follow.follower_id == requester_id, Follow.following_id == recipient_id
    ).first()
    if not existing:
        db.add(Follow(follower_id=requester_id, following_id=recipient_id))

    # Delete the follow request
    db.delete(req)

    # Auto-accept any pending message request between these two users
    my_conv_ids = [
        row.conversation_id
        for row in db.query(ConversationParticipant.conversation_id)
        .filter(ConversationParticipant.user_id == current_user_id)
        .all()
    ]
    if my_conv_ids:
        requester_part = (
            db.query(ConversationParticipant)
            .filter(
                ConversationParticipant.user_id == requester_id,
                ConversationParticipant.conversation_id.in_(my_conv_ids),
            )
            .first()
        )
        if requester_part:
            conv = db.query(Conversation).filter(
                Conversation.id == requester_part.conversation_id,
                Conversation.status == "request",
            ).first()
            if conv:
                conv.status = "accepted"
                ws_manager.broadcast_sync(
                    [requester_id, current_user_id],
                    {"type": "conversation_accepted", "conversation_id": conv.id},
                )

    db.commit()

    # Notify the requester that their follow request was accepted
    create_notification(db, requester_id, current_user_id, "follow_request_accepted", ws_manager=ws_manager)

    return {"ok": True}


@router.delete("/{request_id}")
def reject_follow_request(
    request_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    req = db.query(FollowRequest).filter(
        FollowRequest.id == request_id,
        FollowRequest.recipient_id == current_user_id,
    ).first()
    if not req:
        raise HTTPException(status_code=404, detail="follow request not found")

    db.delete(req)
    db.commit()

    return {"ok": True}
