from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from database import get_db
from dependencies import optional_auth, require_auth
from models import Follow, Reel, ReelComment, ReelLike, ReelSave
from schemas.comment import CommentCreate
from schemas.reel import ReelCreate, ReelUpdate
from services.notifications import create_notification
from utils import enrich_reel, reel_comment_dict
from ws_manager import manager as ws_manager

router = APIRouter(prefix="/api/reels")


# ── CRUD ──────────────────────────────────────────────────────────────────────

@router.get("/feed")
def get_reel_feed(
    skip: int = 0,
    limit: int = 10,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    following_ids = [
        row.following_id
        for row in db.query(Follow).filter(Follow.follower_id == current_user_id).all()
    ]
    following_ids.append(current_user_id)

    reels = (
        db.query(Reel)
        .options(joinedload(Reel.user))
        .filter(Reel.user_id.in_(following_ids))
        .order_by(Reel.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return {"reels": [enrich_reel(r, db, current_user_id) for r in reels]}


@router.get("")
def get_reels(
    skip: int = 0,
    limit: int = 10,
    db: Session = Depends(get_db),
    current_user_id=Depends(optional_auth),
):
    reels = (
        db.query(Reel)
        .options(joinedload(Reel.user))
        .order_by(Reel.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return {"reels": [enrich_reel(r, db, current_user_id) for r in reels]}


@router.get("/{reel_id}")
def get_reel(
    reel_id: int,
    db: Session = Depends(get_db),
    current_user_id=Depends(optional_auth),
):
    reel = db.query(Reel).options(joinedload(Reel.user)).filter(Reel.id == reel_id).first()
    if not reel:
        raise HTTPException(status_code=404, detail="reel not found")
    return {"reel": enrich_reel(reel, db, current_user_id)}


@router.post("", status_code=201)
def create_reel(
    body: ReelCreate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    reel = Reel(
        user_id=current_user_id,
        video_url=body.video_url,
        thumbnail_url=body.thumbnail_url,
        caption=body.caption,
    )
    db.add(reel)
    db.commit()
    db.refresh(reel)
    reel = db.query(Reel).options(joinedload(Reel.user)).filter(Reel.id == reel.id).first()
    return {"reel": enrich_reel(reel, db, current_user_id)}


@router.put("/{reel_id}")
def update_reel(
    reel_id: int,
    body: ReelUpdate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    reel = db.query(Reel).filter(Reel.id == reel_id).first()
    if not reel:
        raise HTTPException(status_code=404, detail="reel not found")
    if reel.user_id != current_user_id:
        raise HTTPException(status_code=403, detail="not your reel")
    reel.caption = body.caption
    db.commit()
    db.refresh(reel)
    reel = db.query(Reel).options(joinedload(Reel.user)).filter(Reel.id == reel.id).first()
    return {"reel": enrich_reel(reel, db, current_user_id)}


@router.delete("/{reel_id}")
def delete_reel(
    reel_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    reel = db.query(Reel).filter(Reel.id == reel_id).first()
    if not reel:
        raise HTTPException(status_code=404, detail="reel not found")
    if reel.user_id != current_user_id:
        raise HTTPException(status_code=403, detail="not your reel")
    db.delete(reel)
    db.commit()
    return {"message": "deleted"}


# ── LIKES ─────────────────────────────────────────────────────────────────────

@router.post("/{reel_id}/like", status_code=201)
def like_reel(
    reel_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    reel = db.query(Reel).filter(Reel.id == reel_id).first()
    if not reel:
        raise HTTPException(status_code=404, detail="reel not found")
    existing = db.query(ReelLike).filter(
        ReelLike.user_id == current_user_id, ReelLike.reel_id == reel_id
    ).first()
    if not existing:
        db.add(ReelLike(user_id=current_user_id, reel_id=reel_id))
        db.commit()
        create_notification(db, reel.user_id, current_user_id, "reel_like", reel_id, ws_manager=ws_manager)
    like_count = db.query(ReelLike).filter(ReelLike.reel_id == reel_id).count()
    return {"liked_by_me": True, "like_count": like_count}


@router.delete("/{reel_id}/like")
def unlike_reel(
    reel_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    existing = db.query(ReelLike).filter(
        ReelLike.user_id == current_user_id, ReelLike.reel_id == reel_id
    ).first()
    if existing:
        db.delete(existing)
        db.commit()
    like_count = db.query(ReelLike).filter(ReelLike.reel_id == reel_id).count()
    return {"liked_by_me": False, "like_count": like_count}


# ── SAVES ─────────────────────────────────────────────────────────────────────

@router.post("/{reel_id}/save", status_code=201)
def save_reel(
    reel_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    reel = db.query(Reel).filter(Reel.id == reel_id).first()
    if not reel:
        raise HTTPException(status_code=404, detail="reel not found")
    existing = db.query(ReelSave).filter(
        ReelSave.user_id == current_user_id, ReelSave.reel_id == reel_id
    ).first()
    if not existing:
        db.add(ReelSave(user_id=current_user_id, reel_id=reel_id))
        db.commit()
    return {"saved_by_me": True}


@router.delete("/{reel_id}/save")
def unsave_reel(
    reel_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    existing = db.query(ReelSave).filter(
        ReelSave.user_id == current_user_id, ReelSave.reel_id == reel_id
    ).first()
    if existing:
        db.delete(existing)
        db.commit()
    return {"saved_by_me": False}


# ── COMMENTS ──────────────────────────────────────────────────────────────────

@router.get("/{reel_id}/comments")
def get_reel_comments(reel_id: int, db: Session = Depends(get_db)):
    top_level = (
        db.query(ReelComment)
        .options(joinedload(ReelComment.user), joinedload(ReelComment.reply_to_user))
        .filter(ReelComment.reel_id == reel_id, ReelComment.parent_comment_id.is_(None))
        .order_by(ReelComment.created_at.asc())
        .all()
    )

    all_replies = (
        db.query(ReelComment)
        .options(joinedload(ReelComment.user), joinedload(ReelComment.reply_to_user))
        .filter(ReelComment.reel_id == reel_id, ReelComment.parent_comment_id.isnot(None))
        .order_by(ReelComment.created_at.asc())
        .all()
    )

    reply_map: dict[int, list] = {}
    for r in all_replies:
        reply_map.setdefault(r.parent_comment_id, []).append(r)

    result = []
    for c in top_level:
        replies = [reel_comment_dict(r) for r in reply_map.get(c.id, [])]
        result.append(reel_comment_dict(c, replies=replies))

    return {"comments": result}


@router.post("/{reel_id}/comments", status_code=201)
def create_reel_comment(
    reel_id: int,
    body: CommentCreate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    reel = db.query(Reel).filter(Reel.id == reel_id).first()
    if not reel:
        raise HTTPException(status_code=404, detail="reel not found")
    if not body.body.strip():
        raise HTTPException(status_code=422, detail="body required")

    # Resolve parent: always store the root comment id
    parent_id = None
    if body.parent_comment_id:
        parent = db.query(ReelComment).filter(ReelComment.id == body.parent_comment_id).first()
        if parent:
            parent_id = parent.parent_comment_id or parent.id

    comment = ReelComment(
        reel_id=reel_id,
        user_id=current_user_id,
        body=body.body.strip(),
        parent_comment_id=parent_id,
        reply_to_user_id=body.reply_to_user_id,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    comment = (
        db.query(ReelComment)
        .options(joinedload(ReelComment.user), joinedload(ReelComment.reply_to_user))
        .filter(ReelComment.id == comment.id)
        .first()
    )
    create_notification(db, reel.user_id, current_user_id, "reel_comment", reel_id, ws_manager=ws_manager)
    return {"comment": reel_comment_dict(comment)}


@router.delete("/{reel_id}/comments/{comment_id}")
def delete_reel_comment(
    reel_id: int,
    comment_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    comment = db.query(ReelComment).filter(ReelComment.id == comment_id).first()
    if not comment:
        raise HTTPException(status_code=404, detail="comment not found")
    if comment.user_id != current_user_id:
        raise HTTPException(status_code=403, detail="not your comment")
    db.delete(comment)
    db.commit()
    return {"message": "deleted"}
