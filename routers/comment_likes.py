from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from dependencies import require_auth
from models import Comment, CommentLike

router = APIRouter(prefix="/api/comments")


@router.post("/{comment_id}/like", status_code=201)
def like_comment(
    comment_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    comment = db.query(Comment).filter(Comment.id == comment_id).first()
    if not comment:
        raise HTTPException(status_code=404, detail="comment not found")

    existing = db.query(CommentLike).filter(
        CommentLike.user_id == current_user_id, CommentLike.comment_id == comment_id
    ).first()
    if not existing:
        db.add(CommentLike(user_id=current_user_id, comment_id=comment_id))
        db.commit()

    likes_count = db.query(CommentLike).filter(CommentLike.comment_id == comment_id).count()
    return {"likes_count": likes_count, "is_liked": True}


@router.delete("/{comment_id}/like")
def unlike_comment(
    comment_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    comment = db.query(Comment).filter(Comment.id == comment_id).first()
    if not comment:
        raise HTTPException(status_code=404, detail="comment not found")

    db.query(CommentLike).filter(
        CommentLike.user_id == current_user_id, CommentLike.comment_id == comment_id
    ).delete()
    db.commit()

    likes_count = db.query(CommentLike).filter(CommentLike.comment_id == comment_id).count()
    return {"likes_count": likes_count, "is_liked": False}
