"""Version 1 of the API.

Modules are mounted here as each milestone lands, so the surface of the API is
readable in one place.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    activities,
    artifacts,
    auth,
    branding,
    contexts,
    documents,
    exports,
    floorplans,
    formlayouts,
    gis,
    health,
    history,
    imports,
    inventory,
    labels,
    library,
    management,
    mediafolders,
    models3d,
    museum,
    notifications,
    photographs,
    projects,
    review,
    search,
    sites,
    social,
    spatial,
    storage,
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

# Physical storage: one hierarchy shared by every module that holds objects.
api_router.include_router(storage.router)

# Spatial: layers and their features, plus search by radius, box and polygon.
api_router.include_router(gis.router)
api_router.include_router(spatial.router)

# Museum collections, and the form layouts a cataloguing client renders.
api_router.include_router(museum.router)
api_router.include_router(inventory.router)
api_router.include_router(management.router)
api_router.include_router(social.router)
api_router.include_router(activities.router)
api_router.include_router(exports.router)
api_router.include_router(floorplans.router)
api_router.include_router(formlayouts.router)
api_router.include_router(imports.router)

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
api_router.include_router(branding.router)
api_router.include_router(mediafolders.router)
api_router.include_router(library.router)
api_router.include_router(labels.router)
api_router.include_router(review.router)
api_router.include_router(history.router)
