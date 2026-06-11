from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from database import get_db
from dependencies import optional_auth, require_auth
from models import Comment, CommentLike, Post
from schemas.comment import CommentCreate
from services.notifications import create_notification
from utils import comment_dict
from ws_manager import manager as ws_manager

router = APIRouter(prefix="/api/posts")


def _build_like_maps(comment_ids: list[int], current_user_id, db: Session):
    """Return (like_counts: dict[id->int], liked_set: set[id]) for a list of comment ids."""
    if not comment_ids:
        return {}, set()

    rows = (
        db.query(CommentLike.comment_id, func.count(CommentLike.id))
        .filter(CommentLike.comment_id.in_(comment_ids))
        .group_by(CommentLike.comment_id)
        .all()
    )
    like_counts = {cid: cnt for cid, cnt in rows}

    liked_set: set[int] = set()
    if current_user_id:
        liked_rows = (
            db.query(CommentLike.comment_id)
            .filter(
                CommentLike.user_id == current_user_id,
                CommentLike.comment_id.in_(comment_ids),
            )
            .all()
        )
        liked_set = {row[0] for row in liked_rows}

    return like_counts, liked_set


@router.get("/{post_id}/comments")
def get_comments(
    post_id: int,
    db: Session = Depends(get_db),
    current_user_id=Depends(optional_auth),
):
    top_level = (
        db.query(Comment)
        .options(joinedload(Comment.user), joinedload(Comment.reply_to_user))
        .filter(Comment.post_id == post_id, Comment.parent_comment_id.is_(None))
        .order_by(Comment.created_at.asc())
        .all()
    )

    all_replies = (
        db.query(Comment)
        .options(joinedload(Comment.user), joinedload(Comment.reply_to_user))
        .filter(Comment.post_id == post_id, Comment.parent_comment_id.isnot(None))
        .order_by(Comment.created_at.asc())
        .all()
    )

    reply_map: dict[int, list] = {}
    for r in all_replies:
        reply_map.setdefault(r.parent_comment_id, []).append(r)

    all_ids = [c.id for c in top_level] + [r.id for r in all_replies]
    like_counts, liked_set = _build_like_maps(all_ids, current_user_id, db)

    result = []
    for c in top_level:
        replies = [
            comment_dict(
                r,
                likes_count=like_counts.get(r.id, 0),
                is_liked=r.id in liked_set,
            )
            for r in reply_map.get(c.id, [])
        ]
        result.append(
            comment_dict(
                c,
                replies=replies,
                likes_count=like_counts.get(c.id, 0),
                is_liked=c.id in liked_set,
            )
        )

    return {"comments": result}


@router.post("/{post_id}/comments", status_code=201)
def create_comment(
    post_id: int,
    body: CommentCreate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="post not found")

    # Resolve parent: always store the root comment id
    parent_id = None
    if body.parent_comment_id:
        parent = db.query(Comment).filter(Comment.id == body.parent_comment_id).first()
        if parent:
            parent_id = parent.parent_comment_id or parent.id

    comment = Comment(
        post_id=post_id,
        user_id=current_user_id,
        body=body.body,
        parent_comment_id=parent_id,
        reply_to_user_id=body.reply_to_user_id,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    comment = (
        db.query(Comment)
        .options(joinedload(Comment.user), joinedload(Comment.reply_to_user))
        .filter(Comment.id == comment.id)
        .first()
    )
    # Notify post owner of new comment; for replies also notify the replied-to user
    create_notification(db, post.user_id, current_user_id, "post_comment", post_id, ws_manager=ws_manager)
    if body.reply_to_user_id and body.reply_to_user_id != post.user_id:
        create_notification(db, body.reply_to_user_id, current_user_id, "comment_reply", post_id, ws_manager=ws_manager)

    # New comment always has 0 likes and is not liked
    return {"comment": comment_dict(comment)}


@router.delete("/{post_id}/comments/{comment_id}")
def delete_comment(
    post_id: int,
    comment_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    comment = db.query(Comment).filter(Comment.id == comment_id).first()
    if not comment:
        raise HTTPException(status_code=404, detail="comment not found")
    if comment.user_id != current_user_id:
        raise HTTPException(status_code=403, detail="not your comment")

    db.delete(comment)
    db.commit()
    return {"message": "deleted"}
