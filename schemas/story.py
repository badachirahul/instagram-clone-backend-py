from typing import List, Optional
from pydantic import BaseModel


class StoryCreate(BaseModel):
    media_url: str
    media_type: str = "image"
    caption: Optional[str] = ""


class StorySegmentCreate(BaseModel):
    media_url: str
    segment_index: int
    total_segments: int


class StoriesBatchCreate(BaseModel):
    segments: List[StorySegmentCreate]
    media_type: str = "video"
    caption: Optional[str] = ""
