"""Form layouts, served to the client rather than hard-coded in it.

Museum cataloguers work in FileMaker. Whatever else is true of it, its data
entry model is the one they know: a **layout** — one record shown as a card of
labelled fields, grouped into tabs, with dropdowns driven by value lists,
related records shown in panels, and a record counter you page through.

This module describes that layout as data. The frontend renders it; it does not
decide it. Three reasons that is worth the indirection:

1. **The layout is institutional.** Which fields matter, what they are called,
   what order they come in — that is a curatorial decision, not a frontend one,
   and it differs between a coin cabinet and a textile store.
2. **Value lists live in the database already.** Periods, materials and
   categories are taxonomy tables; a form that hard-codes them goes stale the
   moment somebody adds a period.
3. **The importer needs the same description.** Mapping a spreadsheet column
   onto a field requires knowing what fields exist, what type each is, and
   which are required — exactly what a layout says. One description serves
   both, so they cannot disagree about what a record holds.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

FieldKind = Literal[
    "text",
    "textarea",
    "number",
    "integer",
    "date",
    "datetime",
    "boolean",
    "select",
    "multiselect",
    "reference",
    "tags",
    "json",
]


@dataclass
class FormField:
    """One field on a layout."""

    name: str
    label: str
    kind: FieldKind = "text"
    required: bool = False
    #: Explanatory text shown beside the field. Where a cataloguing convention
    #: needs stating, this is where it is stated.
    help: str | None = None
    placeholder: str | None = None
    max_length: int | None = None
    #: For ``select`` and ``multiselect``: which value list fills it.
    value_list: str | None = None
    #: For ``reference``: which record type it points at.
    references: str | None = None
    #: A field the platform sets and a person does not type.
    read_only: bool = False
    #: How many columns of the row this field occupies, out of twelve.
    width: int = 6
    unit: str | None = None


@dataclass
class FormGroup:
    """A labelled block of fields within a tab."""

    label: str
    fields: list[FormField] = field(default_factory=list)
    help: str | None = None


@dataclass
class FormTab:
    """One tab of a layout."""

    key: str
    label: str
    groups: list[FormGroup] = field(default_factory=list)


@dataclass
class FormPortal:
    """Related records shown inline, FileMaker's "portal".

    A conservation history belongs on the object's card, not behind a link:
    the whole point of the layout is that everything about the object is in
    front of you.
    """

    key: str
    label: str
    #: Where the client fetches the rows.
    endpoint: str
    #: Columns worth showing in the panel, in order.
    columns: list[str] = field(default_factory=list)
    can_add: bool = True


@dataclass
class FormLayout:
    """A complete layout for one record type."""

    record_type: str
    title: str
    #: Which field to show as the record's heading.
    title_field: str
    #: The identifier a cataloguer searches by.
    key_field: str
    tabs: list[FormTab] = field(default_factory=list)
    portals: list[FormPortal] = field(default_factory=list)
    #: Names of the value lists this layout needs, resolved separately so the
    #: layout itself can be cached and the lists cannot go stale with it.
    value_lists: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------
# The museum object layout
# --------------------------------------------------------------------------
def museum_object_layout() -> FormLayout:
    """The cataloguing card for an accessioned object."""
    return FormLayout(
        record_type="museum_object",
        title="Object record",
        title_field="title",
        key_field="accession_number",
        value_lists=[
            "acquisition_method",
            "condition",
            "conservation_status",
            "object_status",
            "period",
            "material",
            "object_category",
            "collection",
        ],
        tabs=[
            FormTab(
                key="identification",
                label="Identification",
                groups=[
                    FormGroup(
                        label="Numbers",
                        help="The number is the object's identity. It is printed on it.",
                        fields=[
                            FormField(
                                name="accession_number",
                                label="Accession no.",
                                required=True,
                                max_length=120,
                                width=4,
                                help="Leave blank to take the next number in the collection.",
                            ),
                            FormField(
                                name="collection_id",
                                label="Collection",
                                kind="reference",
                                references="collection",
                                value_list="collection",
                                required=True,
                                width=4,
                            ),
                            FormField(
                                name="former_number",
                                label="Former no.",
                                max_length=120,
                                width=4,
                                help="An old ledger, donor or previous-institution number.",
                            ),
                            FormField(
                                name="part_number",
                                label="Part",
                                max_length=40,
                                width=4,
                                help="For an object catalogued in parts: 3 of 12.",
                            ),
                            FormField(
                                name="object_count",
                                label="Number of pieces",
                                kind="integer",
                                width=4,
                            ),
                            FormField(
                                name="number_is_legacy",
                                label="Legacy number",
                                kind="boolean",
                                read_only=True,
                                width=4,
                                help="Set when the number predates the current scheme.",
                            ),
                        ],
                    ),
                    FormGroup(
                        label="Description",
                        fields=[
                            FormField(name="title", label="Object name", required=True, width=8),
                            FormField(name="object_type", label="Object type", width=4),
                            FormField(
                                name="description", label="Description", kind="textarea", width=12
                            ),
                            FormField(
                                name="category_id",
                                label="Category",
                                kind="reference",
                                references="object_category",
                                value_list="object_category",
                                width=6,
                            ),
                            FormField(name="culture", label="Culture", width=6),
                            FormField(
                                name="materials",
                                label="Materials",
                                kind="multiselect",
                                value_list="material",
                                width=6,
                            ),
                            FormField(name="techniques", label="Techniques", kind="tags", width=6),
                            FormField(name="maker", label="Maker / workshop", width=6),
                            FormField(
                                name="inscription", label="Inscription", kind="textarea", width=6
                            ),
                            FormField(name="marks", label="Marks", kind="textarea", width=6),
                        ],
                    ),
                    FormGroup(
                        label="Date",
                        help="Years are signed: -2900 means 2900 BCE.",
                        fields=[
                            FormField(
                                name="period_id",
                                label="Period",
                                kind="reference",
                                references="period",
                                value_list="period",
                                width=6,
                            ),
                            FormField(
                                name="date_from", label="From (year)", kind="integer", width=3
                            ),
                            FormField(name="date_to", label="To (year)", kind="integer", width=3),
                            FormField(name="date_note", label="Dating note", width=12),
                        ],
                    ),
                ],
            ),
            FormTab(
                key="measurement",
                label="Measurement",
                groups=[
                    FormGroup(
                        label="Dimensions",
                        help="All lengths in millimetres, weight in grams.",
                        fields=[
                            FormField(
                                name="height_mm", label="Height", kind="number", unit="mm", width=3
                            ),
                            FormField(
                                name="width_mm", label="Width", kind="number", unit="mm", width=3
                            ),
                            FormField(
                                name="depth_mm", label="Depth", kind="number", unit="mm", width=3
                            ),
                            FormField(
                                name="diameter_mm",
                                label="Diameter",
                                kind="number",
                                unit="mm",
                                width=3,
                            ),
                            FormField(
                                name="thickness_mm",
                                label="Thickness",
                                kind="number",
                                unit="mm",
                                width=3,
                            ),
                            FormField(
                                name="weight_g", label="Weight", kind="number", unit="g", width=3
                            ),
                            FormField(name="dimension_note", label="Note", width=6),
                        ],
                    )
                ],
            ),
            FormTab(
                key="acquisition",
                label="Acquisition & provenance",
                groups=[
                    FormGroup(
                        label="How it was acquired",
                        fields=[
                            FormField(
                                name="acquisition_method",
                                label="Method",
                                kind="select",
                                value_list="acquisition_method",
                                width=4,
                            ),
                            FormField(
                                name="acquisition_date", label="Date acquired", kind="date", width=4
                            ),
                            FormField(name="acquisition_source", label="Source", width=4),
                            FormField(
                                name="credit_line",
                                label="Credit line",
                                width=6,
                                help="As it should appear on a label or in a publication.",
                            ),
                            FormField(
                                name="acquisition_note", label="Note", kind="textarea", width=12
                            ),
                        ],
                    ),
                    FormGroup(
                        label="Provenance",
                        help=(
                            "Everything known about where this object was before the "
                            "institution held it. The first thing anyone will ask."
                        ),
                        fields=[
                            FormField(
                                name="provenance", label="Provenance", kind="textarea", width=12
                            )
                        ],
                    ),
                    FormGroup(
                        label="Valuation and insurance",
                        help="Visible only to those who may edit this record.",
                        fields=[
                            FormField(
                                name="valuation_amount", label="Valuation", kind="number", width=4
                            ),
                            FormField(
                                name="valuation_currency", label="Currency", max_length=3, width=2
                            ),
                            FormField(
                                name="valuation_date", label="Valued on", kind="date", width=3
                            ),
                            FormField(name="insurance_reference", label="Policy ref.", width=3),
                        ],
                    ),
                ],
            ),
            FormTab(
                key="condition",
                label="Condition & location",
                groups=[
                    FormGroup(
                        label="Condition",
                        fields=[
                            FormField(
                                name="condition",
                                label="Condition",
                                kind="select",
                                value_list="condition",
                                width=4,
                            ),
                            FormField(
                                name="conservation_status",
                                label="Conservation status",
                                kind="select",
                                value_list="conservation_status",
                                width=4,
                            ),
                            FormField(
                                name="last_checked_on", label="Last checked", kind="date", width=4
                            ),
                            FormField(
                                name="condition_note",
                                label="Condition note",
                                kind="textarea",
                                width=12,
                            ),
                        ],
                    ),
                    FormGroup(
                        label="Where it is",
                        fields=[
                            FormField(
                                name="status",
                                label="Status",
                                kind="select",
                                value_list="object_status",
                                width=4,
                            ),
                            FormField(
                                name="storage_location_id",
                                label="Current location",
                                kind="reference",
                                references="storage_location",
                                width=4,
                            ),
                            FormField(
                                name="home_location_id",
                                label="Home location",
                                kind="reference",
                                references="storage_location",
                                width=4,
                                help="Where it returns to after display or treatment.",
                            ),
                        ],
                    ),
                    FormGroup(
                        label="Deaccession",
                        help="Only when the object has formally left the collection.",
                        fields=[
                            FormField(
                                name="deaccession_date",
                                label="Deaccessioned on",
                                kind="date",
                                width=4,
                            ),
                            FormField(
                                name="deaccession_reason", label="Reason", kind="textarea", width=8
                            ),
                        ],
                    ),
                ],
            ),
            FormTab(
                key="links",
                label="Links & publication",
                groups=[
                    FormGroup(
                        label="Excavation record",
                        help=(
                            "Set when this object came out of a recorded excavation. "
                            "The excavation record stays as it was written in the field; "
                            "this record carries everything that happened afterwards."
                        ),
                        fields=[
                            FormField(
                                name="artifact_id",
                                label="Artifact",
                                kind="reference",
                                references="artifact",
                                width=6,
                            )
                        ],
                    ),
                    FormGroup(
                        label="Publication",
                        fields=[
                            FormField(
                                name="is_published", label="Published", kind="boolean", width=3
                            ),
                            FormField(
                                name="is_public", label="Publicly visible", kind="boolean", width=3
                            ),
                            FormField(name="rights_statement", label="Rights", width=6),
                            FormField(name="tags", label="Tags", kind="tags", width=12),
                        ],
                    ),
                    FormGroup(
                        label="Other fields",
                        help="Anything this institution records that the form above does not.",
                        fields=[
                            FormField(
                                name="metadata_json", label="Custom fields", kind="json", width=12
                            )
                        ],
                    ),
                ],
            ),
        ],
        portals=[
            FormPortal(
                key="conservation",
                label="Conservation history",
                endpoint="/api/v1/museum/objects/{id}/conservation",
                columns=["performed_on", "treatment_type", "conservator", "description"],
            ),
            FormPortal(
                key="movements",
                label="Location history",
                endpoint="/api/v1/storage/museum_objects/{id}/movements",
                columns=["moved_at", "reason", "from_path", "to_path", "moved_by_label"],
                can_add=False,
            ),
            FormPortal(
                key="photographs",
                label="Photographs",
                endpoint="/api/v1/photographs?museum_object_id={id}",
                columns=["title", "taken_at", "photographer"],
            ),
            FormPortal(
                key="exhibitions",
                label="Exhibitions",
                endpoint="/api/v1/museum/objects/{id}/exhibitions",
                columns=["title", "venue", "opens_on", "closes_on"],
                can_add=False,
            ),
        ],
    )


LAYOUTS = {"museum_object": museum_object_layout}


def get_layout(record_type: str) -> FormLayout | None:
    builder = LAYOUTS.get(record_type)
    return builder() if builder is not None else None


# --------------------------------------------------------------------------
# Value lists
# --------------------------------------------------------------------------
def _enum_options(enum_class: Any) -> list[dict[str, str]]:
    return [
        {"value": member.value, "label": member.value.replace("_", " ").capitalize()}
        for member in enum_class
    ]


def value_lists(session: Session, names: list[str]) -> dict[str, list[dict[str, str]]]:
    """Resolve the value lists a layout asks for.

    Taxonomy lists come from the database, so a period added this morning is
    in the dropdown this afternoon without a deployment.
    """
    from app.models.enums import (
        AcquisitionMethod,
        ConditionState,
        ConservationStatus,
        ExhibitionStatus,
        LoanDirection,
        LoanStatus,
        ObjectStatus,
        TreatmentType,
    )
    from app.models.museum import Collection
    from app.models.taxonomy import Material, ObjectCategory, Period

    static: dict[str, Any] = {
        "acquisition_method": AcquisitionMethod,
        "condition": ConditionState,
        "conservation_status": ConservationStatus,
        "object_status": ObjectStatus,
        "treatment_type": TreatmentType,
        "exhibition_status": ExhibitionStatus,
        "loan_direction": LoanDirection,
        "loan_status": LoanStatus,
    }
    tables = {"period": Period, "material": Material, "object_category": ObjectCategory}

    resolved: dict[str, list[dict[str, str]]] = {}
    for name in names:
        if name in static:
            resolved[name] = _enum_options(static[name])
        elif name in tables:
            model = tables[name]
            resolved[name] = [
                {"value": str(row.id), "label": row.name}
                for row in session.scalars(select(model).order_by(model.name)).all()
            ]
        elif name == "collection":
            resolved[name] = [
                {"value": str(row.id), "label": f"{row.code} — {row.name}"}
                for row in session.scalars(select(Collection).order_by(Collection.name)).all()
            ]
    return resolved


def field_index(layout: FormLayout) -> dict[str, FormField]:
    """Every field on a layout, by name.

    The importer's column mapping is built from this, so a field on the form
    is a field a spreadsheet can be mapped onto, with no second list to keep
    in step.
    """
    fields: dict[str, FormField] = {}
    for tab in layout.tabs:
        for group in tab.groups:
            for form_field in group.fields:
                fields[form_field.name] = form_field
    return fields
