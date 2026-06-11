from typing import List

from pydantic import BaseModel


class ConversationCreate(BaseModel):
    user_id: int


class MessageCreate(BaseModel):
    body: str


class SharePostRequest(BaseModel):
    conversation_ids: List[int]


class ShareReelRequest(BaseModel):
    conversation_ids: List[int]
