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


class Module(str, enum.Enum):
    """A functional area of the platform, permissioned independently.

    A user holds a level in each module separately and additively: being an
    editor in the archaeology module says nothing about whether they can see
    the museum's loan records or the institution's budgets.
    """

    ARCHAEOLOGY = "archaeology"
    MUSEUM = "museum"
    SOCIAL_MEDIA = "social_media"
    MANAGEMENT = "management"
    INVENTORY = "inventory"
    #: Declared before it is built. Adding a value to a PostgreSQL enum later
    #: is a migration that cannot run inside a transaction on older servers,
    #: and a grant for a module that does not exist yet is simply inert.
    ARCHIVE = "archive"


class ModuleLevel(str, enum.Enum):
    """What a user may do *inside* one module, ordered from least to most.

    - ``VIEWER`` reads.
    - ``CONTRIBUTOR`` creates and edits their own work; it goes for approval.
    - ``EDITOR`` edits anyone's work in the module; their own needs no approval.
    - ``SUPERVISOR`` approves submissions, starts projects, manages teams.
    - ``ADMINISTRATOR`` has full control of the module, deletion included.
    """

    VIEWER = "viewer"
    CONTRIBUTOR = "contributor"
    EDITOR = "editor"
    SUPERVISOR = "supervisor"
    ADMINISTRATOR = "administrator"

    @property
    def rank(self) -> int:
        return _MODULE_LEVEL_RANK[self]

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, ModuleLevel):
            return NotImplemented
        return self.rank < other.rank

    def __le__(self, other: object) -> bool:
        if not isinstance(other, ModuleLevel):
            return NotImplemented
        return self.rank <= other.rank

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, ModuleLevel):
            return NotImplemented
        return self.rank > other.rank

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, ModuleLevel):
            return NotImplemented
        return self.rank >= other.rank


_MODULE_LEVEL_RANK: dict[ModuleLevel, int] = {
    ModuleLevel.VIEWER: 0,
    ModuleLevel.CONTRIBUTOR: 1,
    ModuleLevel.EDITOR: 2,
    ModuleLevel.SUPERVISOR: 3,
    ModuleLevel.ADMINISTRATOR: 4,
}


class ShapeKind(str, enum.Enum):
    """What a region on a floor plan is.

    ``RECT`` and ``POLYGON`` describe an area — a cabinet, a case, a room. A
    ``PIN`` marks a single point, for an object standing on the floor rather
    than filed in a container. ``WALL`` and ``LABEL`` are scenery: a plan with
    no walls on it is a plan nobody can orient themselves in.
    """

    RECT = "rect"
    POLYGON = "polygon"
    CIRCLE = "circle"
    PIN = "pin"
    WALL = "wall"
    LABEL = "label"


class ImportStatus(str, enum.Enum):
    """Where a spreadsheet import has got to.

    The states are deliberately separate. ``ANALYSED`` means the file has been
    read and its columns guessed at; ``MAPPED`` means a person has approved
    what each column fills; ``PREVIEWED`` means every row has been validated
    and the result reported. Only ``COMMITTED`` has written anything.
    """

    ANALYSED = "analysed"
    MAPPED = "mapped"
    PREVIEWED = "previewed"
    COMMITTED = "committed"
    FAILED = "failed"
    REVERTED = "reverted"


class StorageKind(str, enum.Enum):
    """A rung on the storage hierarchy, ordered from outermost to innermost.

    Institution → Building → Floor → Room → Cabinet → Shelf → Drawer → Box.

    The order is enforced only against *inversion*: a child may not sit at a
    shallower rung than its parent. Skipping rungs is fine — a crate on a room
    floor has no cabinet — and so is repeating one, because finds bags inside a
    crate really are boxes inside a box. A hierarchy that refuses to describe
    the actual building is one people stop using.
    """

    INSTITUTION = "institution"
    BUILDING = "building"
    FLOOR = "floor"
    ROOM = "room"
    CABINET = "cabinet"
    SHELF = "shelf"
    DRAWER = "drawer"
    BOX = "box"

    @property
    def depth(self) -> int:
        return _STORAGE_KIND_DEPTH[self]


_STORAGE_KIND_DEPTH: dict[StorageKind, int] = {
    StorageKind.INSTITUTION: 0,
    StorageKind.BUILDING: 1,
    StorageKind.FLOOR: 2,
    StorageKind.ROOM: 3,
    StorageKind.CABINET: 4,
    StorageKind.SHELF: 5,
    StorageKind.DRAWER: 6,
    StorageKind.BOX: 7,
}


class MovementReason(str, enum.Enum):
    """Why an object left one place for another.

    Kept as a closed list because "where has this been and why" is a question
    a registrar has to answer from the record years later, and free text does
    not aggregate.
    """

    ACCESSION = "accession"
    REORGANISATION = "reorganisation"
    CONSERVATION = "conservation"
    ANALYSIS = "analysis"
    EXHIBITION = "exhibition"
    LOAN_OUT = "loan_out"
    LOAN_RETURN = "loan_return"
    EXCAVATION = "excavation"
    REPATRIATION = "repatriation"
    DISPOSAL = "disposal"
    CORRECTION = "correction"
    OTHER = "other"


class AcquisitionMethod(str, enum.Enum):
    """How an object entered the collection.

    A closed list because provenance is the first thing anyone asks about, and
    "how did you get this" is a question with legal weight. Free text does not
    aggregate and does not audit.
    """

    EXCAVATION = "excavation"
    SURVEY = "survey"
    DONATION = "donation"
    BEQUEST = "bequest"
    PURCHASE = "purchase"
    EXCHANGE = "exchange"
    TRANSFER = "transfer"
    FIELD_COLLECTION = "field_collection"
    SEIZURE = "seizure"
    REPATRIATION = "repatriation"
    UNKNOWN = "unknown"


class ObjectStatus(str, enum.Enum):
    """Where an object stands in the collection's own process."""

    #: Arrived but not yet formally accessioned.
    TEMPORARY = "temporary"
    ACCESSIONED = "accessioned"
    ON_DISPLAY = "on_display"
    IN_CONSERVATION = "in_conservation"
    ON_LOAN = "on_loan"
    #: Formally removed from the collection — sold, transferred, destroyed.
    DEACCESSIONED = "deaccessioned"
    MISSING = "missing"
    DESTROYED = "destroyed"


class TreatmentType(str, enum.Enum):
    """What was done to an object, in conservation terms."""

    EXAMINATION = "examination"
    CLEANING = "cleaning"
    CONSOLIDATION = "consolidation"
    STABILISATION = "stabilisation"
    RECONSTRUCTION = "reconstruction"
    MOUNTING = "mounting"
    REHOUSING = "rehousing"
    ANALYSIS = "analysis"
    MONITORING = "monitoring"
    OTHER = "other"


class ExhibitionStatus(str, enum.Enum):
    PLANNED = "planned"
    IN_PREPARATION = "in_preparation"
    OPEN = "open"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class LoanDirection(str, enum.Enum):
    """Whether the object is going out or coming in.

    Both directions exist because they are different paperwork with different
    obligations, and an institution that only lends today may borrow tomorrow.
    """

    OUTGOING = "outgoing"
    INCOMING = "incoming"


class LoanStatus(str, enum.Enum):
    REQUESTED = "requested"
    APPROVED = "approved"
    DECLINED = "declined"
    IN_TRANSIT = "in_transit"
    ON_LOAN = "on_loan"
    RETURNED = "returned"
    CANCELLED = "cancelled"


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
    MUSEUM_OBJECT = "museum_object"
