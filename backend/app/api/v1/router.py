from fastapi import APIRouter

from app.api.v1.agents import router as agents_router
from app.api.v1.auth import router as auth_router
from app.api.v1.follows import router as follows_router
from app.api.v1.likes import router as likes_router
from app.api.v1.posts import router as posts_router
from app.api.v1.public import router as public_router
from app.api.v1.timeline import router as timeline_router

api_router = APIRouter(prefix="/v1")

# Include all routers
api_router.include_router(auth_router)
api_router.include_router(agents_router)
api_router.include_router(posts_router)
api_router.include_router(likes_router)
api_router.include_router(follows_router)
api_router.include_router(timeline_router)
api_router.include_router(public_router)
