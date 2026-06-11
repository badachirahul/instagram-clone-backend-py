from sqlalchemy.orm import Session, joinedload

from models import Notification
from utils import notification_dict


def create_notification(
    db: Session,
    recipient_user_id: int,
    actor_user_id: int,
    notification_type: str,
    entity_id: int | None = None,
    ws_manager=None,
):
    if recipient_user_id == actor_user_id:
        return None

    n = Notification(
        recipient_user_id=recipient_user_id,
        actor_user_id=actor_user_id,
        type=notification_type,
        entity_id=entity_id,
    )
    db.add(n)
    db.commit()
    db.refresh(n)

    if ws_manager is not None:
        n = (
            db.query(Notification)
            .options(joinedload(Notification.actor))
            .filter(Notification.id == n.id)
            .first()
        )
        ws_manager.broadcast_sync(
            [recipient_user_id],
            {"type": "notification", "notification": notification_dict(n)},
        )

    return n
