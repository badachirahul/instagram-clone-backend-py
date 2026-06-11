import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from database import get_db
from dependencies import optional_auth, require_auth
from models import Follow, Story, StoryView
from schemas.story import StoriesBatchCreate, StoryCreate
from utils import fmt_dt, story_dict, user_dict

router = APIRouter(prefix="/api")


def _now() -> datetime:
    return datetime.utcnow()


def _bulk_views(story_ids: list, current_user_id, db: Session):
    """Return (views_counts dict, viewed_ids set) for a list of story IDs."""
    if not story_ids:
        return {}, set()

    count_rows = (
        db.query(StoryView.story_id, func.count(StoryView.id))
        .filter(StoryView.story_id.in_(story_ids))
        .group_by(StoryView.story_id)
        .all()
    )
    views_counts = {row[0]: row[1] for row in count_rows}

    viewed_ids: set = set()
    if current_user_id:
        viewed_rows = (
            db.query(StoryView.story_id)
            .filter(
                StoryView.user_id == current_user_id,
                StoryView.story_id.in_(story_ids),
            )
            .all()
        )
        viewed_ids = {row.story_id for row in viewed_rows}

    return views_counts, viewed_ids


# ── Feed ───────────────────────────────────────────────────────────────────────

@router.get("/stories/feed")
def get_story_feed(
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    """Return active story groups (per user) from followed users + self.

    Own group first; then unviewed groups; then fully-viewed groups.
    """
    now = _now()
    following_ids = [
        row.following_id
        for row in db.query(Follow).filter(Follow.follower_id == current_user_id).all()
    ]
    following_ids.append(current_user_id)

    stories = (
        db.query(Story)
        .options(joinedload(Story.user))
        .filter(Story.user_id.in_(following_ids), Story.expires_at > now)
        .order_by(Story.user_id, Story.created_at.asc(), Story.segment_index.asc())
        .all()
    )

    story_ids = [s.id for s in stories]
    views_counts, viewed_ids = _bulk_views(story_ids, current_user_id, db)

    user_map: dict[int, dict] = {}
    for s in stories:
        if s.user_id not in user_map:
            user_map[s.user_id] = {
                "user": user_dict(s.user),
                "stories": [],
                "has_unseen": False,
            }
        is_viewed = s.id in viewed_ids
        user_map[s.user_id]["stories"].append(
            story_dict(s, views_count=views_counts.get(s.id, 0), is_viewed=is_viewed)
        )
        if not is_viewed:
            user_map[s.user_id]["has_unseen"] = True

    # Own group first; then others sorted: unviewed before viewed
    own_group = user_map.pop(current_user_id, None)
    others = sorted(user_map.values(), key=lambda g: 0 if g["has_unseen"] else 1)

    items = []
    if own_group:
        items.append(own_group)
    items.extend(others)

    return {"items": items}


# ── CRUD ───────────────────────────────────────────────────────────────────────

@router.post("/stories", status_code=201)
def create_story(
    body: StoryCreate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    expires = _now() + timedelta(hours=24)
    story = Story(
        user_id=current_user_id,
        media_url=body.media_url,
        media_type=body.media_type,
        caption=body.caption or "",
        story_group_id=str(uuid.uuid4()),
        segment_index=0,
        total_segments=1,
        expires_at=expires,
    )
    db.add(story)
    db.commit()
    db.refresh(story)
    story = (
        db.query(Story)
        .options(joinedload(Story.user))
        .filter(Story.id == story.id)
        .first()
    )
    return {"story": story_dict(story)}


@router.post("/stories/batch", status_code=201)
def create_stories_batch(
    body: StoriesBatchCreate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    """Create multiple story segments sharing a single story_group_id."""
    group_id = str(uuid.uuid4())
    expires = _now() + timedelta(hours=24)

    new_stories = []
    for seg in body.segments:
        s = Story(
            user_id=current_user_id,
            media_url=seg.media_url,
            media_type=body.media_type,
            caption=body.caption or "",
            story_group_id=group_id,
            segment_index=seg.segment_index,
            total_segments=seg.total_segments,
            expires_at=expires,
        )
        db.add(s)
        new_stories.append(s)

    db.commit()

    story_ids = [s.id for s in new_stories]
    loaded = (
        db.query(Story)
        .options(joinedload(Story.user))
        .filter(Story.id.in_(story_ids))
        .order_by(Story.segment_index.asc())
        .all()
    )
    return {"stories": [story_dict(s) for s in loaded]}


@router.get("/stories/{story_id}")
def get_story(
    story_id: int,
    db: Session = Depends(get_db),
    current_user_id=Depends(optional_auth),
):
    now = _now()
    story = (
        db.query(Story)
        .options(joinedload(Story.user))
        .filter(Story.id == story_id, Story.expires_at > now)
        .first()
    )
    if not story:
        raise HTTPException(status_code=404, detail="story not found")
    views_counts, viewed_ids = _bulk_views([story_id], current_user_id, db)
    return {
        "story": story_dict(
            story,
            views_count=views_counts.get(story_id, 0),
            is_viewed=story_id in viewed_ids,
        )
    }


@router.delete("/stories/{story_id}")
def delete_story(
    story_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    story = db.query(Story).filter(Story.id == story_id).first()
    if not story:
        raise HTTPException(status_code=404, detail="story not found")
    if story.user_id != current_user_id:
        raise HTTPException(status_code=403, detail="not your story")

    group_id = story.story_group_id
    if group_id:
        # Delete every segment in the group that belongs to this user
        db.query(Story).filter(
            Story.story_group_id == group_id,
            Story.user_id == current_user_id,
        ).delete(synchronize_session=False)
    else:
        db.delete(story)

    db.commit()
    return {"message": "deleted", "story_group_id": group_id}


# ── View recording ─────────────────────────────────────────────────────────────

@router.post("/stories/{story_id}/view")
def view_story(
    story_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    """Record that the current user viewed this story (idempotent)."""
    now = _now()
    story = (
        db.query(Story)
        .filter(Story.id == story_id, Story.expires_at > now)
        .first()
    )
    if not story:
        raise HTTPException(status_code=404, detail="story not found")
    if story.user_id == current_user_id:
        return {"ok": True}  # owners don't count as viewers of their own stories
    existing = (
        db.query(StoryView)
        .filter(StoryView.story_id == story_id, StoryView.user_id == current_user_id)
        .first()
    )
    if not existing:
        db.add(StoryView(story_id=story_id, user_id=current_user_id))
        db.commit()
    return {"ok": True}


# ── Viewers list (owner only) ──────────────────────────────────────────────────

@router.get("/stories/{story_id}/viewers")
def get_story_viewers(
    story_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(require_auth),
):
    story = db.query(Story).filter(Story.id == story_id).first()
    if not story:
        raise HTTPException(status_code=404, detail="story not found")
    if story.user_id != current_user_id:
        raise HTTPException(status_code=403, detail="not your story")

    views = (
        db.query(StoryView)
        .options(joinedload(StoryView.user))
        .filter(StoryView.story_id == story_id)
        .order_by(StoryView.viewed_at.desc())
        .all()
    )

    return {
        "views_count": len(views),
        "viewers": [
            {"user": user_dict(v.user), "viewed_at": fmt_dt(v.viewed_at)}
            for v in views
        ],
    }


# ── Per-user stories ───────────────────────────────────────────────────────────

@router.get("/users/{user_id}/stories")
def get_user_stories(
    user_id: int,
    db: Session = Depends(get_db),
    current_user_id=Depends(optional_auth),
):
    """All active stories for a given user, oldest-first with segment ordering."""
    now = _now()
    stories = (
        db.query(Story)
        .options(joinedload(Story.user))
        .filter(Story.user_id == user_id, Story.expires_at > now)
        .order_by(Story.created_at.asc(), Story.segment_index.asc())
        .all()
    )
    story_ids = [s.id for s in stories]
    views_counts, viewed_ids = _bulk_views(story_ids, current_user_id, db)
    return {
        "stories": [
            story_dict(
                s,
                views_count=views_counts.get(s.id, 0),
                is_viewed=s.id in viewed_ids,
            )
            for s in stories
        ]
    }
