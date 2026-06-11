import bcrypt
from fastapi import APIRouter, Depends, Response, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from dependencies import require_auth
from models import User
from schemas.auth import LoginIn, RegisterIn
from utils import generate_token, user_dict

router = APIRouter(prefix="/auth")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


@router.post("/register", status_code=201)
def register(body: RegisterIn, response: Response, db: Session = Depends(get_db)):
    existing = db.query(User).filter(
        (User.username == body.username) | (User.email == body.email)
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="username or email already taken")

    user = User(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = generate_token(user.id)
    response.set_cookie("token", token, max_age=86400, path="/", httponly=True, samesite="lax", secure=False)
    return {"user": user_dict(user)}


@router.post("/login")
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid email or password")

    token = generate_token(user.id)
    response.set_cookie("token", token, max_age=86400, path="/", httponly=True, samesite="lax", secure=False)
    return {"user": user_dict(user)}


@router.get("/me")
def me(db: Session = Depends(get_db), current_user_id: int = Depends(require_auth)):
    user = db.query(User).filter(User.id == current_user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="user not found")
    return {"user": user_dict(user)}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("token", path="/")
    return {"message": "logged out"}
