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
    #: A reference the importer cannot resolve on its own, and that the record
    #: it belongs to resolves instead. A find names its context by number —
    #: "1042" — and that number is only unique within a site, so there is no
    #: list of values to match against until the site is known. The importer
    #: passes such a column through as written and leaves it to the creator.
    resolved_late: bool = False
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
                                label="Inventory no.",
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


def equipment_layout() -> FormLayout:
    """The record card for one piece of kit.

    Ordered the way somebody with the thing in their hands fills it in: the
    number on the case first, then what it is, then the paperwork.
    """
    return FormLayout(
        record_type="equipment",
        title="Equipment record",
        title_field="name",
        key_field="asset_number",
        value_lists=["equipment_status_settable"],
        tabs=[
            FormTab(
                key="identification",
                label="Identification",
                groups=[
                    FormGroup(
                        label="What it is",
                        help="The asset number is what somebody reads off the case.",
                        fields=[
                            FormField(
                                name="asset_number",
                                label="Asset no.",
                                required=True,
                                max_length=80,
                                width=4,
                            ),
                            FormField(
                                name="name", label="Name", required=True, max_length=200, width=8
                            ),
                            FormField(
                                name="category",
                                label="Category",
                                max_length=120,
                                width=4,
                                help=(
                                    "Free text against what is already in use. Kit lists "
                                    "differ everywhere, and a closed list sends people "
                                    "back to their spreadsheet."
                                ),
                            ),
                            FormField(
                                name="status",
                                label="Status",
                                kind="select",
                                value_list="equipment_status_settable",
                                width=4,
                                help="Whether it can go out. Issuing it is a checkout, not an edit.",
                            ),
                            FormField(
                                name="description", label="Description", kind="textarea", width=12
                            ),
                        ],
                    ),
                    FormGroup(
                        label="Make and model",
                        fields=[
                            FormField(
                                name="manufacturer", label="Manufacturer", max_length=160, width=4
                            ),
                            FormField(name="model", label="Model", max_length=160, width=4),
                            FormField(
                                name="serial_number",
                                label="Serial no.",
                                max_length=160,
                                width=4,
                                help="The manufacturer's number, not yours. Insurers ask for it.",
                            ),
                            FormField(
                                name="condition_notes",
                                label="Condition",
                                kind="textarea",
                                width=12,
                                help='"Scratched lens, still usable" is the useful answer.',
                            ),
                        ],
                    ),
                ],
            ),
            FormTab(
                key="where",
                label="Where it lives",
                groups=[
                    FormGroup(
                        label="Home",
                        help=(
                            "Where it belongs when nobody has it — not where it is. "
                            "Where it is now is the open loan, below."
                        ),
                        fields=[
                            FormField(
                                name="storage_location_id",
                                label="Home shelf",
                                kind="reference",
                                references="storage_location",
                                width=6,
                            ),
                            FormField(name="notes", label="Notes", kind="textarea", width=12),
                        ],
                    ),
                ],
            ),
            FormTab(
                key="calibration",
                label="Calibration",
                groups=[
                    FormGroup(
                        label="Servicing",
                        help=(
                            "A trowel needs none of this. A total station, a level, a "
                            "pH meter and a set of scales all do, and using one that is "
                            "out of date can put a season's readings in doubt."
                        ),
                        fields=[
                            FormField(
                                name="needs_calibration",
                                label="Needs calibration",
                                kind="boolean",
                                width=4,
                            ),
                            FormField(
                                name="calibration_interval_days",
                                label="Interval",
                                kind="integer",
                                unit="days",
                                width=4,
                                help="How long a certificate lasts. 365 is common.",
                            ),
                            FormField(
                                name="calibration_due_on",
                                label="Due",
                                kind="date",
                                width=4,
                                read_only=True,
                                help="Set from the most recent certificate on file.",
                            ),
                        ],
                    ),
                ],
            ),
            FormTab(
                key="purchase",
                label="Purchase",
                groups=[
                    FormGroup(
                        label="How it was bought",
                        help="What an insurance claim or an audit asks for.",
                        fields=[
                            FormField(name="purchased_on", label="Purchased", kind="date", width=4),
                            FormField(name="purchase_price", label="Price", kind="number", width=4),
                            FormField(name="currency", label="Currency", max_length=3, width=4),
                            FormField(name="supplier", label="Supplier", max_length=200, width=6),
                            FormField(
                                name="warranty_until", label="Warranty until", kind="date", width=6
                            ),
                            FormField(
                                name="funding_source",
                                label="Funded by",
                                max_length=200,
                                width=6,
                                help="Which grant paid for it. Grants get reported on.",
                            ),
                        ],
                    ),
                ],
            ),
        ],
        portals=[
            FormPortal(
                key="checkouts",
                label="Who has had it",
                endpoint="/inventory/equipment/{id}/checkouts",
                columns=["borrower_label", "destination", "taken_at", "due_on", "returned_at"],
            ),
            FormPortal(
                key="calibrations",
                label="Calibration history",
                endpoint="/inventory/equipment/{id}/calibrations",
                columns=["performed_on", "performed_by", "result", "next_due_on"],
            ),
        ],
    )


def consumable_layout() -> FormLayout:
    """The record card for a stock line.

    The quantity is read-only here on purpose. It is the sum of a ledger, and
    a form that could type over the total would make the ledger decorative —
    so changing stock is a movement, with a reason attached.
    """
    return FormLayout(
        record_type="consumable",
        title="Stock line",
        title_field="name",
        key_field="code",
        value_lists=["stock_reason"],
        tabs=[
            FormTab(
                key="identification",
                label="Identification",
                groups=[
                    FormGroup(
                        label="What it is",
                        fields=[
                            FormField(
                                name="code", label="Code", required=True, max_length=80, width=4
                            ),
                            FormField(
                                name="name", label="Name", required=True, max_length=200, width=8
                            ),
                            FormField(name="category", label="Category", max_length=120, width=4),
                            FormField(
                                name="unit",
                                label="Unit",
                                max_length=60,
                                width=4,
                                help=(
                                    "What one of it is — bag, box of 100, roll, metre. "
                                    "A unit that does not match how the store buys the "
                                    "thing makes every count a translation exercise."
                                ),
                            ),
                            FormField(
                                name="description", label="Description", kind="textarea", width=12
                            ),
                        ],
                    ),
                    FormGroup(
                        label="On the shelf",
                        fields=[
                            FormField(
                                name="quantity",
                                label="In stock",
                                kind="number",
                                read_only=True,
                                width=4,
                                help="The sum of the ledger. Change it with a movement.",
                            ),
                            FormField(
                                name="reorder_level",
                                label="Reorder at",
                                kind="number",
                                width=4,
                                help="Below this it appears on the reorder list.",
                            ),
                            FormField(
                                name="expires_on",
                                label="Expires",
                                kind="date",
                                width=4,
                                help="Adhesives and chemicals go off. Before, not after.",
                            ),
                            FormField(
                                name="storage_location_id",
                                label="Kept in",
                                kind="reference",
                                references="storage_location",
                                width=6,
                            ),
                            FormField(name="is_active", label="In use", kind="boolean", width=6),
                        ],
                    ),
                ],
            ),
            FormTab(
                key="buying",
                label="Buying",
                groups=[
                    FormGroup(
                        label="Supplier",
                        fields=[
                            FormField(name="supplier", label="Supplier", max_length=200, width=6),
                            FormField(
                                name="supplier_reference",
                                label="Their reference",
                                max_length=120,
                                width=6,
                                help="What to quote when reordering.",
                            ),
                            FormField(name="unit_cost", label="Unit cost", kind="number", width=4),
                            FormField(name="currency", label="Currency", max_length=3, width=4),
                            FormField(name="notes", label="Notes", kind="textarea", width=12),
                        ],
                    ),
                ],
            ),
        ],
        portals=[
            FormPortal(
                key="movements",
                label="The ledger",
                endpoint="/inventory/consumables/{id}/movements",
                columns=["occurred_at", "change", "balance_after", "reason", "issued_to_label"],
            ),
        ],
    )


# --------------------------------------------------------------------------
# The excavation layouts
#
# These exist first of all so that excavation data can be **imported**. The
# importer builds its column mapping from a layout, so a record type with no
# layout cannot be imported at all — which is why, until now, a museum could
# migrate off its spreadsheets and an excavation could not.
#
# They are written from the shape of a real site archive rather than from the
# database columns: a site sheet, a context sheet, a finds register. The order
# is the order those sheets are filled in, because that is the order a
# spreadsheet exported from one will be in.
# --------------------------------------------------------------------------
def site_layout() -> FormLayout:
    """The site record: what it is, where it is, and what protects it."""
    return FormLayout(
        record_type="site",
        title="Site",
        title_field="name",
        key_field="code",
        value_lists=["period", "condition", "site_type", "protection_status", "project"],
        tabs=[
            FormTab(
                key="identification",
                label="Identification",
                groups=[
                    FormGroup(
                        label="Names and numbers",
                        help="The code is what everything else on the dig refers to.",
                        fields=[
                            FormField(
                                name="code",
                                label="Site code",
                                required=True,
                                max_length=60,
                                width=4,
                                help="Short, and the one printed on bags and labels.",
                            ),
                            FormField(
                                name="name",
                                label="Site name",
                                required=True,
                                max_length=300,
                                width=4,
                            ),
                            FormField(
                                name="project_id",
                                label="Project",
                                kind="reference",
                                references="project",
                                value_list="project",
                                required=True,
                                width=4,
                            ),
                            FormField(
                                name="alternative_names",
                                label="Also known as",
                                kind="tags",
                                width=6,
                                help="Local names, older publications, transliterations.",
                            ),
                            FormField(
                                name="national_register_id",
                                label="National register no.",
                                max_length=120,
                                width=6,
                            ),
                            FormField(
                                name="site_type",
                                label="Type",
                                kind="select",
                                value_list="site_type",
                                width=6,
                            ),
                            FormField(
                                name="description", label="Description", kind="textarea", width=12
                            ),
                        ],
                    ),
                ],
            ),
            FormTab(
                key="location",
                label="Location",
                groups=[
                    FormGroup(
                        label="Coordinates",
                        help=(
                            "Decimal degrees. Mark the site restricted if publishing "
                            "its position would put it at risk — the platform then "
                            "blurs it on the map, leaves it out of exports, and hides "
                            "it from search for anyone who may not edit it."
                        ),
                        fields=[
                            FormField(
                                name="latitude", label="Latitude", kind="number", width=4, unit="°"
                            ),
                            FormField(
                                name="longitude",
                                label="Longitude",
                                kind="number",
                                width=4,
                                unit="°",
                            ),
                            FormField(
                                name="elevation",
                                label="Elevation",
                                kind="number",
                                width=4,
                                unit="m",
                            ),
                            FormField(
                                name="location_accuracy_m",
                                label="Accuracy",
                                kind="number",
                                width=4,
                                unit="m",
                            ),
                            FormField(
                                name="location_restricted",
                                label="Position is restricted",
                                kind="boolean",
                                width=8,
                            ),
                        ],
                    ),
                    FormGroup(
                        label="Where",
                        fields=[
                            FormField(name="country", label="Country", max_length=100, width=4),
                            FormField(name="region", label="Region", max_length=200, width=4),
                            FormField(name="district", label="District", max_length=200, width=4),
                            FormField(
                                name="municipality", label="Municipality", max_length=200, width=6
                            ),
                            FormField(name="address", label="Address", max_length=400, width=6),
                        ],
                    ),
                ],
            ),
            FormTab(
                key="dating",
                label="Dating & condition",
                groups=[
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
                                name="period_text",
                                label="Period as written",
                                max_length=300,
                                width=6,
                                help="Kept as recorded when it does not match a period in the list.",
                            ),
                            FormField(
                                name="date_from", label="From (year)", kind="integer", width=4
                            ),
                            FormField(name="date_to", label="To (year)", kind="integer", width=4),
                            FormField(
                                name="dating_method", label="Dating method", max_length=200, width=4
                            ),
                        ],
                    ),
                    FormGroup(
                        label="Condition and protection",
                        fields=[
                            FormField(
                                name="condition",
                                label="Condition",
                                kind="select",
                                value_list="condition",
                                width=4,
                            ),
                            FormField(
                                name="protection_status",
                                label="Protection",
                                kind="select",
                                value_list="protection_status",
                                width=4,
                            ),
                            FormField(name="threats", label="Threats", kind="tags", width=4),
                            FormField(name="land_use", label="Land use", max_length=200, width=6),
                            FormField(name="landowner", label="Landowner", max_length=300, width=6),
                        ],
                    ),
                ],
            ),
            FormTab(
                key="work",
                label="Work & notes",
                groups=[
                    FormGroup(
                        label="Fieldwork",
                        fields=[
                            FormField(
                                name="discovery_date", label="Discovered on", kind="date", width=4
                            ),
                            FormField(
                                name="discovered_by", label="Discovered by", max_length=300, width=8
                            ),
                            FormField(
                                name="excavation_start",
                                label="Excavation from",
                                kind="date",
                                width=4,
                            ),
                            FormField(
                                name="excavation_end", label="Excavation to", kind="date", width=4
                            ),
                        ],
                    ),
                    FormGroup(
                        label="Other fields",
                        help="Anything this project records that the form above does not.",
                        fields=[
                            FormField(
                                name="references", label="References", kind="textarea", width=12
                            ),
                            FormField(name="notes", label="Notes", kind="textarea", width=12),
                            FormField(name="keywords", label="Keywords", kind="tags", width=6),
                            FormField(name="is_public", label="Public", kind="boolean", width=6),
                            FormField(
                                name="metadata_json", label="Extra fields", kind="json", width=12
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )


def context_layout() -> FormLayout:
    """The context sheet.

    Grouped the way the paper sheet is: number and type first, then where it
    was dug, then what it was made of, then how it relates to everything else.
    Stratigraphic relationships are not on here — they come from the matrix,
    which has its own import because a relationship is between two records and
    a row on a context sheet is about one.
    """
    return FormLayout(
        record_type="excavation_context",
        title="Context",
        title_field="context_number",
        key_field="context_number",
        value_lists=["period", "context_type", "site"],
        tabs=[
            FormTab(
                key="identification",
                label="Identification",
                groups=[
                    FormGroup(
                        label="The unit",
                        fields=[
                            FormField(
                                name="context_number",
                                label="Context no.",
                                required=True,
                                max_length=50,
                                width=4,
                            ),
                            FormField(
                                name="site_id",
                                label="Site",
                                kind="reference",
                                references="site",
                                value_list="site",
                                required=True,
                                width=4,
                                help="Set once for the whole file unless the sheet covers several.",
                            ),
                            FormField(
                                name="context_type",
                                label="Type",
                                kind="select",
                                value_list="context_type",
                                required=True,
                                width=4,
                                help="Layer, cut, fill, wall, and so on.",
                            ),
                            FormField(
                                name="stratigraphic_unit",
                                label="Stratigraphic unit",
                                max_length=80,
                                width=4,
                            ),
                            FormField(name="trench", label="Trench", max_length=80, width=4),
                            FormField(name="area", label="Area", max_length=80, width=4),
                            FormField(name="square", label="Square / grid", max_length=80, width=4),
                            FormField(name="phase", label="Phase", max_length=80, width=4),
                        ],
                    ),
                    FormGroup(
                        label="Description",
                        fields=[
                            FormField(
                                name="description", label="Description", kind="textarea", width=12
                            ),
                            FormField(
                                name="interpretation",
                                label="Interpretation",
                                kind="textarea",
                                width=12,
                                help="What it is taken to mean, kept separate from what was seen.",
                            ),
                        ],
                    ),
                ],
            ),
            FormTab(
                key="matrix",
                label="Deposit",
                groups=[
                    FormGroup(
                        label="What it is made of",
                        fields=[
                            FormField(
                                name="munsell_color",
                                label="Munsell",
                                max_length=30,
                                width=4,
                                placeholder="10YR 5/3",
                            ),
                            FormField(
                                name="composition", label="Composition", max_length=300, width=8
                            ),
                            FormField(
                                name="compaction", label="Compaction", max_length=120, width=4
                            ),
                            FormField(
                                name="inclusions", label="Inclusions", kind="textarea", width=8
                            ),
                        ],
                    ),
                    FormGroup(
                        label="Measurements",
                        fields=[
                            FormField(
                                name="length_cm", label="Length", kind="number", width=3, unit="cm"
                            ),
                            FormField(
                                name="width_cm", label="Width", kind="number", width=3, unit="cm"
                            ),
                            FormField(
                                name="depth_cm", label="Depth", kind="number", width=3, unit="cm"
                            ),
                            FormField(
                                name="thickness_cm",
                                label="Thickness",
                                kind="number",
                                width=3,
                                unit="cm",
                            ),
                            FormField(
                                name="top_elevation",
                                label="Top elevation",
                                kind="number",
                                width=4,
                                unit="m",
                            ),
                            FormField(
                                name="bottom_elevation",
                                label="Bottom elevation",
                                kind="number",
                                width=4,
                                unit="m",
                            ),
                            FormField(
                                name="latitude", label="Latitude", kind="number", width=4, unit="°"
                            ),
                            FormField(
                                name="longitude",
                                label="Longitude",
                                kind="number",
                                width=4,
                                unit="°",
                            ),
                        ],
                    ),
                ],
            ),
            FormTab(
                key="record",
                label="Recording & dating",
                groups=[
                    FormGroup(
                        label="Who and when",
                        fields=[
                            FormField(
                                name="excavation_date", label="Excavated on", kind="date", width=4
                            ),
                            FormField(
                                name="excavated_by", label="Excavated by", max_length=300, width=4
                            ),
                            FormField(
                                name="recorded_by", label="Recorded by", max_length=300, width=4
                            ),
                            FormField(name="samples_taken", label="Samples", kind="tags", width=12),
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
                                name="dating_evidence",
                                label="Dating evidence",
                                kind="textarea",
                                width=6,
                            ),
                            FormField(
                                name="date_from", label="From (year)", kind="integer", width=4
                            ),
                            FormField(name="date_to", label="To (year)", kind="integer", width=4),
                        ],
                    ),
                    FormGroup(
                        label="Other fields",
                        fields=[
                            FormField(name="notes", label="Notes", kind="textarea", width=12),
                            FormField(
                                name="metadata_json", label="Extra fields", kind="json", width=12
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )


def artifact_layout() -> FormLayout:
    """The finds register.

    A finds register is one row per find, and the columns are always the same
    six: number, what it is, where it came from, how big, what date, where it
    is now. Everything else is a specialist's column added later.
    """
    return FormLayout(
        record_type="artifact",
        title="Find",
        title_field="name",
        key_field="inventory_number",
        value_lists=[
            "period",
            "material",
            "object_category",
            "condition",
            "conservation_status",
            "site",
        ],
        tabs=[
            FormTab(
                key="identification",
                label="Identification",
                groups=[
                    FormGroup(
                        label="Numbers",
                        help="The inventory number is the find's identity. It goes on the bag.",
                        fields=[
                            FormField(
                                name="inventory_number",
                                label="Inventory no.",
                                required=True,
                                max_length=100,
                                width=4,
                            ),
                            FormField(
                                name="field_number",
                                label="Field no.",
                                max_length=100,
                                width=4,
                                help="What it was called in the trench, before it was registered.",
                            ),
                            FormField(
                                name="accession_number",
                                label="Museum no.",
                                max_length=100,
                                width=4,
                                help="If it has since been accessioned into a collection.",
                            ),
                            FormField(
                                name="site_id",
                                label="Site",
                                kind="reference",
                                references="site",
                                value_list="site",
                                required=True,
                                width=4,
                                help="Set once for the whole file unless the sheet covers several.",
                            ),
                        ],
                    ),
                    FormGroup(
                        label="What it is",
                        fields=[
                            FormField(name="name", label="Name", max_length=300, width=6),
                            FormField(
                                name="object_type", label="Object type", max_length=200, width=6
                            ),
                            FormField(
                                name="category_id",
                                label="Category",
                                kind="reference",
                                references="object_category",
                                value_list="object_category",
                                width=6,
                            ),
                            FormField(name="typology", label="Typology", max_length=200, width=6),
                            FormField(
                                name="description", label="Description", kind="textarea", width=12
                            ),
                            FormField(
                                name="quantity",
                                label="Quantity",
                                kind="integer",
                                width=4,
                                help="More than one where a bag of sherds is registered as one find.",
                            ),
                            FormField(
                                name="is_fragment", label="Fragment", kind="boolean", width=4
                            ),
                        ],
                    ),
                ],
            ),
            FormTab(
                key="provenance",
                label="Where it came from",
                groups=[
                    FormGroup(
                        label="On the site",
                        help=(
                            "Context is what ties the find to the sequence. A find "
                            "without one is a find that cannot be dated by anything "
                            "but itself."
                        ),
                        fields=[
                            FormField(
                                name="context_id",
                                label="Context",
                                kind="reference",
                                references="excavation_context",
                                resolved_late=True,
                                width=4,
                                help="By context number, as the register writes it.",
                            ),
                            FormField(
                                name="stratigraphic_unit",
                                label="Stratigraphic unit",
                                max_length=80,
                                width=4,
                            ),
                            FormField(name="trench", label="Trench", max_length=80, width=4),
                            FormField(name="square", label="Square / grid", max_length=80, width=4),
                            FormField(
                                name="depth_cm", label="Depth", kind="number", width=4, unit="cm"
                            ),
                            FormField(
                                name="elevation",
                                label="Elevation",
                                kind="number",
                                width=4,
                                unit="m",
                            ),
                            FormField(
                                name="latitude", label="Latitude", kind="number", width=4, unit="°"
                            ),
                            FormField(
                                name="longitude",
                                label="Longitude",
                                kind="number",
                                width=4,
                                unit="°",
                            ),
                        ],
                    ),
                    FormGroup(
                        label="Recovery",
                        fields=[
                            FormField(name="find_date", label="Found on", kind="date", width=4),
                            FormField(name="found_by", label="Found by", max_length=300, width=4),
                            FormField(
                                name="recovery_method",
                                label="Recovery method",
                                max_length=120,
                                width=4,
                                help="Excavation, sieving, surface collection, flotation.",
                            ),
                        ],
                    ),
                ],
            ),
            FormTab(
                key="measurement",
                label="Measurement & material",
                groups=[
                    FormGroup(
                        label="Material",
                        fields=[
                            FormField(
                                name="material_id",
                                label="Material",
                                kind="reference",
                                references="material",
                                value_list="material",
                                width=4,
                            ),
                            FormField(
                                name="material_text",
                                label="Material as written",
                                max_length=200,
                                width=4,
                                help="Kept as recorded when it does not match the list.",
                            ),
                            FormField(name="technique", label="Technique", max_length=200, width=4),
                            FormField(
                                name="decoration", label="Decoration", kind="textarea", width=6
                            ),
                            FormField(
                                name="inscription", label="Inscription", kind="textarea", width=6
                            ),
                        ],
                    ),
                    FormGroup(
                        label="Dimensions",
                        fields=[
                            FormField(
                                name="length_mm", label="Length", kind="number", width=3, unit="mm"
                            ),
                            FormField(
                                name="width_mm", label="Width", kind="number", width=3, unit="mm"
                            ),
                            FormField(
                                name="height_mm", label="Height", kind="number", width=3, unit="mm"
                            ),
                            FormField(
                                name="thickness_mm",
                                label="Thickness",
                                kind="number",
                                width=3,
                                unit="mm",
                            ),
                            FormField(
                                name="diameter_mm",
                                label="Diameter",
                                kind="number",
                                width=3,
                                unit="mm",
                            ),
                            FormField(
                                name="rim_diameter_mm",
                                label="Rim diameter",
                                kind="number",
                                width=3,
                                unit="mm",
                            ),
                            FormField(
                                name="weight_g", label="Weight", kind="number", width=3, unit="g"
                            ),
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
                                width=4,
                            ),
                            FormField(
                                name="period_text",
                                label="Period as written",
                                max_length=200,
                                width=4,
                            ),
                            FormField(
                                name="dating_method", label="Dating method", max_length=200, width=4
                            ),
                            FormField(
                                name="date_from", label="From (year)", kind="integer", width=4
                            ),
                            FormField(name="date_to", label="To (year)", kind="integer", width=4),
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
                                label="Conservation",
                                kind="select",
                                value_list="conservation_status",
                                width=4,
                            ),
                            FormField(
                                name="conservation_notes",
                                label="Conservation notes",
                                kind="textarea",
                                width=12,
                            ),
                        ],
                    ),
                    FormGroup(
                        label="Where it is now",
                        fields=[
                            FormField(
                                name="current_location",
                                label="Location as written",
                                max_length=300,
                                width=6,
                                help=(
                                    "Free text, from before the store was a tree. New "
                                    "records should be filed into a storage location "
                                    "instead; this is kept because it is the only "
                                    "record of where legacy material was said to be."
                                ),
                            ),
                            FormField(name="storage_box", label="Box", max_length=120, width=3),
                            FormField(
                                name="is_on_display", label="On display", kind="boolean", width=3
                            ),
                        ],
                    ),
                    FormGroup(
                        label="Other fields",
                        fields=[
                            FormField(
                                name="research_notes",
                                label="Research notes",
                                kind="textarea",
                                width=12,
                            ),
                            FormField(name="keywords", label="Keywords", kind="tags", width=6),
                            FormField(name="is_public", label="Public", kind="boolean", width=6),
                            FormField(
                                name="metadata_json", label="Extra fields", kind="json", width=12
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )


LAYOUTS = {
    "museum_object": museum_object_layout,
    "equipment": equipment_layout,
    "consumable": consumable_layout,
    "site": site_layout,
    "excavation_context": context_layout,
    "artifact": artifact_layout,
}


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
        CalibrationResult,
        ConditionState,
        ConservationStatus,
        ContextType,
        EquipmentStatus,
        ExhibitionStatus,
        LoanDirection,
        LoanStatus,
        ObjectStatus,
        ProtectionStatus,
        SiteType,
        StockReason,
        TreatmentType,
    )
    from app.models.museum import Collection
    from app.models.project import Project
    from app.models.site import Site
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
        "equipment_status": EquipmentStatus,
        "stock_reason": StockReason,
        "calibration_result": CalibrationResult,
        "site_type": SiteType,
        "protection_status": ProtectionStatus,
        "context_type": ContextType,
    }

    # Every status *except* "checked out". A form that offers it produces an
    # item the register says is gone with nothing saying who has it, which is
    # what the API refuses — so the dropdown should not hold out the option in
    # the first place. Filtering here rather than in the frontend keeps the one
    # rule in one place.
    settable_statuses = [
        option
        for option in _enum_options(EquipmentStatus)
        if option["value"] != EquipmentStatus.CHECKED_OUT.value
    ]
    tables = {"period": Period, "material": Material, "object_category": ObjectCategory}

    resolved: dict[str, list[dict[str, str]]] = {}
    for name in names:
        if name == "equipment_status_settable":
            resolved[name] = settable_statuses
        elif name in static:
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
        elif name == "project":
            resolved[name] = [
                {"value": str(row.id), "label": f"{row.code} — {row.name}"}
                for row in session.scalars(select(Project).order_by(Project.name)).all()
            ]
        elif name == "site":
            # Code first: a finds register says "TED", not the site's full name,
            # and the importer accepts either side of the dash.
            resolved[name] = [
                {"value": str(row.id), "label": f"{row.code} — {row.name}"}
                for row in session.scalars(select(Site).order_by(Site.code)).all()
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
