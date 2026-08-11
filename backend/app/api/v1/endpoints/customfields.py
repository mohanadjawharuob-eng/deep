"""Fields an institution adds to the platform's own forms.

Every heritage institution records something the next one does not, and until
now the answer was a spreadsheet kept beside the platform — which is where the
real recording then quietly happens. This is the smallest thing that stops
that: a form for adding a field to a form.

Three rules, each of which costs something and is worth it.

**A name is chosen once.** The key is what values are stored under inside the
record's ``metadata_json``; renaming it would leave every value already written
filed under a key nothing reads. Labels change freely, because a label is only
a caption.

**A custom field cannot shadow a platform one.** Two fields called
``description`` on one form is a form where one of them silently wins, and the
one that wins is not the one somebody typed into. Rejected at creation, when it
is still a typo rather than a month of data.

**Removing one is retiring it, unless you say otherwise.** Deleting a
definition leaves values in the archive that nothing can read or explain, which
is the worst state for an archive to be in. So the ordinary delete retires the
field — values stay, exports still carry them, the form stops offering it. Only
an explicit *and erase the values* deletes both, and it says how many records
it touched.
"""

from __future__ import annotations

import re
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.api.deps import CurrentUser, DbSession, require_capability
from app.core.permissions import Capability
from app.models.artifact import Artifact
from app.models.context import ExcavationContext
from app.models.customfield import CustomField
from app.models.enums import ActivityAction
from app.models.inventory import Consumable, Equipment
from app.models.museum import MuseumObject
from app.models.site import Site
from app.models.user import User
from app.schemas.common import Message, ORMModel
from app.services import activity, forms

router = APIRouter(prefix="/custom-fields", tags=["Forms"])

#: Deciding what the institution records is the same kind of decision as
#: deciding its period list, and is held by the same people.
RequireFormAdmin = Annotated[User, Depends(require_capability(Capability.MANAGE_TAXONOMY))]

#: Where the values of a record type's custom fields are actually stored, for
#: the one operation that has to reach them: erasing a field for good.
_RECORDS: dict[str, Any] = {
    "museum_object": MuseumObject,
    "site": Site,
    "excavation_context": ExcavationContext,
    "artifact": Artifact,
    "equipment": Equipment,
    "consumable": Consumable,
}

#: Kinds a custom field may be. ``reference`` is deliberately absent: a value
#: in a JSON blob is not a foreign key, nothing enforces it, and offering one
#: would promise an integrity the storage cannot keep.
KINDS = ("text", "textarea", "number", "integer", "date", "boolean", "select")


class CustomFieldRead(ORMModel):
    id: uuid.UUID
    record_type: str
    name: str
    label: str
    kind: str
    choices: list[str] | None = None
    help: str | None = None
    required: bool
    position: int
    is_active: bool


class CustomFieldWrite(BaseModel):
    record_type: str
    label: str = Field(min_length=1, max_length=120)
    #: Optional: derived from the label when left out, which is what the form
    #: does. Somebody migrating a spreadsheet may want to match its column.
    name: str | None = Field(default=None, max_length=60)
    kind: str = "text"
    choices: list[str] | None = None
    help: str | None = None
    required: bool = False
    position: int = 0

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, value: str) -> str:
        if value not in KINDS:
            raise ValueError(f"Choose one of: {', '.join(KINDS)}")
        return value


class CustomFieldPatch(BaseModel):
    """What may be changed after the fact.

    Not ``name`` and not ``record_type``: both decide where values are stored,
    and moving that after values exist orphans them.
    """

    label: str | None = Field(default=None, min_length=1, max_length=120)
    kind: str | None = None
    choices: list[str] | None = None
    help: str | None = None
    required: bool | None = None
    position: int | None = None
    is_active: bool | None = None

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, value: str | None) -> str | None:
        if value is not None and value not in KINDS:
            raise ValueError(f"Choose one of: {', '.join(KINDS)}")
        return value


def _key_from(label: str) -> str:
    """A storage key from a label: ``Ministry file no.`` becomes ``ministry_file_no``."""
    key = re.sub(r"[^a-z0-9]+", "_", label.strip().lower()).strip("_")
    return key[:60] or "field"


def _check_record_type(record_type: str) -> None:
    if record_type not in forms.LAYOUTS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"There is no form called {record_type!r}. "
                f"Available: {', '.join(sorted(forms.LAYOUTS))}."
            ),
        )


def _check_free(session: DbSession, record_type: str, name: str) -> None:
    """The name must clash with neither a platform field nor another custom one."""
    layout = forms.get_layout(record_type)
    if layout is not None and name in forms.field_index(layout):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=(
                f"{name!r} is already a field on this form. Give yours a different "
                "name — two fields with one name means one of them is never the "
                "one you typed into."
            ),
        )
    existing = session.scalar(
        select(CustomField).where(
            CustomField.record_type == record_type, CustomField.name == name
        )
    )
    if existing is not None:
        state = "already on this form" if existing.is_active else "retired but still on this form"
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"A field called {name!r} is {state} ({existing.label!r}).",
        )


@router.get(
    "",
    response_model=list[CustomFieldRead],
    summary="Fields this institution has added",
    description=(
        "Every custom field, or those on one form. Retired fields are left "
        "out unless `include_retired` is set — they are still on records and "
        "still in exports, they are simply no longer offered."
    ),
)
def list_custom_fields(
    session: DbSession,
    user: CurrentUser,
    record_type: Annotated[str | None, Query()] = None,
    include_retired: Annotated[bool, Query()] = False,
) -> list[CustomFieldRead]:
    statement = select(CustomField)
    if record_type:
        statement = statement.where(CustomField.record_type == record_type)
    if not include_retired:
        statement = statement.where(CustomField.is_active.is_(True))
    rows = session.scalars(
        statement.order_by(CustomField.record_type, CustomField.position, CustomField.label)
    ).all()
    return [CustomFieldRead.model_validate(row) for row in rows]


@router.post(
    "",
    response_model=CustomFieldRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a field to a form",
    description=(
        "The field appears immediately on the record card, in the edit form, "
        "in the spreadsheet importer's column list and in the tray, because "
        "all four read the same description of the form."
    ),
    responses={409: {"description": "That name is already a field on this form"}},
)
def create_custom_field(
    payload: CustomFieldWrite, session: DbSession, request: Request, user: RequireFormAdmin
) -> CustomFieldRead:
    _check_record_type(payload.record_type)
    name = _key_from(payload.name or payload.label)
    _check_free(session, payload.record_type, name)

    if payload.kind == "select" and not payload.choices:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A dropdown needs at least one choice to offer.",
        )

    field = CustomField(
        record_type=payload.record_type,
        name=name,
        label=payload.label.strip(),
        kind=payload.kind,
        choices=[choice.strip() for choice in payload.choices] if payload.choices else None,
        help=payload.help,
        required=payload.required,
        position=payload.position,
    )
    session.add(field)
    session.flush()
    activity.log(
        session,
        action=ActivityAction.CREATE,
        user=user,
        resource_label=field.label,
        summary=f"Added the field {field.label!r} to the {payload.record_type} form",
        request=request,
    )
    return CustomFieldRead.model_validate(field)


@router.patch(
    "/{field_id}",
    response_model=CustomFieldRead,
    summary="Change a field",
    description=(
        "The label, help text, order, choices and whether it is required can "
        "all change. Its storage name cannot: values already written are "
        "filed under it."
    ),
)
def update_custom_field(
    field_id: uuid.UUID,
    payload: CustomFieldPatch,
    session: DbSession,
    request: Request,
    user: RequireFormAdmin,
) -> CustomFieldRead:
    field = session.get(CustomField, field_id)
    if field is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No such field")

    changes = payload.model_dump(exclude_unset=True)
    if changes.get("kind") == "select" and not (changes.get("choices") or field.choices):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A dropdown needs at least one choice to offer.",
        )
    for key, value in changes.items():
        setattr(field, key, value)
    session.add(field)
    session.flush()
    activity.log(
        session,
        action=ActivityAction.UPDATE,
        user=user,
        resource_label=field.label,
        summary=f"Changed the field {field.label!r} on the {field.record_type} form",
        request=request,
    )
    return CustomFieldRead.model_validate(field)


@router.delete(
    "/{field_id}",
    response_model=Message,
    summary="Retire a field, or erase it",
    description=(
        "By default the field is **retired**: forms stop offering it, and "
        "every value already recorded stays on its record and in every "
        "export. Pass `erase_values=true` to delete the field and strip its "
        "values from every record — that cannot be undone, and the reply "
        "says how many records it changed."
    ),
)
def delete_custom_field(
    field_id: uuid.UUID,
    session: DbSession,
    request: Request,
    user: RequireFormAdmin,
    erase_values: Annotated[bool, Query()] = False,
) -> Message:
    field = session.get(CustomField, field_id)
    if field is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No such field")

    label, name, record_type = field.label, field.name, field.record_type

    if not erase_values:
        field.is_active = False
        session.add(field)
        activity.log(
            session,
            action=ActivityAction.UPDATE,
            user=user,
            resource_label=label,
            summary=f"Retired the field {label!r} on the {record_type} form",
            request=request,
        )
        return Message(
            detail=(
                f"{label!r} has been retired. It is off the form; every value "
                "already recorded is still on its record and in exports."
            )
        )

    model = _RECORDS.get(record_type)
    touched = 0
    if model is not None:
        rows = session.scalars(
            select(model).where(model.metadata_json.has_key(name))  # noqa: W601
        ).all()
        for row in rows:
            values = dict(row.metadata_json or {})
            values.pop(name, None)
            row.metadata_json = values
            flag_modified(row, "metadata_json")
            touched += 1

    session.delete(field)
    activity.log(
        session,
        action=ActivityAction.DELETE,
        user=user,
        resource_label=label,
        summary=(
            f"Deleted the field {label!r} from the {record_type} form "
            f"and erased its values from {touched} record(s)"
        ),
        request=request,
    )
    return Message(
        detail=(
            f"{label!r} is gone, and its value was erased from {touched} "
            f"record{'' if touched == 1 else 's'}."
        )
    )
