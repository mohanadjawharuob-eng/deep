"""Populate a fresh database.

Run as ``python -m scripts.seed`` (the container entrypoint does this after
migrations). The script is **idempotent**: it looks each record up before
inserting, so it is safe on every boot.

Two layers are created:

*Reference data* — the first administrator, the controlled vocabularies and
the default system settings. Always created.

*Sample data* — a demonstration project with sites, contexts and artifacts, so
a new deployment has something to look at. Skipped unless ``--with-samples``
is passed or ``SEED_SAMPLE_DATA=true`` is set.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import (
    ActivityAction,
    ActivityLog,
    Artifact,
    ConditionState,
    ConservationStatus,
    ContextRelationship,
    ContextType,
    ExcavationContext,
    Material,
    ObjectCategory,
    Period,
    Project,
    ProjectMembership,
    ProjectRole,
    ProjectStatus,
    ProtectionStatus,
    ResourceType,
    Site,
    SiteType,
    StratigraphicRelation,
    SystemSetting,
    User,
    UserRole,
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


def seed_samples(session: Session, admin: User) -> None:
    """Create a small but complete demonstration project."""
    if session.scalar(select(Project).where(Project.code == "DEMO-2024")) is not None:
        logger.info("Sample project already present; skipping")
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
