"""Version 1 of the API.

Modules are mounted here as each milestone lands, so the surface of the API is
readable in one place.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import auth, health, users

api_router = APIRouter()

api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
