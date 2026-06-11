from fastapi import Cookie, HTTPException
from utils import decode_token


def require_auth(token: str = Cookie(default=None)) -> int:
    if token is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    user_id = decode_token(token)
    if user_id is None:
        raise HTTPException(status_code=401, detail="invalid token")
    return user_id


def optional_auth(token: str = Cookie(default=None)):
    if token is None:
        return None
    return decode_token(token)
