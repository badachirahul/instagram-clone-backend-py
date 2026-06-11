from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base


class Story(Base):
    __tablename__ = "stories"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    media_url = Column(String, nullable=False)
    media_type = Column(String, nullable=False, default="image")  # 'image' | 'video'
    caption = Column(String, default="")
    created_at = Column(DateTime, server_default=func.now())
    expires_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Video segmentation — NULL for image stories; set for all stories going forward
    story_group_id = Column(String, nullable=True, index=True)
    segment_index = Column(Integer, nullable=True, default=0)
    total_segments = Column(Integer, nullable=True, default=1)

    user = relationship("User")
