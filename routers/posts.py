from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from database import get_db
from dependencies import optional_auth, require_auth
from models import Follow, Post
from schemas.post import PostCreate, PostUpdate
from utils import enrich_post

router = APIRouter(prefix="/api/posts")


def _assert_can_view(post, current_user_id, db):
    if not post.user or not post.user.is_private:
        return
    if current_user_id and (current_user_id == post.user_id):
        return
    if current_user_id:
        is_following = (
            db.query(Follow)
            .filter(Follow.follower_id == current_user_id, Follow.following_id == post.user_id)
            .first()
            is not None
        )
        if is_following:
            return
    raise HTTPException(status_code=403, detail="This account is private")


@router.get("")
def get_posts(db: Session = Depends(get_db), current_user_id=Depends(optional_auth)):
    posts = (
        db.query(Post)
        .options(joinedload(Post.user))
        .order_by(Post.created_at.desc())
        .all()
    )
    # Filter out private account posts the viewer cannot see
    visible = [p for p in posts if not (p.user and p.user.is_private and p.user_id != current_user_id)]
    return {"posts": [enrich_post(p, db, current_user_id) for p in visible]}


@router.get("/{post_id}")
def get_post(post_id: int, db: Session = Depends(get_db), current_user_id=Depends(optional_auth)):
    post = db.query(Post).options(joinedload(Post.user)).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="post not found")
    _assert_can_view(post, current_user_id, db)
    return {"post": enrich_post(post, db, current_user_id)}


@router.post("", status_code=201)
def create_post(
    body: PostCreate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    post = Post(user_id=current_user_id, image_url=body.image_url, caption=body.caption)
    db.add(post)
    db.commit()
    db.refresh(post)
    post = db.query(Post).options(joinedload(Post.user)).filter(Post.id == post.id).first()
    return {"post": enrich_post(post, db, current_user_id)}


@router.put("/{post_id}")
def update_post(
    post_id: int,
    body: PostUpdate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="post not found")
    if post.user_id != current_user_id:
        raise HTTPException(status_code=403, detail="not your post")

    post.caption = body.caption
    db.commit()
    post = db.query(Post).options(joinedload(Post.user)).filter(Post.id == post_id).first()
    return {"post": enrich_post(post, db, current_user_id)}


@router.delete("/{post_id}")
def delete_post(
    post_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="post not found")
    if post.user_id != current_user_id:
        raise HTTPException(status_code=403, detail="not your post")

    db.delete(post)
    db.commit()
    return {"message": "deleted"}
