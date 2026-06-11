from typing import Optional
from pydantic import BaseModel


class ProfileUpdate(BaseModel):
    bio: Optional[str] = None
    profile_picture_url: Optional[str] = None
