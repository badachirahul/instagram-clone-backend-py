import os
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

load_dotenv()

from database import Base, engine
import models  # registers all ORM models with Base.metadata
from routers import auth, comment_likes, comments, feed, follows, likes, posts, reels, saves, users

Base.metadata.create_all(bind=engine)

app = FastAPI()


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
app.include_router(users.router)
app.include_router(follows.router)
app.include_router(feed.router)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
