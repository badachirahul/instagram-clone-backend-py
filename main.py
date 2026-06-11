import asyncio
import os
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

load_dotenv()

from database import Base, engine
import models  # registers all ORM models with Base.metadata
from routers import auth, comment_likes, comments, feed, follows, likes, messages, posts, reels, saves, stories, users
from utils import decode_token
from ws_manager import manager as ws_manager

Base.metadata.create_all(bind=engine)

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
app.include_router(feed.router)
app.include_router(messages.router)


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
            # receive_text() will raise on disconnect or client close.
            await ws.receive_text()
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        ws_manager.disconnect(user_id, ws)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
