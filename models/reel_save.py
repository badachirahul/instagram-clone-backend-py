from sqlalchemy import Column, Integer, DateTime, ForeignKey
from sqlalchemy.sql import func
from database import Base


class ReelSave(Base):
    __tablename__ = "reel_saves"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    reel_id = Column(Integer, ForeignKey("reels.id"), primary_key=True)
    created_at = Column(DateTime, server_default=func.now())
