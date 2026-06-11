import os
from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError

SECRET_KEY = os.getenv("JWT_SECRET", "change-me")
ALGORITHM = "HS256"


def generate_token(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=24)
    payload = {"user_id": user_id, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("user_id")
        return int(user_id) if user_id is not None else None
    except JWTError:
        return None


def fmt_dt(dt) -> str:
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def user_dict(user) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email or "",
        "bio": user.bio or "",
        "profile_picture_url": user.profile_picture_url or "",
        "created_at": fmt_dt(user.created_at),
    }


def post_dict(post, like_count=0, liked_by_me=False, comment_count=0, saved_by_me=False) -> dict:
    return {
        "id": post.id,
        "user_id": post.user_id,
        "user": user_dict(post.user) if post.user else None,
        "image_url": post.image_url,
        "caption": post.caption or "",
        "created_at": fmt_dt(post.created_at),
        "like_count": like_count,
        "liked_by_me": liked_by_me,
        "comment_count": comment_count,
        "saved_by_me": saved_by_me,
    }


def comment_dict(comment, replies=None, likes_count=0, is_liked=False) -> dict:
    return {
        "id": comment.id,
        "post_id": comment.post_id,
        "user_id": comment.user_id,
        "user": user_dict(comment.user) if comment.user else None,
        "body": comment.body,
        "parent_comment_id": comment.parent_comment_id,
        "reply_to_user_id": comment.reply_to_user_id,
        "reply_to_user": user_dict(comment.reply_to_user) if getattr(comment, "reply_to_user", None) else None,
        "created_at": fmt_dt(comment.created_at),
        "replies": replies if replies is not None else [],
        "likes_count": likes_count,
        "is_liked": is_liked,
    }


def reel_dict(
    reel, like_count=0, liked_by_me=False, comment_count=0, saved_by_me=False, is_following_user=False
) -> dict:
    return {
        "id": reel.id,
        "user_id": reel.user_id,
        "user": user_dict(reel.user) if reel.user else None,
        "video_url": reel.video_url,
        "thumbnail_url": reel.thumbnail_url or "",
        "caption": reel.caption or "",
        "views_count": reel.views_count or 0,
        "created_at": fmt_dt(reel.created_at),
        "updated_at": fmt_dt(reel.updated_at),
        "like_count": like_count,
        "liked_by_me": liked_by_me,
        "comment_count": comment_count,
        "saved_by_me": saved_by_me,
        "is_following_user": is_following_user,
    }


def reel_comment_dict(comment, replies=None) -> dict:
    return {
        "id": comment.id,
        "reel_id": comment.reel_id,
        "user_id": comment.user_id,
        "user": user_dict(comment.user) if comment.user else None,
        "body": comment.body,
        "parent_comment_id": comment.parent_comment_id,
        "reply_to_user_id": comment.reply_to_user_id,
        "reply_to_user": user_dict(comment.reply_to_user) if getattr(comment, "reply_to_user", None) else None,
        "created_at": fmt_dt(comment.created_at),
        "replies": replies if replies is not None else [],
    }


def story_dict(story, views_count: int = 0, is_viewed: bool = False) -> dict:
    return {
        "id": story.id,
        "user_id": story.user_id,
        "user": user_dict(story.user) if story.user else None,
        "media_url": story.media_url,
        "media_type": story.media_type,
        "caption": story.caption or "",
        "created_at": fmt_dt(story.created_at),
        "expires_at": fmt_dt(story.expires_at),
        "updated_at": fmt_dt(story.updated_at),
        "views_count": views_count,
        "is_viewed": is_viewed,
        "story_group_id": story.story_group_id,
        "segment_index": story.segment_index if story.segment_index is not None else 0,
        "total_segments": story.total_segments if story.total_segments is not None else 1,
    }


def enrich_reel(reel, db, current_user_id=None) -> dict:
    from models import ReelLike, ReelComment, ReelSave, Follow

    like_count = db.query(ReelLike).filter(ReelLike.reel_id == reel.id).count()
    comment_count = db.query(ReelComment).filter(ReelComment.reel_id == reel.id).count()
    liked_by_me = False
    saved_by_me = False
    is_following_user = False
    if current_user_id:
        liked_by_me = (
            db.query(ReelLike)
            .filter(ReelLike.user_id == current_user_id, ReelLike.reel_id == reel.id)
            .first()
            is not None
        )
        saved_by_me = (
            db.query(ReelSave)
            .filter(ReelSave.user_id == current_user_id, ReelSave.reel_id == reel.id)
            .first()
            is not None
        )
        if reel.user_id != current_user_id:
            is_following_user = (
                db.query(Follow)
                .filter(Follow.follower_id == current_user_id, Follow.following_id == reel.user_id)
                .first()
                is not None
            )
    return reel_dict(
        reel,
        like_count=like_count,
        liked_by_me=liked_by_me,
        comment_count=comment_count,
        saved_by_me=saved_by_me,
        is_following_user=is_following_user,
    )


def enrich_post(post, db, current_user_id=None) -> dict:
    from models import Like, Comment, SavedPost

    like_count = db.query(Like).filter(Like.post_id == post.id).count()
    comment_count = db.query(Comment).filter(Comment.post_id == post.id).count()
    liked_by_me = False
    saved_by_me = False
    if current_user_id:
        liked_by_me = (
            db.query(Like)
            .filter(Like.user_id == current_user_id, Like.post_id == post.id)
            .first()
            is not None
        )
        saved_by_me = (
            db.query(SavedPost)
            .filter(SavedPost.user_id == current_user_id, SavedPost.post_id == post.id)
            .first()
            is not None
        )
    return post_dict(post, like_count=like_count, liked_by_me=liked_by_me, comment_count=comment_count, saved_by_me=saved_by_me)


def message_dict(message) -> dict:
    return {
        "id": message.id,
        "conversation_id": message.conversation_id,
        "sender_id": message.sender_id,
        "body": message.body,
        "created_at": fmt_dt(message.created_at),
        "is_deleted_for_everyone": message.is_deleted_for_everyone,
    }


def conversation_dict(conversation, other_user, last_message=None, unread_count=0) -> dict:
    return {
        "id": conversation.id,
        "other_user": user_dict(other_user) if other_user else None,
        "last_message": message_dict(last_message) if last_message else None,
        "unread_count": unread_count,
        "created_at": fmt_dt(conversation.created_at),
    }


def notification_dict(n) -> dict:
    return {
        "id": n.id,
        "type": n.type,
        "entity_id": n.entity_id,
        "is_read": n.is_read,
        "created_at": fmt_dt(n.created_at),
        "actor": {
            "id": n.actor.id,
            "username": n.actor.username,
            "profile_picture_url": n.actor.profile_picture_url or "",
        } if n.actor else None,
    }
