import asyncio
import os
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

load_dotenv()

from database import Base, engine
import models  # registers all ORM models with Base.metadata
from routers import auth, comment_likes, comments, feed, follow_requests, follows, likes, messages, notifications, posts, reels, saves, stories, users
from utils import decode_token
from ws_manager import manager as ws_manager

Base.metadata.create_all(bind=engine)

# Schema migrations — safe to run on every startup
from sqlalchemy import text as _text
_MIGRATIONS = [
    # Messages: share columns
    "ALTER TABLE messages ADD COLUMN IF NOT EXISTS message_type VARCHAR NOT NULL DEFAULT 'text'",
    "ALTER TABLE messages ADD COLUMN IF NOT EXISTS shared_post_id INTEGER REFERENCES posts(id)",
    "ALTER TABLE messages ADD COLUMN IF NOT EXISTS shared_reel_id INTEGER REFERENCES reels(id)",
    # Users: private accounts
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_private BOOLEAN NOT NULL DEFAULT FALSE",
    # Conversations: request status + requester tracking
    "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS status VARCHAR NOT NULL DEFAULT 'accepted'",
    "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS requester_id INTEGER REFERENCES users(id)",
    # Follow requests table
    """
    CREATE TABLE IF NOT EXISTS follow_requests (
        id SERIAL PRIMARY KEY,
        requester_id INTEGER NOT NULL REFERENCES users(id),
        recipient_id INTEGER NOT NULL REFERENCES users(id),
        created_at TIMESTAMP DEFAULT NOW(),
        UNIQUE(requester_id, recipient_id)
    )
    """,
]

with engine.connect() as _conn:
    for _sql in _MIGRATIONS:
        try:
            _conn.execute(_text(_sql))
            _conn.commit()
        except Exception:
            _conn.rollback()

app = FastAPI()


@app.on_event("startup")
async def _startup():
    ws_manager.set_event_loop(asyncio.get_event_loop())


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if isinstance(exc.detail, dict):
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(status_code=exc.status_code, content={"message": str(exc.detail)})


app.include_router(auth.router)
app.include_router(posts.router)
app.include_router(likes.router)
app.include_router(saves.router)
app.include_router(reels.router)
app.include_router(comments.router)
app.include_router(comment_likes.router)
app.include_router(stories.router)
app.include_router(users.router)
app.include_router(follows.router)
app.include_router(follow_requests.router)
app.include_router(feed.router)
app.include_router(messages.router)
app.include_router(notifications.router)


@app.websocket("/ws/messages")
async def websocket_messages(ws: WebSocket):
    token = ws.cookies.get("token")
    if not token:
        await ws.close(code=1008)
        return

    user_id = decode_token(token)
    if not user_id:
        await ws.close(code=1008)
        return

    await ws_manager.connect(user_id, ws)
    try:
        while True:
            # Keep the connection alive; sending is triggered by REST calls.
            await ws.receive_text()
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        ws_manager.disconnect(user_id, ws)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
