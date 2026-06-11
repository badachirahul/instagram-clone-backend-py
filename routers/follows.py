from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from dependencies import require_auth
from models import Follow, FollowRequest, User
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

    # Already following → no-op
    existing_follow = db.query(Follow).filter(
        Follow.follower_id == current_user_id, Follow.following_id == user_id
    ).first()
    if existing_follow:
        followers_count = db.query(Follow).filter(Follow.following_id == user_id).count()
        return {"status": "following", "is_following": True, "has_requested": False, "followers_count": followers_count}

    if target.is_private:
        # Private account: send a follow request instead
        existing_req = db.query(FollowRequest).filter(
            FollowRequest.requester_id == current_user_id,
            FollowRequest.recipient_id == user_id,
        ).first()
        if not existing_req:
            db.add(FollowRequest(requester_id=current_user_id, recipient_id=user_id))
            db.commit()
            create_notification(db, user_id, current_user_id, "follow_request", ws_manager=ws_manager)

        followers_count = db.query(Follow).filter(Follow.following_id == user_id).count()
        return {"status": "requested", "is_following": False, "has_requested": True, "followers_count": followers_count}
    else:
        # Public account: follow immediately
        db.add(Follow(follower_id=current_user_id, following_id=user_id))
        db.commit()
        create_notification(db, user_id, current_user_id, "follow", ws_manager=ws_manager)

        followers_count = db.query(Follow).filter(Follow.following_id == user_id).count()
        return {"status": "following", "is_following": True, "has_requested": False, "followers_count": followers_count}


@router.delete("/{user_id}/follow")
def unfollow_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="user not found")

    # Remove follow if it exists
    db.query(Follow).filter(
        Follow.follower_id == current_user_id, Follow.following_id == user_id
    ).delete()

    # Also cancel any pending follow request
    db.query(FollowRequest).filter(
        FollowRequest.requester_id == current_user_id,
        FollowRequest.recipient_id == user_id,
    ).delete()

    db.commit()

    followers_count = db.query(Follow).filter(Follow.following_id == user_id).count()
    return {"status": "none", "is_following": False, "has_requested": False, "followers_count": followers_count}
