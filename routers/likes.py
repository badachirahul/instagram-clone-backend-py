from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from dependencies import require_auth
from models import Like, Post

router = APIRouter(prefix="/api/posts")


@router.post("/{post_id}/like")
def like_post(
    post_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="post not found")

    existing = db.query(Like).filter(Like.user_id == current_user_id, Like.post_id == post_id).first()
    if not existing:
        db.add(Like(user_id=current_user_id, post_id=post_id))
        db.commit()

    like_count = db.query(Like).filter(Like.post_id == post_id).count()
    return {"like_count": like_count, "liked_by_me": True}


@router.delete("/{post_id}/like")
def unlike_post(
    post_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="post not found")

    db.query(Like).filter(Like.user_id == current_user_id, Like.post_id == post_id).delete()
    db.commit()

    like_count = db.query(Like).filter(Like.post_id == post_id).count()
    return {"like_count": like_count, "liked_by_me": False}
