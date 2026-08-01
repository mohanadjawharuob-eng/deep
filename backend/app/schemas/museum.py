"""Schemas for collections, objects, conservation, exhibitions and loans."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

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
from app.schemas.common import ORMModel


# --------------------------------------------------------------------------
# Collections
# --------------------------------------------------------------------------
class CollectionBase(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    description: str | None = None
    accession_pattern: str | None = Field(
        default=None,
        max_length=120,
        description=(
            "Template for this collection's numbers. Placeholders: {prefix}, "
            "{code}, {year}, {yy}, {seq} — and {seq} may be padded as "
            "{seq:04d}. Leave blank to accept any number."
        ),
        examples=["{prefix}.{year}.{seq:04d}"],
    )
    accession_prefix: str | None = Field(default=None, max_length=40)
    enforce_pattern: bool = Field(
        default=False,
        description=(
            "Refuse numbers that do not match the pattern. Off by default: "
            "every collection holds inherited oddities, and refusing to record "
            "them is how a migration stalls."
        ),
    )
    institution: str | None = Field(default=None, max_length=300)
    department: str | None = Field(default=None, max_length=200)
    curator_id: uuid.UUID | None = None
    metadata_json: dict[str, Any] | None = None
    is_public: bool = False


class CollectionCreate(CollectionBase):
    code: str = Field(min_length=1, max_length=40, examples=["ARCH"])


class CollectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    accession_pattern: str | None = Field(default=None, max_length=120)
    accession_prefix: str | None = Field(default=None, max_length=40)
    enforce_pattern: bool | None = None
    institution: str | None = Field(default=None, max_length=300)
    department: str | None = Field(default=None, max_length=200)
    curator_id: uuid.UUID | None = None
    metadata_json: dict[str, Any] | None = None
    is_public: bool | None = None


class CollectionRead(ORMModel):
    id: uuid.UUID
    name: str
    code: str
    description: str | None = None
    accession_pattern: str | None = None
    accession_prefix: str | None = None
    accession_sequence: int
    enforce_pattern: bool
    institution: str | None = None
    department: str | None = None
    curator_id: uuid.UUID | None = None
    is_public: bool
    owner_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class CollectionDetail(CollectionRead):
    object_count: int = 0
    #: What the next number would look like, so a cataloguer can see the
    #: scheme working before committing to it.
    next_accession_number: str | None = None
    can_edit: bool = False
    can_delete: bool = False


# --------------------------------------------------------------------------
# Objects
# --------------------------------------------------------------------------
class MuseumObjectBase(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str | None = None
    object_type: str | None = Field(default=None, max_length=200)
    category_id: uuid.UUID | None = None
    period_id: uuid.UUID | None = None
    culture: str | None = Field(default=None, max_length=200)
    date_from: int | None = Field(default=None, description="Signed year; negative is BCE")
    date_to: int | None = None
    date_note: str | None = Field(default=None, max_length=300)

    materials: list[str] | None = None
    techniques: list[str] | None = None
    maker: str | None = Field(default=None, max_length=300)
    inscription: str | None = None
    marks: str | None = None

    height_mm: float | None = Field(default=None, ge=0)
    width_mm: float | None = Field(default=None, ge=0)
    depth_mm: float | None = Field(default=None, ge=0)
    diameter_mm: float | None = Field(default=None, ge=0)
    thickness_mm: float | None = Field(default=None, ge=0)
    weight_g: float | None = Field(default=None, ge=0)
    dimension_note: str | None = Field(default=None, max_length=300)

    condition: ConditionState = ConditionState.UNKNOWN
    conservation_status: ConservationStatus = ConservationStatus.UNKNOWN
    condition_note: str | None = None
    last_checked_on: date | None = None

    acquisition_method: AcquisitionMethod = AcquisitionMethod.UNKNOWN
    acquisition_date: date | None = None
    acquisition_source: str | None = Field(default=None, max_length=300)
    acquisition_note: str | None = None
    provenance: str | None = None
    credit_line: str | None = Field(default=None, max_length=300)
    valuation_amount: float | None = Field(default=None, ge=0)
    valuation_currency: str | None = Field(default=None, min_length=3, max_length=3)
    valuation_date: date | None = None
    insurance_reference: str | None = Field(default=None, max_length=120)

    status: ObjectStatus = ObjectStatus.ACCESSIONED
    storage_location_id: uuid.UUID | None = None
    home_location_id: uuid.UUID | None = None
    deaccession_date: date | None = None
    deaccession_reason: str | None = None

    artifact_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "The excavation record this object came from, when it came from "
            "one. Most of a collection has none."
        ),
    )

    former_number: str | None = Field(default=None, max_length=120)
    part_number: str | None = Field(default=None, max_length=40)
    object_count: int = Field(default=1, ge=1)

    is_published: bool = False
    rights_statement: str | None = Field(default=None, max_length=300)
    tags: list[str] | None = None
    metadata_json: dict[str, Any] | None = None
    is_public: bool = False

    @model_validator(mode="after")
    def _date_range(self) -> MuseumObjectBase:
        both = self.date_from is not None and self.date_to is not None
        if both and self.date_from > self.date_to:
            raise ValueError("date_from cannot be later than date_to")
        return self


class MuseumObjectCreate(MuseumObjectBase):
    collection_id: uuid.UUID
    accession_number: str | None = Field(
        default=None,
        max_length=120,
        description=(
            "Leave blank to take the next number in the collection's sequence. "
            "A number that does not match the collection's pattern is still "
            "recorded, flagged as legacy, unless the collection enforces it."
        ),
    )


class MuseumObjectUpdate(BaseModel):
    """Everything on the object may be corrected except its identity.

    ``accession_number`` and ``collection_id`` are absent deliberately: moving
    an object between collections or renumbering it are separate, audited
    operations, not a field edit.
    """

    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    object_type: str | None = Field(default=None, max_length=200)
    category_id: uuid.UUID | None = None
    period_id: uuid.UUID | None = None
    culture: str | None = Field(default=None, max_length=200)
    date_from: int | None = None
    date_to: int | None = None
    date_note: str | None = Field(default=None, max_length=300)
    materials: list[str] | None = None
    techniques: list[str] | None = None
    maker: str | None = Field(default=None, max_length=300)
    inscription: str | None = None
    marks: str | None = None
    height_mm: float | None = Field(default=None, ge=0)
    width_mm: float | None = Field(default=None, ge=0)
    depth_mm: float | None = Field(default=None, ge=0)
    diameter_mm: float | None = Field(default=None, ge=0)
    thickness_mm: float | None = Field(default=None, ge=0)
    weight_g: float | None = Field(default=None, ge=0)
    dimension_note: str | None = Field(default=None, max_length=300)
    condition: ConditionState | None = None
    conservation_status: ConservationStatus | None = None
    condition_note: str | None = None
    last_checked_on: date | None = None
    acquisition_method: AcquisitionMethod | None = None
    acquisition_date: date | None = None
    acquisition_source: str | None = Field(default=None, max_length=300)
    acquisition_note: str | None = None
    provenance: str | None = None
    credit_line: str | None = Field(default=None, max_length=300)
    valuation_amount: float | None = Field(default=None, ge=0)
    valuation_currency: str | None = Field(default=None, min_length=3, max_length=3)
    valuation_date: date | None = None
    insurance_reference: str | None = Field(default=None, max_length=120)
    status: ObjectStatus | None = None
    home_location_id: uuid.UUID | None = None
    deaccession_date: date | None = None
    deaccession_reason: str | None = None
    artifact_id: uuid.UUID | None = None
    former_number: str | None = Field(default=None, max_length=120)
    part_number: str | None = Field(default=None, max_length=40)
    object_count: int | None = Field(default=None, ge=1)
    is_published: bool | None = None
    rights_statement: str | None = Field(default=None, max_length=300)
    tags: list[str] | None = None
    metadata_json: dict[str, Any] | None = None
    is_public: bool | None = None


class MuseumObjectSummary(ORMModel):
    id: uuid.UUID
    accession_number: str
    former_number: str | None = None
    number_is_legacy: bool
    title: str
    object_type: str | None = None
    collection_id: uuid.UUID
    period_id: uuid.UUID | None = None
    condition: ConditionState
    status: ObjectStatus
    storage_location_id: uuid.UUID | None = None
    artifact_id: uuid.UUID | None = None
    is_public: bool
    review_status: ReviewStatus
    created_at: datetime


class MuseumObjectRead(MuseumObjectSummary):
    description: str | None = None
    category_id: uuid.UUID | None = None
    culture: str | None = None
    date_from: int | None = None
    date_to: int | None = None
    date_note: str | None = None
    materials: list[str] | None = None
    techniques: list[str] | None = None
    maker: str | None = None
    inscription: str | None = None
    marks: str | None = None
    height_mm: float | None = None
    width_mm: float | None = None
    depth_mm: float | None = None
    diameter_mm: float | None = None
    thickness_mm: float | None = None
    weight_g: float | None = None
    dimension_note: str | None = None
    conservation_status: ConservationStatus
    condition_note: str | None = None
    last_checked_on: date | None = None
    acquisition_method: AcquisitionMethod
    acquisition_date: date | None = None
    acquisition_source: str | None = None
    acquisition_note: str | None = None
    provenance: str | None = None
    credit_line: str | None = None
    home_location_id: uuid.UUID | None = None
    deaccession_date: date | None = None
    deaccession_reason: str | None = None
    part_number: str | None = None
    object_count: int
    is_published: bool
    rights_statement: str | None = None
    tags: list[str] | None = None
    metadata_json: dict[str, Any] | None = None
    public_token: str
    owner_id: uuid.UUID | None = None
    updated_at: datetime


class MuseumObjectDetail(MuseumObjectRead):
    #: Present only for a caller who may edit the object. A valuation on a
    #: public record is an invitation.
    valuation_amount: float | None = None
    valuation_currency: str | None = None
    valuation_date: date | None = None
    insurance_reference: str | None = None

    #: Resolved for display, so a card does not need four extra requests.
    collection_name: str | None = None
    storage_path: str | None = None
    treatment_count: int = 0
    #: Set when the accession number did not match the collection's pattern.
    accession_warning: str | None = None

    can_edit: bool = False
    can_delete: bool = False


class AccessionPreview(BaseModel):
    """What a number would be, and whether one typed by hand is acceptable."""

    collection_id: uuid.UUID
    next_accession_number: str
    pattern: str | None = None
    #: Set when a candidate was supplied.
    candidate: str | None = None
    candidate_matches_pattern: bool | None = None
    candidate_is_available: bool | None = None
    message: str | None = None


# --------------------------------------------------------------------------
# Conservation
# --------------------------------------------------------------------------
class ConservationCreate(BaseModel):
    treatment_type: TreatmentType = TreatmentType.EXAMINATION
    performed_on: date
    conservator: str | None = Field(default=None, max_length=200)
    conservator_id: uuid.UUID | None = None
    condition_before: ConditionState | None = None
    condition_after: ConditionState | None = None
    description: str = Field(min_length=1)
    materials_used: str | None = Field(
        default=None,
        description=(
            "What was physically applied. A future conservator must know "
            "before choosing a solvent."
        ),
    )
    recommendations: str | None = None
    next_review_on: date | None = None
    hours_spent: float | None = Field(default=None, ge=0)
    cost_amount: float | None = Field(default=None, ge=0)
    cost_currency: str | None = Field(default=None, min_length=3, max_length=3)
    metadata_json: dict[str, Any] | None = None
    #: Apply ``condition_after`` to the object itself, which is almost always
    #: what is meant after a treatment.
    update_object_condition: bool = True


class ConservationUpdate(BaseModel):
    treatment_type: TreatmentType | None = None
    performed_on: date | None = None
    conservator: str | None = Field(default=None, max_length=200)
    condition_before: ConditionState | None = None
    condition_after: ConditionState | None = None
    description: str | None = Field(default=None, min_length=1)
    materials_used: str | None = None
    recommendations: str | None = None
    next_review_on: date | None = None
    hours_spent: float | None = Field(default=None, ge=0)
    cost_amount: float | None = Field(default=None, ge=0)
    cost_currency: str | None = Field(default=None, min_length=3, max_length=3)
    metadata_json: dict[str, Any] | None = None


class ConservationRead(ORMModel):
    id: uuid.UUID
    museum_object_id: uuid.UUID
    treatment_type: TreatmentType
    performed_on: date
    conservator: str | None = None
    conservator_id: uuid.UUID | None = None
    condition_before: ConditionState | None = None
    condition_after: ConditionState | None = None
    description: str
    materials_used: str | None = None
    recommendations: str | None = None
    next_review_on: date | None = None
    hours_spent: float | None = None
    cost_amount: float | None = None
    cost_currency: str | None = None
    metadata_json: dict[str, Any] | None = None
    owner_id: uuid.UUID | None = None
    created_at: datetime


# --------------------------------------------------------------------------
# Exhibitions
# --------------------------------------------------------------------------
class ExhibitionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    subtitle: str | None = Field(default=None, max_length=300)
    description: str | None = None
    status: ExhibitionStatus = ExhibitionStatus.PLANNED
    venue: str | None = Field(default=None, max_length=300)
    location_id: uuid.UUID | None = None
    opens_on: date | None = None
    closes_on: date | None = None
    curator: str | None = Field(default=None, max_length=200)
    curator_id: uuid.UUID | None = None
    is_permanent: bool = False
    catalogue_reference: str | None = Field(default=None, max_length=300)
    metadata_json: dict[str, Any] | None = None
    is_public: bool = False

    @model_validator(mode="after")
    def _date_range(self) -> ExhibitionCreate:
        both = self.opens_on is not None and self.closes_on is not None
        if both and self.opens_on > self.closes_on:
            raise ValueError("opens_on cannot be later than closes_on")
        return self


class ExhibitionUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    subtitle: str | None = Field(default=None, max_length=300)
    description: str | None = None
    status: ExhibitionStatus | None = None
    venue: str | None = Field(default=None, max_length=300)
    location_id: uuid.UUID | None = None
    opens_on: date | None = None
    closes_on: date | None = None
    curator: str | None = Field(default=None, max_length=200)
    curator_id: uuid.UUID | None = None
    is_permanent: bool | None = None
    catalogue_reference: str | None = Field(default=None, max_length=300)
    metadata_json: dict[str, Any] | None = None
    is_public: bool | None = None


class ExhibitionRead(ORMModel):
    id: uuid.UUID
    title: str
    subtitle: str | None = None
    description: str | None = None
    status: ExhibitionStatus
    venue: str | None = None
    location_id: uuid.UUID | None = None
    opens_on: date | None = None
    closes_on: date | None = None
    curator: str | None = None
    is_permanent: bool
    catalogue_reference: str | None = None
    item_count: int = 0
    is_public: bool
    owner_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class ExhibitionItemCreate(BaseModel):
    museum_object_id: uuid.UUID
    label_text: str | None = Field(
        default=None,
        description=(
            "The wall label, written per exhibition: the same pot is described "
            "differently in a show about trade than in one about cooking."
        ),
    )
    case_number: str | None = Field(default=None, max_length=60)
    display_order: int = 0
    notes: str | None = None


class ExhibitionItemRead(ORMModel):
    id: uuid.UUID
    exhibition_id: uuid.UUID
    museum_object_id: uuid.UUID
    accession_number: str | None = None
    object_title: str | None = None
    label_text: str | None = None
    case_number: str | None = None
    display_order: int
    notes: str | None = None


# --------------------------------------------------------------------------
# Loans
# --------------------------------------------------------------------------
class LoanCreate(BaseModel):
    reference: str = Field(min_length=1, max_length=80)
    direction: LoanDirection
    status: LoanStatus = LoanStatus.REQUESTED
    counterparty: str = Field(min_length=1, max_length=300)
    contact_name: str | None = Field(default=None, max_length=200)
    contact_email: str | None = Field(default=None, max_length=320)
    purpose: str | None = None
    exhibition_id: uuid.UUID | None = None
    requested_on: date | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    insurance_value: float | None = Field(default=None, ge=0)
    insurance_currency: str | None = Field(default=None, min_length=3, max_length=3)
    conditions: str | None = None
    notes: str | None = None
    metadata_json: dict[str, Any] | None = None
    is_public: bool = False

    @model_validator(mode="after")
    def _date_range(self) -> LoanCreate:
        both = self.starts_on is not None and self.ends_on is not None
        if both and self.starts_on > self.ends_on:
            raise ValueError("starts_on cannot be later than ends_on")
        return self


class LoanUpdate(BaseModel):
    status: LoanStatus | None = None
    counterparty: str | None = Field(default=None, min_length=1, max_length=300)
    contact_name: str | None = Field(default=None, max_length=200)
    contact_email: str | None = Field(default=None, max_length=320)
    purpose: str | None = None
    exhibition_id: uuid.UUID | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    returned_on: date | None = None
    insurance_value: float | None = Field(default=None, ge=0)
    insurance_currency: str | None = Field(default=None, min_length=3, max_length=3)
    conditions: str | None = None
    notes: str | None = None
    metadata_json: dict[str, Any] | None = None
    is_public: bool | None = None


class LoanRead(ORMModel):
    id: uuid.UUID
    reference: str
    direction: LoanDirection
    status: LoanStatus
    counterparty: str
    contact_name: str | None = None
    contact_email: str | None = None
    purpose: str | None = None
    exhibition_id: uuid.UUID | None = None
    requested_on: date | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    returned_on: date | None = None
    insurance_value: float | None = None
    insurance_currency: str | None = None
    conditions: str | None = None
    notes: str | None = None
    item_count: int = 0
    is_public: bool
    created_at: datetime
    updated_at: datetime


class LoanItemCreate(BaseModel):
    museum_object_id: uuid.UUID | None = None
    external_description: str | None = Field(
        default=None,
        description="For an incoming loan, where the object is not ours to number.",
    )
    condition_out: ConditionState | None = None
    condition_in: ConditionState | None = None
    condition_note: str | None = None
    insurance_value: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _identifies_something(self) -> LoanItemCreate:
        if self.museum_object_id is None and not self.external_description:
            raise ValueError(
                "A loan item needs either one of our objects or a description " "of somebody else's"
            )
        return self


class LoanItemRead(ORMModel):
    id: uuid.UUID
    loan_id: uuid.UUID
    museum_object_id: uuid.UUID | None = None
    accession_number: str | None = None
    object_title: str | None = None
    external_description: str | None = None
    condition_out: ConditionState | None = None
    condition_in: ConditionState | None = None
    condition_note: str | None = None
    insurance_value: float | None = None


# --------------------------------------------------------------------------
# Environmental readings
# --------------------------------------------------------------------------
class ReadingCreate(BaseModel):
    location_id: uuid.UUID
    recorded_at: datetime | None = Field(
        default=None, description="Defaults to now. Backdating a logger download is normal."
    )
    temperature_c: float | None = Field(default=None, ge=-50, le=80)
    relative_humidity: float | None = Field(default=None, ge=0, le=100)
    illuminance_lux: float | None = Field(default=None, ge=0)
    uv_microwatt_lumen: float | None = Field(default=None, ge=0)
    source: str | None = Field(
        default=None,
        max_length=120,
        description="Which logger or person produced this, so a drifting sensor can be found.",
    )
    note: str | None = None

    @model_validator(mode="after")
    def _has_a_value(self) -> ReadingCreate:
        measured = (
            self.temperature_c,
            self.relative_humidity,
            self.illuminance_lux,
            self.uv_microwatt_lumen,
        )
        if all(value is None for value in measured):
            raise ValueError("A reading needs at least one measurement")
        return self


class ReadingRead(ORMModel):
    id: uuid.UUID
    location_id: uuid.UUID
    recorded_at: datetime
    temperature_c: float | None = None
    relative_humidity: float | None = None
    illuminance_lux: float | None = None
    uv_microwatt_lumen: float | None = None
    source: str | None = None
    recorded_by_id: uuid.UUID | None = None
    note: str | None = None


class ExcursionSummary(BaseModel):
    """How a location's readings compare with what it is meant to hold.

    A target with no readings cannot be shown to have been met; readings with
    no target cannot be judged. This puts the two together.
    """

    location_id: uuid.UUID
    display_path: str
    target_temperature_c: float | None = None
    target_humidity_percent: float | None = None
    reading_count: int = 0
    first_reading_at: datetime | None = None
    last_reading_at: datetime | None = None
    min_temperature_c: float | None = None
    max_temperature_c: float | None = None
    mean_temperature_c: float | None = None
    min_humidity: float | None = None
    max_humidity: float | None = None
    mean_humidity: float | None = None
    #: Readings outside the tolerance around the target.
    temperature_excursions: int = 0
    humidity_excursions: int = 0
    tolerance_temperature_c: float = 2.0
    tolerance_humidity: float = 5.0
