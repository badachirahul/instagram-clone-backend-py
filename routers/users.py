from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, aliased, joinedload

from database import get_db
from dependencies import optional_auth, require_auth
from models import Comment, Follow, FollowRequest, Like, Post, SavedPost, User, Reel, ReelSave
from schemas.user import ProfileUpdate
from utils import enrich_post, enrich_reel, user_dict

router = APIRouter(prefix="/api/users")


def _is_approved_viewer(target_user, current_user_id, db) -> bool:
    """Return True if current_user can see private content on target_user's profile."""
    if not target_user.is_private:
        return True
    if current_user_id is None:
        return False
    if current_user_id == target_user.id:
        return True
    return (
        db.query(Follow)
        .filter(Follow.follower_id == current_user_id, Follow.following_id == target_user.id)
        .first()
        is not None
    )


# ── Own profile ────────────────────────────────────────────────────────────────

@router.patch("/me")
def update_me(
    body: ProfileUpdate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    user = db.query(User).filter(User.id == current_user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="user not found")
    if body.bio is not None:
        user.bio = body.bio
    if body.profile_picture_url is not None:
        user.profile_picture_url = body.profile_picture_url
    if body.is_private is not None:
        user.is_private = body.is_private
    db.commit()
    db.refresh(user)
    return {"user": user_dict(user)}


@router.delete("/me/photo")
def remove_profile_photo(
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    user = db.query(User).filter(User.id == current_user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="user not found")
    user.profile_picture_url = ""
    db.commit()
    return {"ok": True}


# ── Saved content ──────────────────────────────────────────────────────────────

@router.get("/me/saved-reels")
def get_saved_reels(
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    saved = (
        db.query(ReelSave)
        .filter(ReelSave.user_id == current_user_id)
        .order_by(ReelSave.created_at.desc())
        .all()
    )
    reel_ids = [s.reel_id for s in saved]
    reels = (
        db.query(Reel)
        .options(joinedload(Reel.user))
        .filter(Reel.id.in_(reel_ids))
        .all()
    )
    reels_by_id = {r.id: r for r in reels}
    ordered = [reels_by_id[rid] for rid in reel_ids if rid in reels_by_id]
    return {"reels": [enrich_reel(r, db, current_user_id) for r in ordered]}


@router.get("/me/saved-posts")
def get_saved_posts(
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
    current_user_opt=Depends(optional_auth),
):
    saved = (
        db.query(SavedPost)
        .filter(SavedPost.user_id == current_user_id)
        .order_by(SavedPost.created_at.desc())
        .all()
    )
    post_ids = [s.post_id for s in saved]
    posts = (
        db.query(Post)
        .options(joinedload(Post.user))
        .filter(Post.id.in_(post_ids))
        .all()
    )
    posts_by_id = {p.id: p for p in posts}
    ordered = [posts_by_id[pid] for pid in post_ids if pid in posts_by_id]
    return {"posts": [enrich_post(p, db, current_user_id) for p in ordered]}


# ── Search ─────────────────────────────────────────────────────────────────────

@router.get("/search")
def search_users(q: str = "", db: Session = Depends(get_db)):
    if not q.strip():
        return {"users": []}
    users = (
        db.query(User)
        .filter(User.username.ilike(f"%{q}%"))
        .limit(10)
        .all()
    )
    return {
        "users": [
            {
                "id": u.id,
                "username": u.username,
                "profile_picture_url": u.profile_picture_url or "",
                "is_private": bool(u.is_private),
            }
            for u in users
        ]
    }


# ── Profile ────────────────────────────────────────────────────────────────────

@router.get("/{user_id}")
def get_profile(
    user_id: int,
    db: Session = Depends(get_db),
    current_user_id=Depends(optional_auth),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="user not found")

    posts_count = db.query(Post).filter(Post.user_id == user_id).count()
    followers_count = db.query(Follow).filter(Follow.following_id == user_id).count()
    following_count = db.query(Follow).filter(Follow.follower_id == user_id).count()

    is_following = False
    has_requested = False
    if current_user_id:
        is_following = (
            db.query(Follow)
            .filter(Follow.follower_id == current_user_id, Follow.following_id == user_id)
            .first()
            is not None
        )
        if not is_following and user.is_private:
            has_requested = (
                db.query(FollowRequest)
                .filter(
                    FollowRequest.requester_id == current_user_id,
                    FollowRequest.recipient_id == user_id,
                )
                .first()
                is not None
            )

    return {
        "id": user.id,
        "username": user.username,
        "bio": user.bio or "",
        "profile_picture_url": user.profile_picture_url or "",
        "is_private": bool(user.is_private),
        "posts_count": posts_count,
        "followers_count": followers_count,
        "following_count": following_count,
        "is_following": is_following,
        "has_requested": has_requested,
    }


@router.get("/{user_id}/posts")
def get_user_posts(
    user_id: int,
    db: Session = Depends(get_db),
    current_user_id=Depends(optional_auth),
):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="user not found")

    if not _is_approved_viewer(target, current_user_id, db):
        return {"posts": [], "is_private": True}

    posts = (
        db.query(Post)
        .options(joinedload(Post.user))
        .filter(Post.user_id == user_id)
        .order_by(Post.created_at.desc())
        .all()
    )
    return {"posts": [enrich_post(p, db, current_user_id) for p in posts]}


@router.get("/{user_id}/reels")
def get_user_reels(
    user_id: int,
    db: Session = Depends(get_db),
    current_user_id=Depends(optional_auth),
):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="user not found")

    if not _is_approved_viewer(target, current_user_id, db):
        return {"reels": [], "is_private": True}

    reels = (
        db.query(Reel)
        .options(joinedload(Reel.user))
        .filter(Reel.user_id == user_id)
        .order_by(Reel.created_at.desc())
        .all()
    )
    return {"reels": [enrich_reel(r, db, current_user_id) for r in reels]}


@router.get("/{user_id}/followers")
def get_followers(user_id: int, db: Session = Depends(get_db)):
    follows = (
        db.query(Follow)
        .options(joinedload(Follow.follower))
        .filter(Follow.following_id == user_id)
        .order_by(Follow.created_at.desc())
        .all()
    )
    return {
        "users": [
            {"id": f.follower.id, "username": f.follower.username, "profile_picture_url": f.follower.profile_picture_url or ""}
            for f in follows
            if f.follower
        ]
    }


@router.get("/{user_id}/following")
def get_following(user_id: int, db: Session = Depends(get_db)):
    follows = (
        db.query(Follow)
        .options(joinedload(Follow.following))
        .filter(Follow.follower_id == user_id)
        .order_by(Follow.created_at.desc())
        .all()
    )
    return {
        "users": [
            {"id": f.following.id, "username": f.following.username, "profile_picture_url": f.following.profile_picture_url or ""}
            for f in follows
            if f.following
        ]
    }


@router.get("/{user_id}/mutual-followers")
def get_mutual_followers(
    user_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    """People the current user follows who also follow user_id."""
    F1 = aliased(Follow)  # they follow user_id
    F2 = aliased(Follow)  # current_user follows them

    mutual = (
        db.query(User)
        .join(F1, (F1.follower_id == User.id) & (F1.following_id == user_id))
        .join(F2, (F2.follower_id == current_user_id) & (F2.following_id == User.id))
        .limit(3)
        .all()
    )

    total = (
        db.query(func.count(User.id))
        .join(F1, (F1.follower_id == User.id) & (F1.following_id == user_id))
        .join(F2, (F2.follower_id == current_user_id) & (F2.following_id == User.id))
        .scalar()
    ) or 0

    return {
        "count": total,
        "users": [
            {"id": u.id, "username": u.username, "profile_picture_url": u.profile_picture_url or ""}
            for u in mutual
        ],
    }
