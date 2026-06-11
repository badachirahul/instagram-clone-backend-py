from sqlalchemy import Column, Integer, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base


class FollowRequest(Base):
    __tablename__ = "follow_requests"

    id = Column(Integer, primary_key=True, index=True)
    requester_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    recipient_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.now())

    requester = relationship("User", foreign_keys=[requester_id])
    recipient = relationship("User", foreign_keys=[recipient_id])

    __table_args__ = (
        UniqueConstraint("requester_id", "recipient_id", name="uq_follow_request"),
    )
