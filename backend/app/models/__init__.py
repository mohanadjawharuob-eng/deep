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
    AcquisitionMethod,
    ActivityAction,
    ConditionState,
    ConservationStatus,
    ContextType,
    DocumentType,
    ExhibitionStatus,
    GeometryKind,
    LayerCategory,
    LoanDirection,
    LoanStatus,
    Model3DFormat,
    Module,
    ModuleLevel,
    MovementReason,
    NotificationType,
    ObjectStatus,
    PermissionLevel,
    ProjectRole,
    ProjectStatus,
    ProtectionStatus,
    ResourceType,
    ReviewStatus,
    SiteType,
    StorageKind,
    StratigraphicRelation,
    TreatmentType,
    UserRole,
)
from app.models.gis import GisFeature, GisLayer
from app.models.imports import ImportBatch
from app.models.media import Document, Model3D, Photograph
from app.models.museum import (
    Collection,
    ConservationRecord,
    EnvironmentalReading,
    Exhibition,
    ExhibitionItem,
    Loan,
    LoanItem,
    MuseumObject,
)
from app.models.project import Project, ProjectMembership
from app.models.site import Site
from app.models.storage import StorageLocation, StorageMovement
from app.models.taxonomy import Material, ObjectCategory, Period, Publication, SystemSetting
from app.models.user import RecordPermission, RefreshToken, User, UserModuleAccess

__all__ = [
    "TreatmentType",
    "ObjectStatus",
    "MuseumObject",
    "LoanStatus",
    "LoanItem",
    "LoanDirection",
    "Loan",
    "ExhibitionStatus",
    "ExhibitionItem",
    "Exhibition",
    "EnvironmentalReading",
    "ConservationRecord",
    "Collection",
    "AcquisitionMethod",
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
    "ImportBatch",
    "ImportStatus",
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
