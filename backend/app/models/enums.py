"""Enumerations shared by the ORM models and the API schemas.

Every enum is persisted as a native PostgreSQL ``ENUM`` type. The *values*
below are what lands in the database, so they are lowercase and stable —
renaming one is a migration, not an edit.
"""

from __future__ import annotations

import enum


class UserRole(str, enum.Enum):
    """Global role, ordered from least to most privileged.

    Comparison helpers let permission checks read as
    ``user.role >= UserRole.RESEARCHER``.
    """

    VISITOR = "visitor"
    STUDENT = "student"
    RESEARCHER = "researcher"
    ADMIN = "admin"

    @property
    def rank(self) -> int:
        return _ROLE_RANK[self]

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, UserRole):
            return NotImplemented
        return self.rank < other.rank

    def __le__(self, other: object) -> bool:
        if not isinstance(other, UserRole):
            return NotImplemented
        return self.rank <= other.rank

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, UserRole):
            return NotImplemented
        return self.rank > other.rank

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, UserRole):
            return NotImplemented
        return self.rank >= other.rank


_ROLE_RANK: dict[UserRole, int] = {
    UserRole.VISITOR: 0,
    UserRole.STUDENT: 1,
    UserRole.RESEARCHER: 2,
    UserRole.ADMIN: 3,
}


class PermissionLevel(str, enum.Enum):
    """Per-record grant, also ordered."""

    VIEWER = "viewer"
    EDITOR = "editor"
    OWNER = "owner"

    @property
    def rank(self) -> int:
        return _PERMISSION_RANK[self]

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, PermissionLevel):
            return NotImplemented
        return self.rank >= other.rank

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, PermissionLevel):
            return NotImplemented
        return self.rank > other.rank

    def __le__(self, other: object) -> bool:
        if not isinstance(other, PermissionLevel):
            return NotImplemented
        return self.rank <= other.rank

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, PermissionLevel):
            return NotImplemented
        return self.rank < other.rank


_PERMISSION_RANK: dict[PermissionLevel, int] = {
    PermissionLevel.VIEWER: 0,
    PermissionLevel.EDITOR: 1,
    PermissionLevel.OWNER: 2,
}


class ProjectRole(str, enum.Enum):
    """A user's role inside one project's team."""

    DIRECTOR = "director"
    RESEARCHER = "researcher"
    STUDENT = "student"
    OBSERVER = "observer"


class ProjectStatus(str, enum.Enum):
    PLANNED = "planned"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class ReviewStatus(str, enum.Enum):
    """Approval workflow for student submissions."""

    DRAFT = "draft"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class SiteType(str, enum.Enum):
    SETTLEMENT = "settlement"
    BURIAL = "burial"
    RELIGIOUS = "religious"
    INDUSTRIAL = "industrial"
    MILITARY = "military"
    ROCK_ART = "rock_art"
    UNDERWATER = "underwater"
    CAVE = "cave"
    FIND_SPOT = "find_spot"
    OTHER = "other"


class ProtectionStatus(str, enum.Enum):
    UNESCO = "unesco"
    NATIONAL = "national"
    REGIONAL = "regional"
    LOCAL = "local"
    PROPOSED = "proposed"
    UNPROTECTED = "unprotected"
    UNKNOWN = "unknown"


class ConditionState(str, enum.Enum):
    EXCELLENT = "excellent"
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"
    DESTROYED = "destroyed"
    UNKNOWN = "unknown"


class ConservationStatus(str, enum.Enum):
    STABLE = "stable"
    NEEDS_TREATMENT = "needs_treatment"
    IN_TREATMENT = "in_treatment"
    TREATED = "treated"
    FRAGILE = "fragile"
    UNKNOWN = "unknown"


class ContextType(str, enum.Enum):
    """Single-context recording vocabulary (MoLA / Harris matrix)."""

    LAYER = "layer"
    CUT = "cut"
    FILL = "fill"
    STRUCTURE = "structure"
    SKELETON = "skeleton"
    FEATURE = "feature"
    DEPOSIT = "deposit"
    MASONRY = "masonry"
    OTHER = "other"


class StratigraphicRelation(str, enum.Enum):
    """Harris matrix relationships between two contexts."""

    ABOVE = "above"
    BELOW = "below"
    CUTS = "cuts"
    CUT_BY = "cut_by"
    FILLS = "fills"
    FILLED_BY = "filled_by"
    CONTEMPORARY_WITH = "contemporary_with"
    SAME_AS = "same_as"
    ABUTS = "abuts"
    BONDED_WITH = "bonded_with"


#: Relations that must be mirrored on the other context to keep the matrix
#: consistent, e.g. A *above* B implies B *below* A.
INVERSE_RELATION: dict[StratigraphicRelation, StratigraphicRelation] = {
    StratigraphicRelation.ABOVE: StratigraphicRelation.BELOW,
    StratigraphicRelation.BELOW: StratigraphicRelation.ABOVE,
    StratigraphicRelation.CUTS: StratigraphicRelation.CUT_BY,
    StratigraphicRelation.CUT_BY: StratigraphicRelation.CUTS,
    StratigraphicRelation.FILLS: StratigraphicRelation.FILLED_BY,
    StratigraphicRelation.FILLED_BY: StratigraphicRelation.FILLS,
    StratigraphicRelation.CONTEMPORARY_WITH: StratigraphicRelation.CONTEMPORARY_WITH,
    StratigraphicRelation.SAME_AS: StratigraphicRelation.SAME_AS,
    StratigraphicRelation.ABUTS: StratigraphicRelation.ABUTS,
    StratigraphicRelation.BONDED_WITH: StratigraphicRelation.BONDED_WITH,
}


class DocumentType(str, enum.Enum):
    REPORT = "report"
    PUBLICATION = "publication"
    FIELD_NOTES = "field_notes"
    PERMIT = "permit"
    PLAN = "plan"
    SECTION_DRAWING = "section_drawing"
    SPREADSHEET = "spreadsheet"
    CORRESPONDENCE = "correspondence"
    OTHER = "other"


class Model3DFormat(str, enum.Enum):
    OBJ = "obj"
    PLY = "ply"
    FBX = "fbx"
    GLTF = "gltf"
    GLB = "glb"
    STL = "stl"
    SKETCHFAB = "sketchfab"
    REALITYSCAN = "realityscan"
    METASHAPE = "metashape"
    POTREE = "potree"
    OTHER = "other"


class GeometryKind(str, enum.Enum):
    """What a GIS layer holds, used to pick the right rendering."""

    POINT = "point"
    LINE = "line"
    POLYGON = "polygon"
    MIXED = "mixed"


class LayerCategory(str, enum.Enum):
    TRENCH = "trench"
    GRID = "grid"
    SURVEY_AREA = "survey_area"
    SITE_BOUNDARY = "site_boundary"
    FEATURE = "feature"
    TOPOGRAPHY = "topography"
    GEOPHYSICS = "geophysics"
    ORTHOPHOTO = "orthophoto"
    OTHER = "other"


class ActivityAction(str, enum.Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    RESTORE = "restore"
    LOGIN = "login"
    LOGIN_FAILED = "login_failed"
    LOGOUT = "logout"
    UPLOAD = "upload"
    DOWNLOAD = "download"
    APPROVE = "approve"
    REJECT = "reject"
    SUBMIT = "submit"
    SHARE = "share"
    EXPORT = "export"
    IMPORT = "import"


class NotificationType(str, enum.Enum):
    RECORD_APPROVED = "record_approved"
    RECORD_REJECTED = "record_rejected"
    RECORD_SUBMITTED = "record_submitted"
    COMMENT_ADDED = "comment_added"
    FILE_UPLOADED = "file_uploaded"
    PROJECT_INVITATION = "project_invitation"
    PERMISSION_GRANTED = "permission_granted"
    SYSTEM = "system"


class ResourceType(str, enum.Enum):
    """Polymorphic discriminator for activity, revisions, permissions and
    notifications. Values match the API path segment for each module."""

    PROJECT = "project"
    SITE = "site"
    ARTIFACT = "artifact"
    CONTEXT = "context"
    PHOTOGRAPH = "photograph"
    DOCUMENT = "document"
    MODEL3D = "model3d"
    GIS_LAYER = "gis_layer"
    USER = "user"
    PUBLICATION = "publication"
