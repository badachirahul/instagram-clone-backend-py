from sqlalchemy import Boolean, Column, Integer, String, DateTime
from sqlalchemy.sql import func
from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    profile_picture_url = Column(String, default="")
    bio = Column(String, default="")
    is_private = Column(Boolean, server_default="false", default=False)
    created_at = Column(DateTime, server_default=func.now())
