"""Museum collections: accessioned objects, their history and their uses.

The distinction from the archaeology module is deliberate. An **artifact** is a
find as excavated — a record of what came out of the ground, in a context, in a
trench. A **museum object** is that thing once an institution has taken formal
responsibility for it: accessioned, numbered, valued, insured, conserved,
displayed and possibly deaccessioned decades later.

Most objects are both, and the two are linked. But they are separate records
because they answer to different people and different rules: the excavation
record is fixed by what happened in the field and should never change, while
the museum record accumulates a lifetime of custody afterwards. Folding them
into one table would mean either the field record drifts or the custody record
cannot be written.

An object *not* from an excavation — a donation, a purchase, a seizure — has no
artifact to link to, and that is the normal case for most of a collection.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, OwnedRecordMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    AcquisitionMethod,
    ConditionState,
    ConservationStatus,
    ExhibitionStatus,
    LoanDirection,
    LoanStatus,
    ObjectStatus,
    ReviewStatus,
    TreatmentType,
)

if TYPE_CHECKING:
    from app.models.artifact import Artifact
    from app.models.storage import StorageLocation


class Collection(UUIDPrimaryKeyMixin, TimestampMixin, OwnedRecordMixin, Base):
    """A named collection, and the numbering scheme its objects follow.

    Institutions have their own accession number formats and are rightly
    attached to them — the number is printed on the object, written in ledgers
    and cited in publications going back a century. The platform therefore does
    not impose one: each collection declares its own pattern, and the platform
    validates against it and can continue the sequence.
    """

    __tablename__ = "collections"

    name: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text)

    # --- Accession numbering ---------------------------------------------
    #: Template for this collection's numbers, using ``{}`` placeholders:
    #: ``{prefix}.{year}.{seq:04d}`` produces ``NM.2024.0001``. See
    #: ``app/services/accession.py`` for the supported placeholders.
    accession_pattern: Mapped[str | None] = mapped_column(String(120))
    accession_prefix: Mapped[str | None] = mapped_column(String(40))
    #: Highest sequence issued so far, so the next can be offered. Advisory:
    #: a curator may always type a number by hand.
    accession_sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    #: Whether a number that does not match the pattern is refused. Off by
    #: default, because every collection contains inherited oddities and a
    #: platform that refuses to record them is a platform nobody migrates to.
    enforce_pattern: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    institution: Mapped[str | None] = mapped_column(String(300))
    department: Mapped[str | None] = mapped_column(String(200))
    curator_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)

    objects: Mapped[list[MuseumObject]] = relationship(back_populates="collection")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Collection {self.code}>"


class MuseumObject(UUIDPrimaryKeyMixin, TimestampMixin, OwnedRecordMixin, Base):
    """One accessioned object.

    The field set is deliberately close to what a museum cataloguer expects to
    fill in, because the people using this have catalogued objects before and
    a form that omits half of what they need is a form they work around in a
    spreadsheet.
    """

    __tablename__ = "museum_objects"

    # --- Numbers ---------------------------------------------------------
    accession_number: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    #: A second number the object also answers to — an old ledger number, a
    #: donor's number, a previous institution's. Collections are full of them.
    former_number: Mapped[str | None] = mapped_column(String(120), index=True)
    #: Set when the number does not match the collection's pattern, so the
    #: oddity is recorded as known rather than looking like a typing error.
    number_is_legacy: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: For objects catalogued as a group: 3 of 12 sherds from one vessel.
    part_number: Mapped[str | None] = mapped_column(String(40))
    object_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    collection_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("collections.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # --- Identification --------------------------------------------------
    title: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    object_type: Mapped[str | None] = mapped_column(String(200), index=True)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("object_categories.id", ondelete="SET NULL"), index=True
    )
    period_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("periods.id", ondelete="SET NULL"), index=True
    )
    culture: Mapped[str | None] = mapped_column(String(200), index=True)
    #: Signed years: negative is BCE, matching the archaeology module.
    date_from: Mapped[int | None] = mapped_column(Integer, index=True)
    date_to: Mapped[int | None] = mapped_column(Integer, index=True)
    date_note: Mapped[str | None] = mapped_column(String(300))

    materials: Mapped[list[str] | None] = mapped_column(ARRAY(String(120)))
    techniques: Mapped[list[str] | None] = mapped_column(ARRAY(String(120)))
    maker: Mapped[str | None] = mapped_column(String(300))
    inscription: Mapped[str | None] = mapped_column(Text)
    marks: Mapped[str | None] = mapped_column(Text)

    # --- Measurement -----------------------------------------------------
    height_mm: Mapped[float | None] = mapped_column(Numeric(10, 2))
    width_mm: Mapped[float | None] = mapped_column(Numeric(10, 2))
    depth_mm: Mapped[float | None] = mapped_column(Numeric(10, 2))
    diameter_mm: Mapped[float | None] = mapped_column(Numeric(10, 2))
    thickness_mm: Mapped[float | None] = mapped_column(Numeric(10, 2))
    weight_g: Mapped[float | None] = mapped_column(Numeric(12, 3))
    dimension_note: Mapped[str | None] = mapped_column(String(300))

    # --- Condition and care ----------------------------------------------
    condition: Mapped[ConditionState] = mapped_column(
        Enum(
            ConditionState, name="condition_state", values_callable=lambda e: [m.value for m in e]
        ),
        default=ConditionState.UNKNOWN,
        nullable=False,
        index=True,
    )
    conservation_status: Mapped[ConservationStatus] = mapped_column(
        Enum(
            ConservationStatus,
            name="conservation_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=ConservationStatus.UNKNOWN,
        nullable=False,
        index=True,
    )
    condition_note: Mapped[str | None] = mapped_column(Text)
    #: When somebody last physically looked at it. The question an auditor and
    #: a conservator both ask first.
    last_checked_on: Mapped[date | None] = mapped_column(Date)
    last_checked_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    # --- Acquisition -----------------------------------------------------
    acquisition_method: Mapped[AcquisitionMethod] = mapped_column(
        Enum(
            AcquisitionMethod,
            name="acquisition_method",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=AcquisitionMethod.UNKNOWN,
        nullable=False,
        index=True,
    )
    acquisition_date: Mapped[date | None] = mapped_column(Date, index=True)
    acquisition_source: Mapped[str | None] = mapped_column(String(300))
    acquisition_note: Mapped[str | None] = mapped_column(Text)
    #: Everything known about where it was before the institution had it. The
    #: single most consequential field on the record.
    provenance: Mapped[str | None] = mapped_column(Text)
    credit_line: Mapped[str | None] = mapped_column(String(300))
    #: Kept separate from the public record and readable only by those who can
    #: edit the object, because a valuation is a theft incentive.
    valuation_amount: Mapped[float | None] = mapped_column(Numeric(14, 2))
    valuation_currency: Mapped[str | None] = mapped_column(String(3))
    valuation_date: Mapped[date | None] = mapped_column(Date)
    insurance_reference: Mapped[str | None] = mapped_column(String(120))

    # --- Status and location ---------------------------------------------
    status: Mapped[ObjectStatus] = mapped_column(
        Enum(ObjectStatus, name="object_status", values_callable=lambda e: [m.value for m in e]),
        default=ObjectStatus.ACCESSIONED,
        nullable=False,
        index=True,
    )
    storage_location_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("storage_locations.id", ondelete="SET NULL"), index=True
    )
    #: Where it is meant to live when not on display or in the lab, so a
    #: returned object has somewhere to go back to.
    home_location_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("storage_locations.id", ondelete="SET NULL")
    )
    deaccession_date: Mapped[date | None] = mapped_column(Date)
    deaccession_reason: Mapped[str | None] = mapped_column(Text)

    # --- The link back to the excavation ---------------------------------
    #: Set when this object came out of a recorded excavation. Null for most
    #: of a typical collection — donations, purchases and old holdings have no
    #: excavation record to point at.
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("artifacts.id", ondelete="SET NULL"),
        index=True,
        unique=True,
    )

    # --- Publication and rights ------------------------------------------
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    rights_statement: Mapped[str | None] = mapped_column(String(300))
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(String(80)))
    #: Every institution has fields nobody else wants.
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)

    review_status: Mapped[ReviewStatus] = mapped_column(
        Enum(ReviewStatus, name="review_status", values_callable=lambda e: [m.value for m in e]),
        default=ReviewStatus.APPROVED,
        nullable=False,
        index=True,
    )
    #: Stable token for a printed label, matching artifacts, sites and shelves.
    public_token: Mapped[str] = mapped_column(
        String(32), nullable=False, unique=True, index=True, default=lambda: uuid.uuid4().hex
    )

    collection: Mapped[Collection] = relationship(back_populates="objects")
    artifact: Mapped[Artifact | None] = relationship()
    storage_location: Mapped[StorageLocation | None] = relationship(
        foreign_keys=[storage_location_id]
    )
    home_location: Mapped[StorageLocation | None] = relationship(foreign_keys=[home_location_id])
    treatments: Mapped[list[ConservationRecord]] = relationship(
        back_populates="museum_object", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # Accession numbers repeat across collections — two museums both have a
        # "1974.1" — but never within one.
        UniqueConstraint("collection_id", "accession_number", name="uq_museum_objects_accession"),
        CheckConstraint("object_count >= 1", name="ck_museum_objects_count"),
        CheckConstraint(
            "date_from IS NULL OR date_to IS NULL OR date_from <= date_to",
            name="ck_museum_objects_date_range",
        ),
        Index("ix_museum_objects_collection_status", "collection_id", "status"),
        Index("ix_museum_objects_title_lower", "title"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<MuseumObject {self.accession_number}>"


class ConservationRecord(UUIDPrimaryKeyMixin, TimestampMixin, OwnedRecordMixin, Base):
    """One examination or treatment, appended to an object's care history.

    Append-only in practice: a treatment that happened cannot un-happen, and
    the record of what was done — with what materials, by whom — is what a
    future conservator needs before touching the object again.
    """

    __tablename__ = "conservation_records"

    museum_object_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("museum_objects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    treatment_type: Mapped[TreatmentType] = mapped_column(
        Enum(TreatmentType, name="treatment_type", values_callable=lambda e: [m.value for m in e]),
        default=TreatmentType.EXAMINATION,
        nullable=False,
        index=True,
    )
    performed_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    conservator: Mapped[str | None] = mapped_column(String(200))
    conservator_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    condition_before: Mapped[ConditionState | None] = mapped_column(
        Enum(ConditionState, name="condition_state", values_callable=lambda e: [m.value for m in e])
    )
    condition_after: Mapped[ConditionState | None] = mapped_column(
        Enum(ConditionState, name="condition_state", values_callable=lambda e: [m.value for m in e])
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    #: What was physically applied. A future conservator must know before
    #: choosing a solvent, and "we cleaned it" does not answer that.
    materials_used: Mapped[str | None] = mapped_column(Text)
    recommendations: Mapped[str | None] = mapped_column(Text)
    #: When the object should next be looked at.
    next_review_on: Mapped[date | None] = mapped_column(Date, index=True)
    hours_spent: Mapped[float | None] = mapped_column(Numeric(8, 2))
    cost_amount: Mapped[float | None] = mapped_column(Numeric(12, 2))
    cost_currency: Mapped[str | None] = mapped_column(String(3))
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)

    museum_object: Mapped[MuseumObject] = relationship(back_populates="treatments")

    __table_args__ = (
        Index("ix_conservation_records_object_date", "museum_object_id", "performed_on"),
    )


class Exhibition(UUIDPrimaryKeyMixin, TimestampMixin, OwnedRecordMixin, Base):
    """A display, permanent or temporary, in-house or travelling."""

    __tablename__ = "exhibitions"

    title: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    subtitle: Mapped[str | None] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ExhibitionStatus] = mapped_column(
        Enum(
            ExhibitionStatus,
            name="exhibition_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=ExhibitionStatus.PLANNED,
        nullable=False,
        index=True,
    )
    venue: Mapped[str | None] = mapped_column(String(300))
    #: Where in the building, when it is in this one.
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("storage_locations.id", ondelete="SET NULL")
    )
    opens_on: Mapped[date | None] = mapped_column(Date, index=True)
    closes_on: Mapped[date | None] = mapped_column(Date, index=True)
    curator: Mapped[str | None] = mapped_column(String(200))
    curator_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    is_permanent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    catalogue_reference: Mapped[str | None] = mapped_column(String(300))
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)

    items: Mapped[list[ExhibitionItem]] = relationship(
        back_populates="exhibition", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "opens_on IS NULL OR closes_on IS NULL OR opens_on <= closes_on",
            name="ck_exhibitions_date_range",
        ),
    )


class ExhibitionItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One object in one exhibition, with what the label said."""

    __tablename__ = "exhibition_items"

    exhibition_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("exhibitions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    museum_object_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("museum_objects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: The wall label, which is written per exhibition rather than per object:
    #: the same pot is described differently in a show about trade than in one
    #: about cooking.
    label_text: Mapped[str | None] = mapped_column(Text)
    case_number: Mapped[str | None] = mapped_column(String(60))
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    exhibition: Mapped[Exhibition] = relationship(back_populates="items")
    museum_object: Mapped[MuseumObject] = relationship()

    __table_args__ = (
        UniqueConstraint("exhibition_id", "museum_object_id", name="uq_exhibition_items"),
    )


class Loan(UUIDPrimaryKeyMixin, TimestampMixin, OwnedRecordMixin, Base):
    """An object leaving the building, or arriving from elsewhere.

    Present although the institution does not currently lend. Loan paperwork is
    the kind of thing that becomes urgent with three weeks' notice, and adding
    the table later would mean a migration in the middle of that. It costs
    nothing to carry unused.
    """

    __tablename__ = "loans"

    reference: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    direction: Mapped[LoanDirection] = mapped_column(
        Enum(LoanDirection, name="loan_direction", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        index=True,
    )
    status: Mapped[LoanStatus] = mapped_column(
        Enum(LoanStatus, name="loan_status", values_callable=lambda e: [m.value for m in e]),
        default=LoanStatus.REQUESTED,
        nullable=False,
        index=True,
    )

    #: The other institution — borrower for an outgoing loan, lender for an
    #: incoming one.
    counterparty: Mapped[str] = mapped_column(String(300), nullable=False)
    contact_name: Mapped[str | None] = mapped_column(String(200))
    contact_email: Mapped[str | None] = mapped_column(String(320))
    purpose: Mapped[str | None] = mapped_column(Text)
    exhibition_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("exhibitions.id", ondelete="SET NULL")
    )

    requested_on: Mapped[date | None] = mapped_column(Date)
    starts_on: Mapped[date | None] = mapped_column(Date, index=True)
    ends_on: Mapped[date | None] = mapped_column(Date, index=True)
    returned_on: Mapped[date | None] = mapped_column(Date)

    insurance_value: Mapped[float | None] = mapped_column(Numeric(14, 2))
    insurance_currency: Mapped[str | None] = mapped_column(String(3))
    conditions: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)

    items: Mapped[list[LoanItem]] = relationship(
        back_populates="loan", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "starts_on IS NULL OR ends_on IS NULL OR starts_on <= ends_on",
            name="ck_loans_date_range",
        ),
    )


class LoanItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One object on one loan, with its condition at each end."""

    __tablename__ = "loan_items"

    loan_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("loans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    museum_object_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("museum_objects.id", ondelete="CASCADE"), index=True
    )
    #: For an incoming loan the object is not ours and has no accession number
    #: here, so it is described in words instead.
    external_description: Mapped[str | None] = mapped_column(Text)

    #: The whole point of loan paperwork: proving what state it left in and
    #: what state it came back in.
    condition_out: Mapped[ConditionState | None] = mapped_column(
        Enum(ConditionState, name="condition_state", values_callable=lambda e: [m.value for m in e])
    )
    condition_in: Mapped[ConditionState | None] = mapped_column(
        Enum(ConditionState, name="condition_state", values_callable=lambda e: [m.value for m in e])
    )
    condition_note: Mapped[str | None] = mapped_column(Text)
    insurance_value: Mapped[float | None] = mapped_column(Numeric(14, 2))

    loan: Mapped[Loan] = relationship(back_populates="items")
    museum_object: Mapped[MuseumObject | None] = relationship()

    __table_args__ = (
        CheckConstraint(
            "museum_object_id IS NOT NULL OR external_description IS NOT NULL",
            name="ck_loan_items_identifies_something",
        ),
        UniqueConstraint("loan_id", "museum_object_id", name="uq_loan_items"),
    )


class EnvironmentalReading(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One measurement of conditions in one place, at one moment.

    Storage locations carry *target* conditions; this is what was actually
    measured. Both are needed: a target with no readings cannot be shown to
    have been met, and readings with no target cannot be judged.

    Readings are rows rather than an aggregate because the question a
    conservator asks is about drift and excursions — "did it go above 60% while
    the building was closed" — which a monthly average hides.
    """

    __tablename__ = "environmental_readings"

    location_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("storage_locations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    temperature_c: Mapped[float | None] = mapped_column(Numeric(5, 2))
    relative_humidity: Mapped[float | None] = mapped_column(Numeric(5, 2))
    #: Lux, for light-sensitive material on display.
    illuminance_lux: Mapped[float | None] = mapped_column(Numeric(8, 1))
    uv_microwatt_lumen: Mapped[float | None] = mapped_column(Numeric(8, 1))

    #: Which datalogger or person produced this, so a drifting sensor can be
    #: identified and its readings discounted.
    source: Mapped[str | None] = mapped_column(String(120), index=True)
    recorded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    note: Mapped[str | None] = mapped_column(Text)

    location: Mapped[StorageLocation] = relationship()

    __table_args__ = (
        CheckConstraint(
            "temperature_c IS NOT NULL OR relative_humidity IS NOT NULL "
            "OR illuminance_lux IS NOT NULL OR uv_microwatt_lumen IS NOT NULL",
            name="ck_environmental_readings_has_a_value",
        ),
        Index("ix_environmental_readings_location_time", "location_id", "recorded_at"),
    )
