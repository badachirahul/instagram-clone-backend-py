from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from dependencies import require_auth
from models import Post, SavedPost

router = APIRouter(prefix="/api/posts")


@router.post("/{post_id}/save")
def save_post(
    post_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="post not found")

    existing = db.query(SavedPost).filter(
        SavedPost.user_id == current_user_id,
        SavedPost.post_id == post_id,
    ).first()
    if not existing:
        db.add(SavedPost(user_id=current_user_id, post_id=post_id))
        db.commit()

    return {"saved_by_me": True}


@router.delete("/{post_id}/save")
def unsave_post(
    post_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    db.query(SavedPost).filter(
        SavedPost.user_id == current_user_id,
        SavedPost.post_id == post_id,
    ).delete()
    db.commit()
    return {"saved_by_me": False}
