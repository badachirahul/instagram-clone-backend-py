from typing import Optional
from pydantic import BaseModel


class CommentCreate(BaseModel):
    body: str
    parent_comment_id: Optional[int] = None
    reply_to_user_id: Optional[int] = None
