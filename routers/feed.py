from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload

from database import get_db
from dependencies import require_auth
from models import Follow, Post, Reel
from utils import enrich_post, enrich_reel

router = APIRouter()


@router.get("/api/feed")
def get_feed(db: Session = Depends(get_db), current_user_id: int = Depends(require_auth)):
    following_ids = [
        row.following_id
        for row in db.query(Follow).filter(Follow.follower_id == current_user_id).all()
    ]
    following_ids.append(current_user_id)

    posts = (
        db.query(Post)
        .options(joinedload(Post.user))
        .filter(Post.user_id.in_(following_ids))
        .all()
    )
    reels = (
        db.query(Reel)
        .options(joinedload(Reel.user))
        .filter(Reel.user_id.in_(following_ids))
        .all()
    )

    post_items = [
        {"item_type": "post", **enrich_post(p, db, current_user_id)}
        for p in posts
    ]
    reel_items = [
        {"item_type": "reel", **enrich_reel(r, db, current_user_id)}
        for r in reels
    ]

    all_items = sorted(
        post_items + reel_items,
        key=lambda x: x.get("created_at") or "",
        reverse=True,
    )

    return {"items": all_items}
