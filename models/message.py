from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from database import Base


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False, index=True)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    body = Column(String, nullable=False)
    message_type = Column(String, nullable=False, server_default="text")
    shared_post_id = Column(Integer, ForeignKey("posts.id"), nullable=True)
    shared_reel_id = Column(Integer, ForeignKey("reels.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)
    is_deleted_for_everyone = Column(Boolean, nullable=False, default=False)

    conversation = relationship("Conversation", back_populates="messages")
    sender = relationship("User", foreign_keys=[sender_id])
    shared_post = relationship("Post", foreign_keys=[shared_post_id])
    shared_reel = relationship("Reel", foreign_keys=[shared_reel_id])
