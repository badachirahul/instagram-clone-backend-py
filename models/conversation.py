from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    # 'accepted' | 'request' | 'rejected'
    status = Column(String, server_default="accepted", default="accepted")
    requester_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    participants = relationship("ConversationParticipant", back_populates="conversation")
    messages = relationship("Message", back_populates="conversation", order_by="Message.created_at")
