"""ORM models.

Importing this package registers every table on ``Base.metadata``; Alembic's
``env.py`` relies on that for autogeneration, so new model modules must be
added here.
"""

from app.db.base import Base
from app.models.artifact import Artifact, artifact_materials, artifact_publications
from app.models.audit import ActivityLog, Comment, Notification, Revision
from app.models.context import ContextRelationship, ExcavationContext
from app.models.enums import (
    ActivityAction,
    ConditionState,
    ConservationStatus,
    ContextType,
    DocumentType,
    GeometryKind,
    LayerCategory,
    Model3DFormat,
    Module,
    ModuleLevel,
    MovementReason,
    NotificationType,
    PermissionLevel,
    ProjectRole,
    ProjectStatus,
    ProtectionStatus,
    ResourceType,
    ReviewStatus,
    SiteType,
    StorageKind,
    StratigraphicRelation,
    UserRole,
)
from app.models.gis import GisFeature, GisLayer
from app.models.media import Document, Model3D, Photograph
from app.models.project import Project, ProjectMembership
from app.models.site import Site
from app.models.storage import StorageLocation, StorageMovement
from app.models.taxonomy import Material, ObjectCategory, Period, Publication, SystemSetting
from app.models.user import RecordPermission, RefreshToken, User, UserModuleAccess

__all__ = [
    "ActivityAction",
    "ActivityLog",
    "Artifact",
    "Base",
    "Comment",
    "ConditionState",
    "ConservationStatus",
    "ContextRelationship",
    "ContextType",
    "Document",
    "DocumentType",
    "ExcavationContext",
    "GeometryKind",
    "GisFeature",
    "GisLayer",
    "LayerCategory",
    "Material",
    "Model3D",
    "Model3DFormat",
    "Notification",
    "NotificationType",
    "ObjectCategory",
    "Period",
    "PermissionLevel",
    "Photograph",
    "Project",
    "ProjectMembership",
    "ProjectRole",
    "ProjectStatus",
    "ProtectionStatus",
    "Publication",
    "Module",
    "ModuleLevel",
    "MovementReason",
    "RecordPermission",
    "RefreshToken",
    "ResourceType",
    "Revision",
    "ReviewStatus",
    "Site",
    "StorageKind",
    "StorageLocation",
    "StorageMovement",
    "SiteType",
    "StratigraphicRelation",
    "SystemSetting",
    "User",
    "UserModuleAccess",
    "UserRole",
    "artifact_materials",
    "artifact_publications",
]
