from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload

from database import get_db
from dependencies import require_auth
from models import Notification
from utils import notification_dict

router = APIRouter(prefix="/api/notifications")


@router.get("")
def get_notifications(
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    notifs = (
        db.query(Notification)
        .options(joinedload(Notification.actor))
        .filter(Notification.recipient_user_id == current_user_id)
        .order_by(Notification.created_at.desc())
        .all()
    )
    return {"notifications": [notification_dict(n) for n in notifs]}


@router.get("/unread-count")
def get_unread_count(
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    count = (
        db.query(Notification)
        .filter(
            Notification.recipient_user_id == current_user_id,
            Notification.is_read == False,
        )
        .count()
    )
    return {"count": count}


@router.patch("/read-all")
def mark_all_read(
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    db.query(Notification).filter(
        Notification.recipient_user_id == current_user_id,
        Notification.is_read == False,
    ).update({"is_read": True})
    db.commit()
    return {"message": "ok"}


@router.patch("/{notification_id}/read")
def mark_one_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    n = (
        db.query(Notification)
        .filter(
            Notification.id == notification_id,
            Notification.recipient_user_id == current_user_id,
        )
        .first()
    )
    if n:
        n.is_read = True
        db.commit()
    return {"message": "ok"}
