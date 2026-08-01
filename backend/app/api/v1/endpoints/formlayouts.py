"""Form layouts, served to the client.

A cataloguing card is described here and rendered there. The frontend asks
what fields a record has, what they are called, how they group and what fills
their dropdowns — and draws that, rather than carrying its own copy of the
answer that goes stale the moment the form changes.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentUserOptional, DbSession
from app.services import forms

router = APIRouter(prefix="/forms", tags=["Forms"])


@router.get(
    "/layouts",
    response_model=list[str],
    summary="Which record types have a layout",
)
def list_layouts() -> list[str]:
    return sorted(forms.LAYOUTS)


@router.get(
    "/layouts/{record_type}",
    summary="The form layout for a record type",
    description=(
        "Tabs, field groups, labels, types and help text for one record "
        "type, plus the value lists its dropdowns need.\n\n"
        "Value lists are resolved from the database, so a period added this "
        "morning appears in the dropdown this afternoon without a "
        "deployment. Pass `include_value_lists=false` to fetch the layout "
        "alone when they are already cached."
    ),
    responses={404: {"description": "No layout for that record type"}},
)
def read_layout(
    record_type: str,
    session: DbSession,
    user: CurrentUserOptional,
    include_value_lists: Annotated[bool, Query()] = True,
) -> dict[str, Any]:
    layout = forms.get_layout(record_type)
    if layout is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=(
                f"No layout for {record_type!r}. Available: " f"{', '.join(sorted(forms.LAYOUTS))}."
            ),
        )

    payload = layout.as_dict()
    payload["value_list_options"] = (
        forms.value_lists(session, layout.value_lists) if include_value_lists else {}
    )
    return payload


@router.get(
    "/layouts/{record_type}/fields",
    summary="A flat list of the fields on a layout",
    description=(
        "The same fields without the tab and group structure. This is what "
        "the spreadsheet importer maps columns onto, so a field on the form "
        "is a field a column can fill and there is no second list to keep in "
        "step."
    ),
)
def read_fields(record_type: str) -> list[dict[str, Any]]:
    layout = forms.get_layout(record_type)
    if layout is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"No layout for {record_type!r}")

    from dataclasses import asdict

    return [asdict(field) for field in forms.field_index(layout).values()]


@router.get(
    "/value-lists/{name}",
    summary="One value list",
    description="The options behind a dropdown, for a client refreshing one list.",
)
def read_value_list(
    name: str, session: DbSession, user: CurrentUserOptional
) -> list[dict[str, str]]:
    resolved = forms.value_lists(session, [name])
    if name not in resolved:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"No value list named {name!r}")
    return resolved[name]
