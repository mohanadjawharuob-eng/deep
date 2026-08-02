"""Populate a fresh database.

Run as ``python -m scripts.seed`` (the container entrypoint does this after
migrations). The script is **idempotent**: it looks each record up before
inserting, so it is safe on every boot.

Two layers are created:

*Reference data* — the first administrator, the controlled vocabularies and
the default system settings. Always created.

*Sample data* — a demonstration project with sites, contexts, artifacts and a
few media records, so a new deployment has something to look at. Skipped unless
``--with-samples`` is passed or ``SEED_SAMPLE_DATA=true`` is set.

The sample photographs are *drawn*, not shipped: a placeholder card with a
scale bar, generated at seed time and pushed through the same storage and
thumbnail services the upload endpoint uses. That keeps the repository free of
binary fixtures and means the demonstration exercises the real path rather than
inserting rows that point at files nobody wrote.
"""

from __future__ import annotations

import argparse
import io
import logging
import os
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import (
    AcquisitionMethod,
    ActivityAction,
    ActivityLog,
    Artifact,
    Budget,
    CalendarEvent,
    CalibrationResult,
    Collection,
    ConditionState,
    ConservationRecord,
    ConservationStatus,
    Consumable,
    ContextRelationship,
    ContextType,
    Document,
    DocumentType,
    Equipment,
    ExcavationContext,
    Expense,
    ExpenseCategory,
    ExpenseStatus,
    GeometryKind,
    GisFeature,
    GisLayer,
    KitTemplate,
    KitTemplateLine,
    LayerCategory,
    Material,
    MovementReason,
    MuseumObject,
    ObjectCategory,
    ObjectStatus,
    Period,
    Photograph,
    PostAsset,
    PostKind,
    PostMetric,
    PostStatus,
    Project,
    ProjectMembership,
    ProjectRole,
    ProjectStatus,
    ProtectionStatus,
    ResourceType,
    Site,
    SiteType,
    SocialAccount,
    SocialPlatform,
    SocialPost,
    StockReason,
    StorageKind,
    StorageLocation,
    StratigraphicRelation,
    SystemSetting,
    Task,
    TaskPriority,
    TaskStatus,
    TreatmentType,
    User,
    UserRole,
)
from app.services import access, accession, geo, images, inventory, outreach
from app.services import documents as document_service
from app.services import storage_locations as storage_tree
from app.services.storage import (
    CATEGORY_DOCUMENTS,
    CATEGORY_PHOTOGRAPHS,
    CATEGORY_THUMBNAILS,
    storage,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
logger = logging.getLogger("seed")


# --------------------------------------------------------------------------
# Reference data
# --------------------------------------------------------------------------
def _slug(value: str) -> str:
    return "-".join(value.lower().replace("/", " ").split())


#: (name, abbreviation, start_year, end_year, colour). Years are signed:
#: negative is BCE. Deliberately generic — a deployment replaces these with
#: its own regional chronology from the administration panel.
PERIODS: list[tuple[str, str | None, int | None, int | None, str]] = [
    ("Palaeolithic", "PAL", -3300000, -10000, "#7c5e48"),
    ("Mesolithic", "MES", -10000, -8000, "#a07d5a"),
    ("Neolithic", "NEO", -8000, -3300, "#8aa05a"),
    ("Chalcolithic", "CHL", -4500, -3300, "#b08a3e"),
    ("Early Bronze Age", "EBA", -3300, -2100, "#c2703d"),
    ("Middle Bronze Age", "MBA", -2100, -1550, "#b9603a"),
    ("Late Bronze Age", "LBA", -1550, -1200, "#a94f38"),
    ("Iron Age", "IA", -1200, -539, "#8c4a4a"),
    ("Classical", "CLA", -539, 330, "#4a6fa5"),
    ("Roman", "ROM", -27, 476, "#5b7fb5"),
    ("Byzantine", "BYZ", 330, 1453, "#6a5fa5"),
    ("Medieval", "MED", 476, 1500, "#5f7a6a"),
    ("Post-Medieval", "PMD", 1500, 1800, "#6b6b6b"),
    ("Modern", "MOD", 1800, None, "#8a8a8a"),
]

#: (name, group)
MATERIALS: list[tuple[str, str]] = [
    ("Ceramic", "ceramic"),
    ("Terracotta", "ceramic"),
    ("Flint", "stone"),
    ("Obsidian", "stone"),
    ("Basalt", "stone"),
    ("Limestone", "stone"),
    ("Marble", "stone"),
    ("Sandstone", "stone"),
    ("Copper", "metal"),
    ("Bronze", "metal"),
    ("Iron", "metal"),
    ("Lead", "metal"),
    ("Silver", "metal"),
    ("Gold", "metal"),
    ("Bone", "organic"),
    ("Antler", "organic"),
    ("Ivory", "organic"),
    ("Shell", "organic"),
    ("Wood", "organic"),
    ("Textile", "organic"),
    ("Leather", "organic"),
    ("Glass", "vitreous"),
    ("Faience", "vitreous"),
    ("Plaster", "composite"),
    ("Mudbrick", "composite"),
]

#: (name, parent name or None)
CATEGORIES: list[tuple[str, str | None]] = [
    ("Vessel", None),
    ("Amphora", "Vessel"),
    ("Bowl", "Vessel"),
    ("Jar", "Vessel"),
    ("Jug", "Vessel"),
    ("Cooking pot", "Vessel"),
    ("Lamp", "Vessel"),
    ("Tool", None),
    ("Blade", "Tool"),
    ("Scraper", "Tool"),
    ("Core", "Tool"),
    ("Grinding stone", "Tool"),
    ("Needle", "Tool"),
    ("Weapon", None),
    ("Arrowhead", "Weapon"),
    ("Spearhead", "Weapon"),
    ("Dagger", "Weapon"),
    ("Ornament", None),
    ("Bead", "Ornament"),
    ("Pendant", "Ornament"),
    ("Ring", "Ornament"),
    ("Fibula", "Ornament"),
    ("Coin", None),
    ("Figurine", None),
    ("Architectural element", None),
    ("Inscription", None),
    ("Faunal remains", None),
    ("Human remains", None),
    ("Botanical remains", None),
]

#: (key, value, type, description, public)
SETTINGS: list[tuple[str, str, str, str, bool]] = [
    ("site.title", "Archaeological Research Platform", "string", "Name shown in the header", True),
    ("map.default_latitude", "34.8021", "float", "Initial map centre latitude", True),
    ("map.default_longitude", "38.9968", "float", "Initial map centre longitude", True),
    ("map.default_zoom", "6", "int", "Initial map zoom level", True),
    (
        "map.tile_url",
        "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        "string",
        "Leaflet tile template",
        True,
    ),
    ("map.tile_attribution", "© OpenStreetMap contributors", "string", "Tile attribution", True),
    ("registration.open", "true", "bool", "Allow self-service registration", True),
    ("registration.default_role", "student", "string", "Role granted to new accounts", False),
    (
        "uploads.max_size_mb",
        str(settings.MAX_UPLOAD_SIZE_MB),
        "int",
        "Largest accepted upload",
        True,
    ),
    ("backup.retention_days", "30", "int", "How long nightly dumps are kept", False),
    (
        "approval.required_for_students",
        "true",
        "bool",
        "Student submissions await researcher approval",
        False,
    ),
]


def seed_admin(session: Session) -> User:
    """Create the first administrator, or report the existing one."""
    existing = session.scalar(
        select(User).where(func.lower(User.email) == settings.FIRST_ADMIN_EMAIL.lower())
    )
    if existing is not None:
        logger.info("Administrator %s already exists", existing.email)
        return existing

    admin = User(
        email=settings.FIRST_ADMIN_EMAIL.lower(),
        username=settings.FIRST_ADMIN_USERNAME,
        full_name="Platform Administrator",
        hashed_password=hash_password(settings.FIRST_ADMIN_PASSWORD),
        role=UserRole.ADMIN,
        is_active=True,
        is_verified=True,
    )
    session.add(admin)
    session.flush()
    # No module rows: a platform administrator holds every module implicitly.
    session.add(
        ActivityLog(
            action=ActivityAction.CREATE,
            user_id=admin.id,
            user_label=admin.username,
            resource_type=ResourceType.USER,
            resource_id=admin.id,
            resource_label=admin.username,
            summary="First administrator created by the seed script",
        )
    )
    logger.info("Created administrator %s", admin.email)
    if settings.FIRST_ADMIN_PASSWORD == "ChangeMe!2024":
        logger.warning("The administrator is using the default password — change it now.")
    return admin


def seed_vocabularies(session: Session) -> None:
    """Insert periods, materials and object categories if absent."""
    for name, abbreviation, start, end, color in PERIODS:
        slug = _slug(name)
        if session.scalar(select(Period).where(Period.slug == slug)) is None:
            session.add(
                Period(
                    name=name,
                    slug=slug,
                    abbreviation=abbreviation,
                    start_year=start,
                    end_year=end,
                    color=color,
                    sort_order=PERIODS.index((name, abbreviation, start, end, color)),
                )
            )

    for name, group in MATERIALS:
        slug = _slug(name)
        if session.scalar(select(Material).where(Material.slug == slug)) is None:
            session.add(Material(name=name, slug=slug, group=group))

    session.flush()

    # Parents first, so children can resolve ``parent_id`` in the same pass.
    for name, parent_name in CATEGORIES:
        slug = _slug(name)
        if session.scalar(select(ObjectCategory).where(ObjectCategory.slug == slug)) is not None:
            continue
        parent = None
        if parent_name:
            parent = session.scalar(
                select(ObjectCategory).where(ObjectCategory.slug == _slug(parent_name))
            )
        session.add(ObjectCategory(name=name, slug=slug, parent_id=parent.id if parent else None))
        session.flush()

    logger.info(
        "Vocabularies ready: %d periods, %d materials, %d categories",
        session.scalar(select(func.count()).select_from(Period)),
        session.scalar(select(func.count()).select_from(Material)),
        session.scalar(select(func.count()).select_from(ObjectCategory)),
    )


def seed_settings(session: Session) -> None:
    for key, value, value_type, description, is_public in SETTINGS:
        if session.scalar(select(SystemSetting).where(SystemSetting.key == key)) is None:
            session.add(
                SystemSetting(
                    key=key,
                    value=value,
                    value_type=value_type,
                    description=description,
                    is_public=is_public,
                )
            )
    logger.info("System settings ready")


# --------------------------------------------------------------------------
# Sample data
# --------------------------------------------------------------------------
DEMO_USERS = [
    (
        "researcher@example.org",
        "e.marchetti",
        "Elena Marchetti",
        UserRole.RESEARCHER,
        "University of Bologna",
        "Field Director",
    ),
    (
        "student@example.org",
        "j.okonkwo",
        "Jide Okonkwo",
        UserRole.STUDENT,
        "University of Bologna",
        "Graduate Student",
    ),
    ("visitor@example.org", "visitor", "Public Visitor", UserRole.VISITOR, None, None),
]

DEMO_PASSWORD = "DemoPass!2024"


def _placeholder_image(caption: str, subtitle: str, width: int = 1400, height: int = 933) -> bytes:
    """Draw a record shot: a labelled card with a scale bar.

    Deliberately obviously synthetic. A stock photograph would be prettier and
    would misrepresent the data as real excavation material, which is exactly
    the confusion an archaeological database should never introduce.
    """
    from PIL import Image, ImageDraw, ImageFont

    def font(size: int):
        # Only the built-in font is guaranteed present; a container has no
        # system fonts. Sized loading needs Pillow 10.1+, hence the fallback.
        try:
            return ImageFont.load_default(size=size)
        except TypeError:  # pragma: no cover - older Pillow
            return ImageFont.load_default()

    image = Image.new("RGB", (width, height), (198, 178, 148))
    draw = ImageDraw.Draw(image)

    # A soft vignette, so the card reads as an image rather than a colour swatch.
    for step in range(60):
        shade = 198 - step
        draw.rectangle(
            [step * 4, step * 3, width - step * 4, height - step * 3],
            outline=(shade, shade - 20, shade - 50),
        )

    # Clean panels behind the text: the vignette lines would otherwise run
    # straight through the captions and make them hard to read.
    draw.rectangle([0, 0, width, 190], fill=(206, 188, 160))
    draw.rectangle([0, height - 175, width, height], fill=(206, 188, 160))

    draw.text((70, 70), caption, fill=(40, 30, 20), font=font(46))
    draw.text((70, 132), subtitle, fill=(95, 72, 50), font=font(30))
    # A hyphen, not an em dash: the built-in bitmap font has no glyph for one
    # and draws a placeholder box over the following word.
    draw.text(
        (70, height - 150),
        "PLACEHOLDER - generated sample, not a real photograph",
        fill=(140, 45, 35),
        font=font(26),
    )

    # A ten-centimetre scale bar in alternating blocks, as on a real record shot.
    bar_x, bar_y, block = 70, height - 100, 60
    for index in range(10):
        colour = (250, 250, 250) if index % 2 == 0 else (30, 30, 30)
        draw.rectangle(
            [bar_x + index * block, bar_y, bar_x + (index + 1) * block, bar_y + 30],
            fill=colour,
            outline=(20, 20, 20),
        )
    draw.text((bar_x + 10 * block + 16, bar_y + 2), "10 cm", fill=(30, 30, 30), font=font(26))

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=88)
    return buffer.getvalue()


def _store_photograph(
    session: Session,
    *,
    title: str,
    subtitle: str,
    description: str,
    shot_type: str,
    user: User,
    project: Project,
    site: Site,
    artifact: Artifact | None = None,
    is_cover: bool = False,
) -> Photograph:
    """Write a generated image through the real storage and thumbnail path."""
    data = _placeholder_image(title, subtitle)
    facts = images.inspect(data)
    stored = storage.save_bytes(data, category=CATEGORY_PHOTOGRAPHS, extension=facts.extension)

    thumbnails: dict[str, str] = {}
    for size in images.thumbnail_sizes():
        thumbnail = images.make_thumbnail(data, size)
        thumbnails[str(size)] = storage.save_bytes(
            thumbnail, category=CATEGORY_THUMBNAILS, extension=".jpg"
        ).path

    photograph = Photograph(
        title=title,
        description=description,
        photographer=user.full_name,
        photographer_id=user.id,
        taken_at=datetime(2024, 5, 7, 9, 20, tzinfo=UTC),
        file_path=stored.path,
        original_filename=f"{_slug(title)}.jpg",
        mime_type=facts.mime_type,
        file_size=stored.size,
        checksum=stored.checksum,
        width=facts.width,
        height=facts.height,
        thumbnails=thumbnails,
        shot_type=shot_type,
        has_scale=True,
        is_cover=is_cover,
        project_id=project.id,
        site_id=site.id,
        artifact_id=artifact.id if artifact is not None else None,
        context_id=artifact.context_id if artifact is not None else None,
        is_public=True,
        owner_id=user.id,
    )
    session.add(photograph)
    return photograph


def seed_sample_media(
    session: Session,
    *,
    project: Project,
    site: Site,
    artifact: Artifact,
    user: User,
) -> None:
    """Attach a few photographs and a document to the demonstration project."""
    if session.scalar(
        select(Photograph).where(Photograph.title == "Tell el-Demo from the south-west")
    ):
        logger.info("Sample media already present; skipping")
        return

    _store_photograph(
        session,
        title="Tell el-Demo from the south-west",
        subtitle="Site overview, 2024 season",
        description=(
            "General view of the mound at the start of the 2024 season, taken "
            "from the survey datum on the south-western spur."
        ),
        shot_type="overview",
        user=user,
        project=project,
        site=site,
        is_cover=True,
    )
    _store_photograph(
        session,
        title="Context 1042 after excavation",
        subtitle="Pit fill, north-facing section",
        description="The fill of pit cut 1041 fully excavated, showing the section face.",
        shot_type="context",
        user=user,
        project=project,
        site=site,
    )
    _store_photograph(
        session,
        title=f"{artifact.inventory_number} — {artifact.name}",
        subtitle="Find photograph with scale",
        description="Record shot taken in the field house before conservation assessment.",
        shot_type="find",
        user=user,
        project=project,
        site=site,
        artifact=artifact,
        is_cover=True,
    )

    notes = (
        "Tell el-Demo — 2024 season field notes (sample)\n"
        "===============================================\n\n"
        "7 May. Continued excavation of pit 1041 in Trench A. The fill (1042) is "
        "a mid-brown silty loam with frequent charcoal flecks and occasional "
        "Early Bronze Age body sherds. Heavy fraction from flotation produced "
        "carbonised grain, sampled as TED-24-012.\n\n"
        "8 May. Section drawn and photographed. Pit appears to cut the earlier "
        "surface 1050, giving a terminus post quem for the sequence above.\n\n"
        "This file is sample content, generated to demonstrate document upload "
        "and full-text search. It describes no real excavation.\n"
    )
    payload = notes.encode("utf-8")
    facts = document_service.inspect(payload, "ted-2024-field-notes.txt")
    stored = storage.save_bytes(payload, category=CATEGORY_DOCUMENTS, extension=facts.extension)

    session.add(
        Document(
            title="Field notes, 2024 season",
            description="Daily excavation notes for Trench A (sample content).",
            document_type=DocumentType.FIELD_NOTES,
            author=user.full_name,
            document_date=date(2024, 5, 8),
            language="en",
            file_path=stored.path,
            original_filename="ted-2024-field-notes.txt",
            mime_type=facts.mime_type,
            file_size=stored.size,
            checksum=stored.checksum,
            extracted_text=document_service.extract_text(payload, facts.extension),
            tags=["field notes", "Trench A", "sample"],
            researcher_id=user.id,
            project_id=project.id,
            site_id=site.id,
            is_public=True,
            owner_id=user.id,
        )
    )
    session.flush()
    logger.info("Sample media created: 3 photographs with thumbnails, 1 document")


def seed_sample_storage(session: Session, *, artifacts: list[Artifact], user: User) -> None:
    """Build a small store and file the sample finds in it.

    The point is to show the hierarchy doing its job: a find sitting in a box,
    on a shelf, in a cabinet, in a room, in a building — and a movement
    register that already has something in it.
    """
    if session.scalar(select(StorageLocation).where(StorageLocation.code == "IOA")):
        logger.info("Sample store already present; skipping")
        return

    institution = storage_tree.create(
        session,
        kind=StorageKind.INSTITUTION,
        name="Institute of Archaeology",
        code="IOA",
        description="Sample institution for the demonstration data.",
    )
    building = storage_tree.create(
        session,
        kind=StorageKind.BUILDING,
        name="Main Store",
        code="MS",
        parent_id=institution.id,
    )
    finds_room = storage_tree.create(
        session,
        kind=StorageKind.ROOM,
        name="Finds Room 203",
        code="203",
        parent_id=building.id,
        target_temperature_c=18.0,
        target_humidity_percent=45.0,
        environment_notes="Stable conditions for mixed ceramic and metal assemblages.",
    )
    lab = storage_tree.create(
        session,
        kind=StorageKind.ROOM,
        name="Conservation Lab",
        code="LAB",
        parent_id=building.id,
        target_temperature_c=20.0,
        target_humidity_percent=50.0,
    )
    cabinet = storage_tree.create(
        session,
        kind=StorageKind.CABINET,
        name="Cabinet 4",
        code="CAB-4",
        parent_id=finds_room.id,
        capacity=400,
    )
    shelf = storage_tree.create(
        session,
        kind=StorageKind.SHELF,
        name="Shelf B",
        code="B",
        parent_id=cabinet.id,
        capacity=80,
    )
    box = storage_tree.create(
        session,
        kind=StorageKind.BOX,
        name="Box 12",
        code="12",
        parent_id=shelf.id,
        capacity=30,
        description="Early Bronze Age ceramics, Trench A.",
    )

    accessioned = datetime(2024, 5, 20, 10, 0, tzinfo=UTC)
    for artifact in artifacts:
        storage_tree.move_object(
            session,
            artifact,
            ResourceType.ARTIFACT,
            to_location_id=box.id,
            reason=MovementReason.ACCESSION,
            notes="Received from the 2024 season and boxed.",
            moved_at=accessioned,
            user=user,
            label=artifact.inventory_number,
        )

    # One object has since gone to the lab, so the register shows a journey
    # rather than a single arrival.
    storage_tree.move_object(
        session,
        artifacts[0],
        ResourceType.ARTIFACT,
        to_location_id=lab.id,
        reason=MovementReason.CONSERVATION,
        notes="Surface consolidation before study.",
        moved_at=accessioned + timedelta(days=21),
        user=user,
        label=artifacts[0].inventory_number,
    )

    session.flush()
    logger.info(
        "Sample storage created: %s, with %d finds filed",
        box.display_path,
        len(artifacts),
    )


def seed_sample_gis(session: Session, *, project: Project, site: Site, user: User) -> None:
    """A trench plan and a survey boundary, so the map has something on it.

    Coordinates are placed around the demonstration site's own position, so
    the layers land where the site does rather than in a different country.
    """
    if session.scalar(select(GisLayer).where(GisLayer.name == "Trench plan, 2024 season")):
        logger.info("Sample GIS layers already present; skipping")
        return

    centre_lon = float(site.longitude)
    centre_lat = float(site.latitude)

    def offset(east: float, north: float) -> list[float]:
        """Metres east/north of the site, as degrees.

        Rough but adequate for demonstration geometry: a degree of latitude is
        ~111 km everywhere, and a degree of longitude shrinks with the cosine
        of the latitude.
        """
        import math

        return [
            round(centre_lon + east / (111_320 * math.cos(math.radians(centre_lat))), 7),
            round(centre_lat + north / 110_540, 7),
        ]

    layer = GisLayer(
        name="Trench plan, 2024 season",
        description="Excavated trenches and the surveyed site boundary (sample data).",
        category=LayerCategory.TRENCH,
        geometry_kind=GeometryKind.POLYGON,
        project_id=project.id,
        site_id=site.id,
        style={"color": "#c2703d", "weight": 2, "fillOpacity": 0.25},
        source_format="geojson",
        source_crs="EPSG:4326",
        is_public=True,
        owner_id=user.id,
    )
    session.add(layer)
    session.flush()

    trenches = [
        (
            "Trench A",
            {"trench": "A", "opened": "2024-04-15", "supervisor": "E. Marchetti"},
            [offset(-20, -20), offset(0, -20), offset(0, 0), offset(-20, 0), offset(-20, -20)],
        ),
        (
            "Trench B",
            {"trench": "B", "opened": "2024-05-02", "supervisor": "J. Okonkwo"},
            [offset(10, -20), offset(30, -20), offset(30, 0), offset(10, 0), offset(10, -20)],
        ),
        (
            "Site boundary",
            {"survey": "2024 topographic survey"},
            [
                offset(-60, -60),
                offset(60, -60),
                offset(60, 60),
                offset(-60, 60),
                offset(-60, -60),
            ],
        ),
    ]

    for name, properties, ring in trenches:
        session.add(
            GisFeature(
                layer_id=layer.id,
                name=name,
                geom=geo.geometry_element(
                    {"type": "Polygon", "coordinates": [ring]}, geo.STORAGE_SRID
                ),
                properties=properties,
                site_id=site.id,
            )
        )

    session.flush()

    layer.feature_count = len(trenches)
    extent = geo.extent_of(session, layer.id)
    layer.bbox = extent.as_list() if extent is not None else None
    session.add(layer)
    session.flush()

    logger.info("Sample GIS created: layer %r with %d features", layer.name, len(trenches))


def seed_sample_museum(session: Session, *, artifacts: list[Artifact], user: User) -> None:
    """A small collection, with one find accessioned out of the excavation.

    Shows the link working in the direction it actually runs: the excavation
    record stays as written in the field, and the museum record carries what
    happened afterwards.
    """
    if session.scalar(select(Collection).where(Collection.code == "ARCH")):
        logger.info("Sample collection already present; skipping")
        return

    collection = Collection(
        name="Archaeological Collection",
        code="ARCH",
        description="Sample collection for the demonstration data.",
        accession_pattern="{prefix}.{year}.{seq:04d}",
        accession_prefix="IOA",
        institution="Institute of Archaeology",
        is_public=True,
        owner_id=user.id,
    )
    session.add(collection)
    session.flush()

    accessioned = MuseumObject(
        collection_id=collection.id,
        accession_number=accession.next_number(session, collection, when=date(2024, 9, 12)),
        title="Everted-rim cooking pot",
        description=(
            "Handmade cooking pot with an everted rim, heavily sooted on the "
            "exterior. Reassembled from eleven sherds."
        ),
        object_type="Cooking pot",
        culture="Early Bronze Age Levantine",
        date_from=-3000,
        date_to=-2700,
        materials=["Ceramic"],
        height_mm=182.5,
        diameter_mm=214.0,
        weight_g=1340.0,
        condition=ConditionState.FAIR,
        conservation_status=ConservationStatus.STABLE,
        acquisition_method=AcquisitionMethod.EXCAVATION,
        acquisition_date=date(2024, 9, 12),
        acquisition_source="Tell el-Demo 2024 season",
        provenance=(
            "Excavated 2024, Trench A, context 1042. Transferred to the "
            "institute store at the close of the season."
        ),
        credit_line="Institute of Archaeology, Tell el-Demo excavations",
        status=ObjectStatus.ACCESSIONED,
        artifact_id=artifacts[0].id,
        is_public=True,
        owner_id=user.id,
    )
    session.add(accessioned)

    # A second object with no excavation record — the normal case for most of
    # a collection, and worth showing so the link does not look mandatory.
    donated = MuseumObject(
        collection_id=collection.id,
        accession_number="1974.1a",
        number_is_legacy=True,
        title="Oil lamp",
        description="Wheel-made lamp with a pinched nozzle.",
        object_type="Lamp",
        materials=["Ceramic"],
        condition=ConditionState.GOOD,
        acquisition_method=AcquisitionMethod.DONATION,
        acquisition_date=date(1974, 5, 3),
        acquisition_source="Bequest of A. Whitfield",
        provenance="Said to be from the Homs region; no excavation record.",
        former_number="W.77",
        status=ObjectStatus.ACCESSIONED,
        is_public=True,
        owner_id=user.id,
    )
    session.add(donated)
    session.flush()

    session.add(
        ConservationRecord(
            museum_object_id=accessioned.id,
            treatment_type=TreatmentType.CONSOLIDATION,
            performed_on=date(2024, 10, 2),
            conservator="A. Rossi",
            condition_before=ConditionState.POOR,
            condition_after=ConditionState.FAIR,
            description=(
                "Reassembled from eleven sherds and consolidated. Joins secured "
                "with Paraloid B72; no fills."
            ),
            materials_used="Paraloid B72, 15% in acetone",
            recommendations="Handle by the base. Re-examine in twelve months.",
            next_review_on=date(2025, 10, 2),
            hours_spent=6.5,
            owner_id=user.id,
        )
    )

    logger.info(
        "Sample museum created: collection %s with 2 objects, 1 linked to an excavation record",
        collection.code,
    )


def seed_sample_inventory(session: Session, *, user: User) -> None:
    """Stock the store with a plausible field kit.

    The point is to show the three things the module is for at once: an item
    that is out with somebody, a stock line low enough to be on the reorder
    list, and a packing list that can be built into a kit in one action.
    """
    if session.scalar(select(Equipment).where(Equipment.asset_number == "IOA-TS-01")):
        logger.info("Sample inventory already present; skipping")
        return

    store = session.scalar(select(StorageLocation).where(StorageLocation.code == "MS"))
    home_id = store.id if store else None
    today = date.today()

    equipment = [
        Equipment(
            asset_number="IOA-TS-01",
            name="Total station",
            category="total station",
            manufacturer="Leica",
            model="TS07",
            serial_number="TS07-4471",
            purchased_on=today - timedelta(days=900),
            purchase_price=Decimal("14500.00"),
            currency="USD",
            supplier="Leica Geosystems",
            funding_source="Institute capital grant 2022",
            needs_calibration=True,
            calibration_interval_days=365,
            storage_location_id=home_id,
            owner_id=user.id,
        ),
        Equipment(
            asset_number="IOA-LV-01",
            name="Dumpy level",
            category="level",
            manufacturer="Sokkia",
            model="B40A",
            needs_calibration=True,
            calibration_interval_days=730,
            storage_location_id=home_id,
            owner_id=user.id,
        ),
        Equipment(
            asset_number="IOA-CAM-01",
            name="Field camera 1",
            category="camera",
            manufacturer="Nikon",
            model="D7500",
            storage_location_id=home_id,
            owner_id=user.id,
        ),
        Equipment(
            asset_number="IOA-CAM-02",
            name="Field camera 2",
            category="camera",
            manufacturer="Nikon",
            model="D7500",
            condition_notes="Zoom ring stiff. Usable.",
            storage_location_id=home_id,
            owner_id=user.id,
        ),
        Equipment(
            asset_number="IOA-GPS-01",
            name="Handheld GPS",
            category="gps",
            manufacturer="Garmin",
            model="GPSMAP 66i",
            storage_location_id=home_id,
            owner_id=user.id,
        ),
    ]
    session.add_all(equipment)
    session.flush()

    # A certificate on file, so the calibration tab has something in it and the
    # due date is not simply blank.
    inventory.record_calibration(
        session,
        equipment[0],
        performed_on=today - timedelta(days=200),
        result=CalibrationResult.PASSED,
        performed_by="Regional Metrology Laboratory",
        certificate_number="RML-2025-1184",
        user=user,
    )

    # One item genuinely out, because an equipment register with nothing on
    # loan does not show what it is for.
    inventory.issue(
        session,
        equipment[4],
        borrower_label="Rania Haddad",
        issued_by=user,
        destination="Survey, north ridge",
        taken_at=datetime.now(UTC) - timedelta(days=3),
        due_on=today + timedelta(days=4),
    )

    consumables = [
        ("BAG-S", "Finds bags, small", "bags", "bag", 500, 200),
        ("BAG-L", "Finds bags, large", "bags", "bag", 40, 100),
        ("LABEL-T", "Tyvek labels", "labels", "sheet", 60, 25),
        ("PERMA", "Permatrace", "drawing", "metre", Decimal("12.5"), 5),
        ("BATT-AA", "AA batteries", "power", "cell", 24, 40),
    ]
    for code, name, category, unit, opening, reorder in consumables:
        stock = Consumable(
            code=code,
            name=name,
            category=category,
            unit=unit,
            reorder_level=Decimal(str(reorder)),
            storage_location_id=home_id,
            owner_id=user.id,
        )
        session.add(stock)
        session.flush()
        inventory.apply_stock_change(
            session,
            stock,
            change=Decimal(str(opening)),
            reason=StockReason.STOCKTAKE,
            user=user,
            notes="Opening stock",
        )

    template = KitTemplate(
        name="Standard trench kit",
        description="What a trench needs for a day. Loaded at six in the morning.",
        owner_id=user.id,
    )
    session.add(template)
    session.flush()

    bags_small = session.scalar(select(Consumable).where(Consumable.code == "BAG-S"))
    labels = session.scalar(select(Consumable).where(Consumable.code == "LABEL-T"))
    for position, line in enumerate(
        [
            # A category, not a specific camera: a template pinned to camera 1
            # breaks the day camera 1 goes in for repair.
            KitTemplateLine(equipment_category="camera", quantity=1),
            KitTemplateLine(equipment_category="level", quantity=1),
            KitTemplateLine(consumable_id=bags_small.id, quantity=50),
            KitTemplateLine(consumable_id=labels.id, quantity=5),
            KitTemplateLine(equipment_category="gps", quantity=1, is_optional=True),
        ]
    ):
        line.position = position
        template.lines.append(line)
    session.flush()

    logger.info(
        "Sample inventory created: %d items, %d stock lines, 1 packing list",
        len(equipment),
        len(consumables),
    )


def seed_sample_management(session: Session, *, project: Project, user: User) -> None:
    """A grant with real spending against it, and a few things to do.

    The point is to show the three numbers that matter at once: money paid,
    money committed but not yet paid, and what is genuinely left. A budget with
    nothing against it shows none of that.
    """
    if session.scalar(select(Budget).where(Budget.code == "DEMO-GR-01")):
        logger.info("Sample management data already present; skipping")
        return

    today = date.today()
    grant = Budget(
        code="DEMO-GR-01",
        name="Tell el-Demo survey and excavation",
        funder="National Heritage Research Council",
        grant_reference="NHRC/2024/118",
        amount=Decimal("85000.00"),
        currency="USD",
        starts_on=today - timedelta(days=300),
        ends_on=today + timedelta(days=120),
        project_id=project.id,
        manager_id=user.id,
        manager_label=user.full_name,
        description="Three seasons of survey, excavation and post-excavation.",
        owner_id=user.id,
    )
    session.add(grant)
    session.flush()

    # Paid, committed and planned all present, so the balance on screen is
    # doing the thing the module exists for rather than a single total.
    spending = [
        ("Field team salaries, season 1", 18500, ExpenseCategory.SALARIES, ExpenseStatus.PAID, 250),
        ("Flights, specialist team", 4200, ExpenseCategory.TRAVEL, ExpenseStatus.PAID, 245),
        ("Dig house, ten weeks", 9800, ExpenseCategory.ACCOMMODATION, ExpenseStatus.PAID, 240),
        ("Total station service", 640, ExpenseCategory.EQUIPMENT, ExpenseStatus.PAID, 180),
        ("Finds bags and labels", 380, ExpenseCategory.CONSUMABLES, ExpenseStatus.PAID, 175),
        ("Excavation permit", 1200, ExpenseCategory.PERMITS, ExpenseStatus.PAID, 290),
        (
            "Radiocarbon dating, 12 samples",
            5400,
            ExpenseCategory.ANALYSIS,
            ExpenseStatus.COMMITTED,
            40,
        ),
        (
            "Conservation of the bronze fibula",
            2200,
            ExpenseCategory.CONSERVATION,
            ExpenseStatus.COMMITTED,
            25,
        ),
        ("Season 2 salaries", 19000, ExpenseCategory.SALARIES, ExpenseStatus.PLANNED, -60),
        ("Monograph typesetting", 3500, ExpenseCategory.PUBLICATION, ExpenseStatus.PLANNED, -150),
    ]
    for description, amount, category, state, days_ago in spending:
        spent_on = today - timedelta(days=days_ago)
        session.add(
            Expense(
                budget_id=grant.id,
                description=description,
                amount=Decimal(str(amount)),
                currency="USD",
                category=category,
                status=state,
                spent_on=spent_on,
                paid_on=spent_on + timedelta(days=14) if state is ExpenseStatus.PAID else None,
                project_id=project.id,
                owner_id=user.id,
            )
        )

    tasks = [
        ("Finish the season 1 context sheets", TaskStatus.IN_PROGRESS, TaskPriority.HIGH, 14),
        ("Send radiocarbon samples to the laboratory", TaskStatus.TODO, TaskPriority.URGENT, 3),
        ("Draw the north section of Trench 4", TaskStatus.TODO, TaskPriority.NORMAL, 30),
        ("Photograph the ceramic assemblage", TaskStatus.BLOCKED, TaskPriority.NORMAL, 21),
        ("Renew the excavation permit", TaskStatus.DONE, TaskPriority.HIGH, -20),
        ("Book the dig house for season 2", TaskStatus.TODO, TaskPriority.HIGH, -5),
    ]
    for position, (title, state, priority, due_in) in enumerate(tasks):
        session.add(
            Task(
                title=title,
                status=state,
                priority=priority,
                due_on=today + timedelta(days=due_in),
                project_id=project.id,
                assignee_id=user.id,
                assignee_label=user.full_name,
                completed_at=datetime.now(UTC) if state is TaskStatus.DONE else None,
                position=position,
                owner_id=user.id,
            )
        )

    events = [
        ("Season 2 fieldwork", "field season", 45, 105, True),
        ("Interim report due to the funder", "deadline", 60, None, True),
        ("Ministry inspection", "visit", 20, None, False),
    ]
    for title, kind, starts_in, ends_in, all_day in events:
        session.add(
            CalendarEvent(
                title=title,
                kind=kind,
                starts_at=datetime.now(UTC) + timedelta(days=starts_in),
                ends_at=datetime.now(UTC) + timedelta(days=ends_in) if ends_in else None,
                all_day=all_day,
                project_id=project.id,
                owner_id=user.id,
            )
        )

    logger.info(
        "Sample management data created: 1 grant, %d expenses, %d tasks, %d events",
        len(spending),
        len(tasks),
        len(events),
    )


def seed_sample_social(
    session: Session, *, project: Project, artifact: Artifact, user: User
) -> None:
    """Two channels, a few posts, and one post that would give away a findspot.

    The last of those is the point. A demonstration where the location check
    always comes back clear shows nothing about what the check is for.
    """
    if session.scalar(select(SocialAccount).where(SocialAccount.handle == "telldemo_dig")):
        logger.info("Sample social media already present; skipping")
        return

    now = datetime.now(UTC)

    instagram = SocialAccount(
        platform=SocialPlatform.INSTAGRAM,
        handle="telldemo_dig",
        display_name="Tell el-Demo Excavation",
        url="https://example.org/telldemo_dig",
        description="Field updates from the Tell el-Demo Regional Survey.",
        manager_id=user.id,
        manager_label=user.full_name,
        follower_count=2840,
        owner_id=user.id,
    )
    site_page = SocialAccount(
        platform=SocialPlatform.WEBSITE,
        handle="telldemo.example.org",
        display_name="Project website",
        description="The only channel the institution controls outright.",
        manager_id=user.id,
        manager_label=user.full_name,
        owner_id=user.id,
    )
    session.add_all([instagram, site_page])
    session.flush()

    published = SocialPost(
        account_id=instagram.id,
        title="The bronze fibula",
        body=(
            "A copper-alloy fibula from the 2024 season, now conserved and "
            "catalogued. Roman, probably second century."
        ),
        hashtags=["archaeology", "conservation", "smallfinds"],
        language="en",
        kind=PostKind.POST,
        status=PostStatus.PUBLISHED,
        published_at=now - timedelta(days=21),
        external_url="https://example.org/telldemo_dig/p/fibula",
        project_id=project.id,
        resource_type=ResourceType.ARTIFACT,
        resource_id=artifact.id,
        approved_by_id=user.id,
        approved_at=now - timedelta(days=22),
        approval_note="Cleared with the permit office.",
        owner_id=user.id,
    )
    scheduled = SocialPost(
        account_id=instagram.id,
        title="Season 2 is starting",
        body="We are back on site next month. Follow along here.",
        hashtags=["fieldwork"],
        language="en",
        kind=PostKind.POST,
        status=PostStatus.SCHEDULED,
        scheduled_for=now + timedelta(days=12),
        project_id=project.id,
        owner_id=user.id,
    )
    waiting = SocialPost(
        account_id=instagram.id,
        title="Trench 4 at the end of the season",
        body="The final state of Trench 4 before backfilling.",
        kind=PostKind.POST,
        status=PostStatus.NEEDS_APPROVAL,
        project_id=project.id,
        owner_id=user.id,
    )
    session.add_all([published, scheduled, waiting])
    session.flush()

    # Engagement as a series, so the screen can show whether it kept moving.
    for days_ago, likes, comments, shares, impressions in (
        (20, 180, 11, 4, 3100),
        (14, 402, 26, 19, 7400),
        (2, 471, 31, 24, 8900),
    ):
        session.add(
            PostMetric(
                post_id=published.id,
                recorded_at=now - timedelta(days=days_ago),
                likes=likes,
                comments=comments,
                shares=shares,
                impressions=impressions,
                source="Instagram insights",
            )
        )

    # A photograph that still carries the coordinates the camera wrote. This is
    # what the check exists to find, and a demonstration without one shows
    # nothing.
    geotagged = session.scalar(
        select(Photograph).where(Photograph.latitude.is_not(None)).order_by(Photograph.created_at)
    )
    if geotagged is not None:
        session.add(
            PostAsset(
                post_id=waiting.id,
                photograph_id=geotagged.id,
                position=0,
                alt_text="A rectangular trench with exposed stone walling.",
                credit="Tell el-Demo Regional Survey",
            )
        )
        session.flush()
        outreach.record_location_check(session, waiting)

    logger.info("Sample social media created: 2 channels, 3 posts, 3 engagement readings")


def _resume_samples(session: Session, project: Project) -> None:
    """Run the sample sections a partly-seeded database is missing."""
    site = session.scalar(select(Site).where(Site.project_id == project.id))
    artifacts = list(
        session.scalars(
            select(Artifact).where(Artifact.site_id == site.id).order_by(Artifact.inventory_number)
        )
        if site is not None
        else []
    )
    user = session.scalar(select(User).where(User.email == DEMO_USERS[0][0])) or session.scalar(
        select(User).where(User.role == UserRole.ADMIN)
    )
    if site is None or not artifacts or user is None:
        logger.warning("Sample project is present but incomplete; leaving it alone")
        return

    seed_sample_media(session, project=project, site=site, artifact=artifacts[0], user=user)
    seed_sample_storage(session, artifacts=artifacts, user=user)
    seed_sample_gis(session, project=project, site=site, user=user)
    seed_sample_museum(session, artifacts=artifacts, user=user)
    seed_sample_inventory(session, user=user)
    seed_sample_management(session, project=project, user=user)
    seed_sample_social(session, project=project, artifact=artifacts[0], user=user)


def seed_samples(session: Session, admin: User) -> None:
    """Create a small but complete demonstration project.

    Resumable, not all-or-nothing. A database seeded before the store and the
    museum existed has the project but none of their sample data, and skipping
    on the project alone left it that way for good — reporting "already
    present" about sections that were never written. Each section now guards
    on its own anchor record, so re-running fills in whatever is missing.
    """
    existing = session.scalar(select(Project).where(Project.code == "DEMO-2024"))
    if existing is not None:
        logger.info("Sample project already present; filling in any missing sections")
        _resume_samples(session, existing)
        return

    users: dict[str, User] = {}
    for email, username, full_name, role, institution, position in DEMO_USERS:
        user = session.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(
                email=email,
                username=username,
                full_name=full_name,
                hashed_password=hash_password(DEMO_PASSWORD),
                role=role,
                institution=institution,
                position=position,
                is_active=True,
                is_verified=True,
            )
            session.add(user)
            session.flush()
            access.grant_defaults(session, user)
        users[role.value] = user

    researcher = users[UserRole.RESEARCHER.value]
    student = users[UserRole.STUDENT.value]

    project = Project(
        name="Tell el-Demo Regional Survey and Excavation",
        code="DEMO-2024",
        slug="tell-el-demo-2024",
        description=(
            "A demonstration project illustrating how excavation and survey data "
            "are organised on this platform. All records are fictional."
        ),
        project_type="excavation",
        principal_investigator=researcher.full_name,
        principal_investigator_id=researcher.id,
        institution="University of Bologna",
        partner_institutions=["National Museum of Antiquities"],
        country="Syria",
        region="Homs Governorate",
        latitude=34.7324,
        longitude=36.7137,
        start_date=date(2024, 4, 1),
        end_date=date(2026, 10, 31),
        status=ProjectStatus.ACTIVE,
        funding_source="European Research Council",
        funding_amount=850000,
        funding_currency="EUR",
        permit_number="DGAM-2024-118",
        permit_authority="Directorate-General of Antiquities and Museums",
        keywords=["survey", "Bronze Age", "settlement", "demonstration"],
        is_public=True,
        owner_id=researcher.id,
    )
    session.add(project)
    session.flush()

    for user, role in (
        (researcher, ProjectRole.DIRECTOR),
        (student, ProjectRole.STUDENT),
        (admin, ProjectRole.RESEARCHER),
    ):
        session.add(
            ProjectMembership(
                project_id=project.id, user_id=user.id, role=role, invited_by_id=researcher.id
            )
        )

    periods = {p.slug: p for p in session.scalars(select(Period)).all()}
    materials = {m.slug: m for m in session.scalars(select(Material)).all()}
    categories = {c.slug: c for c in session.scalars(select(ObjectCategory)).all()}

    site = Site(
        project_id=project.id,
        name="Tell el-Demo",
        alternative_names=["Tall ad-Dimu", "Demo Höyük"],
        code="TED",
        description=(
            "A 4.5-hectare multi-period mound rising 18 m above the surrounding plain, "
            "with occupation from the Late Chalcolithic through the Iron Age."
        ),
        site_type=SiteType.SETTLEMENT,
        latitude=34.7324,
        longitude=36.7137,
        geom="SRID=4326;POINT(36.7137 34.7324)",
        elevation=512.0,
        location_accuracy_m=5.0,
        country="Syria",
        region="Homs Governorate",
        district="Al-Qusayr",
        period_id=periods["early-bronze-age"].id,
        period_text="Late Chalcolithic – Iron Age",
        dating_method="Ceramic typology; two radiocarbon determinations",
        date_from=-3500,
        date_to=-600,
        protection_status=ProtectionStatus.NATIONAL,
        condition=ConditionState.FAIR,
        threats=["agricultural encroachment", "erosion"],
        land_use="Cereal cultivation on the lower slopes",
        discovery_date=date(1967, 6, 12),
        discovered_by="R. Braidwood regional survey",
        excavation_start=date(2024, 4, 15),
        notes="Surface collection in 2023 recovered Early Bronze Age sherds across the summit.",
        keywords=["tell", "settlement mound"],
        is_public=True,
        owner_id=researcher.id,
    )
    session.add(site)
    session.flush()

    # Two stratified contexts, related as a cut and its fill.
    cut = ExcavationContext(
        site_id=site.id,
        context_number="1042",
        context_type=ContextType.CUT,
        description="Sub-circular pit cut, 1.4 m in diameter, with steep sides and a flat base.",
        interpretation="Storage pit, later reused for refuse disposal.",
        trench="A",
        area="Summit",
        square="A4",
        stratigraphic_unit="SU-1042",
        phase="Phase 3",
        length_cm=140,
        width_cm=132,
        depth_cm=68,
        top_elevation=511.42,
        bottom_elevation=510.74,
        latitude=34.7325,
        longitude=36.7138,
        geom="SRID=4326;POINT(36.7138 34.7325)",
        excavated_by="J. Okonkwo",
        excavation_date=date(2024, 5, 3),
        recorded_by="E. Marchetti",
        period_id=periods["early-bronze-age"].id,
        date_from=-2900,
        date_to=-2600,
        is_public=True,
        owner_id=student.id,
    )
    fill = ExcavationContext(
        site_id=site.id,
        context_number="1041",
        context_type=ContextType.FILL,
        description="Loose dark brown silty fill with frequent charcoal flecks and sherds.",
        interpretation="Single-episode backfill of pit [1042].",
        trench="A",
        area="Summit",
        square="A4",
        stratigraphic_unit="SU-1041",
        phase="Phase 3",
        munsell_color="10YR 3/3",
        composition="Silty clay loam",
        compaction="Loose",
        inclusions="Charcoal (frequent), ceramic (moderate), animal bone (occasional)",
        thickness_cm=68,
        top_elevation=511.42,
        bottom_elevation=510.74,
        excavated_by="J. Okonkwo",
        excavation_date=date(2024, 5, 4),
        recorded_by="E. Marchetti",
        period_id=periods["early-bronze-age"].id,
        date_from=-2900,
        date_to=-2600,
        samples_taken=["flotation FS-014", "charcoal C14-003"],
        is_public=True,
        owner_id=student.id,
    )
    session.add_all([cut, fill])
    session.flush()

    # Harris matrix edges, stored in both directions.
    session.add_all(
        [
            ContextRelationship(
                context_id=fill.id,
                related_context_id=cut.id,
                relation=StratigraphicRelation.FILLS,
                certainty="certain",
            ),
            ContextRelationship(
                context_id=cut.id,
                related_context_id=fill.id,
                relation=StratigraphicRelation.FILLED_BY,
                certainty="certain",
            ),
        ]
    )

    artifacts = [
        Artifact(
            site_id=site.id,
            context_id=fill.id,
            inventory_number="TED-2024-0001",
            field_number="SF-114",
            name="Everted-rim cooking pot",
            object_type="Cooking pot",
            category_id=categories["cooking-pot"].id,
            typology="Hama J類 variant 2",
            description=(
                "Rim and upper body sherd of a handmade cooking pot with an everted, "
                "externally thickened rim. Coarse calcite-tempered fabric, heavily sooted."
            ),
            material_id=materials["ceramic"].id,
            technique="Hand-built, coil construction",
            rim_diameter_mm=224,
            height_mm=88,
            thickness_mm=9.5,
            weight_g=212.4,
            is_fragment=True,
            period_id=periods["early-bronze-age"].id,
            date_from=-2900,
            date_to=-2600,
            dating_method="Ceramic typology",
            stratigraphic_unit="SU-1041",
            trench="A",
            square="A4",
            depth_cm=42,
            elevation=511.0,
            latitude=34.7325,
            longitude=36.7138,
            geom="SRID=4326;POINT(36.7138 34.7325)",
            find_date=date(2024, 5, 4),
            found_by="J. Okonkwo",
            recovery_method="Hand excavation",
            condition=ConditionState.GOOD,
            conservation_status=ConservationStatus.STABLE,
            current_location="Field house, Room 2, Shelf B",
            storage_box="TED-24-012",
            is_public=True,
            owner_id=student.id,
        ),
        Artifact(
            site_id=site.id,
            context_id=fill.id,
            inventory_number="TED-2024-0002",
            field_number="SF-118",
            name="Bronze awl",
            object_type="Awl",
            category_id=categories["needle"].id,
            description=(
                "Complete bronze awl of square section tapering to a point at both ends; "
                "light green patina with limited active corrosion."
            ),
            material_id=materials["bronze"].id,
            technique="Cast and hammered",
            length_mm=74.2,
            width_mm=4.1,
            thickness_mm=4.0,
            weight_g=9.6,
            period_id=periods["early-bronze-age"].id,
            date_from=-2900,
            date_to=-2600,
            stratigraphic_unit="SU-1041",
            trench="A",
            square="A4",
            depth_cm=51,
            elevation=510.91,
            find_date=date(2024, 5, 6),
            found_by="J. Okonkwo",
            recovery_method="Dry sieving, 5 mm mesh",
            condition=ConditionState.GOOD,
            conservation_status=ConservationStatus.NEEDS_TREATMENT,
            conservation_notes="Chloride testing recommended before long-term storage.",
            current_location="Conservation laboratory",
            research_notes="Parallels at Tell Hadidi and Selenkahiye in EB IV contexts.",
            is_public=True,
            owner_id=student.id,
        ),
        Artifact(
            site_id=site.id,
            context_id=cut.id,
            inventory_number="TED-2024-0003",
            field_number="SF-121",
            name="Flint blade segment",
            object_type="Blade",
            category_id=categories["blade"].id,
            description="Medial segment of a prismatic blade in fine honey-brown flint.",
            material_id=materials["flint"].id,
            length_mm=38.5,
            width_mm=14.2,
            thickness_mm=3.8,
            weight_g=2.1,
            is_fragment=True,
            period_id=periods["early-bronze-age"].id,
            stratigraphic_unit="SU-1042",
            trench="A",
            square="A4",
            find_date=date(2024, 5, 7),
            recovery_method="Flotation heavy fraction",
            condition=ConditionState.EXCELLENT,
            conservation_status=ConservationStatus.STABLE,
            current_location="Field house, Room 2, Shelf B",
            storage_box="TED-24-012",
            is_public=True,
            owner_id=student.id,
        ),
    ]
    session.add_all(artifacts)
    session.flush()

    seed_sample_media(session, project=project, site=site, artifact=artifacts[0], user=researcher)
    seed_sample_storage(session, artifacts=artifacts, user=researcher)
    seed_sample_gis(session, project=project, site=site, user=researcher)
    seed_sample_museum(session, artifacts=artifacts, user=researcher)
    seed_sample_inventory(session, user=researcher)
    seed_sample_management(session, project=project, user=researcher)
    seed_sample_social(session, project=project, artifact=artifacts[0], user=researcher)

    now = datetime.now(UTC)
    for offset, (label, action) in enumerate(
        [
            ("Tell el-Demo Regional Survey and Excavation", ActivityAction.CREATE),
            ("Tell el-Demo", ActivityAction.CREATE),
            ("TED-2024-0001", ActivityAction.CREATE),
        ]
    ):
        session.add(
            ActivityLog(
                created_at=now - timedelta(hours=offset * 3),
                action=action,
                user_id=researcher.id,
                user_label=researcher.full_name,
                resource_type=ResourceType.PROJECT,
                resource_label=label,
                summary=f"Seeded sample record: {label}",
            )
        )

    logger.info(
        "Sample data created: project %s with 1 site, 2 contexts, %d artifacts",
        project.code,
        len(artifacts),
    )
    logger.info("Demonstration accounts use the password %r", DEMO_PASSWORD)


# --------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--with-samples",
        action="store_true",
        default=os.getenv("SEED_SAMPLE_DATA", "").lower() in {"1", "true", "yes"},
        help="Also create the demonstration project (default from SEED_SAMPLE_DATA)",
    )
    args = parser.parse_args(argv)

    session: Session = SessionLocal()
    try:
        admin = seed_admin(session)
        seed_vocabularies(session)
        seed_settings(session)
        if args.with_samples:
            if settings.ENVIRONMENT == "production":
                logger.warning("Refusing to create sample data in a production environment")
            else:
                seed_samples(session, admin)
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("Seeding failed; no changes were committed")
        return 1
    finally:
        session.close()

    logger.info("Seeding complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
