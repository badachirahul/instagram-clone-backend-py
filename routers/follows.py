from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from dependencies import require_auth
from models import Follow, User
from services.notifications import create_notification
from ws_manager import manager as ws_manager

router = APIRouter(prefix="/api/users")


@router.post("/{user_id}/follow")
def follow_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="user not found")
    if target.id == current_user_id:
        raise HTTPException(status_code=400, detail="cannot follow yourself")

    existing = db.query(Follow).filter(
        Follow.follower_id == current_user_id, Follow.following_id == user_id
    ).first()
    if not existing:
        db.add(Follow(follower_id=current_user_id, following_id=user_id))
        db.commit()
        create_notification(db, user_id, current_user_id, "follow", ws_manager=ws_manager)

    followers_count = db.query(Follow).filter(Follow.following_id == user_id).count()
    return {"followers_count": followers_count, "is_following": True}


@router.delete("/{user_id}/follow")
def unfollow_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="user not found")

    db.query(Follow).filter(
        Follow.follower_id == current_user_id, Follow.following_id == user_id
    ).delete()
    db.commit()

    followers_count = db.query(Follow).filter(Follow.following_id == user_id).count()
    return {"followers_count": followers_count, "is_following": False}
