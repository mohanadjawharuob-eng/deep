"""Version 1 of the API.

Modules are mounted here as each milestone lands, so the surface of the API is
readable in one place.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    artifacts,
    auth,
    contexts,
    documents,
    health,
    history,
    labels,
    models3d,
    notifications,
    photographs,
    projects,
    review,
    search,
    sites,
    taxonomy,
    users,
)

api_router = APIRouter()

# System and identity
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)

# Content
api_router.include_router(projects.router)
api_router.include_router(sites.router)
api_router.include_router(artifacts.router)
api_router.include_router(contexts.router)

# Media
api_router.include_router(photographs.router)
api_router.include_router(documents.router)
api_router.include_router(models3d.router)

# Cross-cutting: vocabularies, search, review, history and notifications.
# ``review`` and ``history`` are mounted last because their paths are generic
# over record type (``/{kind}/{id}/…``); putting them after the concrete
# routers means a real route always wins the match.
api_router.include_router(taxonomy.router)
api_router.include_router(search.router)
api_router.include_router(notifications.router)
api_router.include_router(labels.router)
api_router.include_router(review.router)
api_router.include_router(history.router)
