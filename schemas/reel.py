from pydantic import BaseModel


class ReelCreate(BaseModel):
    video_url: str
    thumbnail_url: str = ""
    caption: str = ""


class ReelUpdate(BaseModel):
    caption: str = ""
