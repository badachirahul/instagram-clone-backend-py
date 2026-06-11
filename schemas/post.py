from pydantic import BaseModel


class PostCreate(BaseModel):
    image_url: str
    caption: str = ""


class PostUpdate(BaseModel):
    caption: str = ""
