"""QR codes and the public pages they open.

Every artifact, site and project carries a stable ``public_token``. A printed
label encodes a short URL containing that token, so the label survives the
record being renamed or renumbered, and a scan does not expose a database
identifier that could be iterated over.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CurrentUserOptional, DbSession
from app.core.permissions import can_view
from app.models.artifact import Artifact
from app.models.enums import ResourceType
from app.models.project import Project
from app.models.site import Site
from app.services import qrcodes, records

router = APIRouter(tags=["Labels & QR codes"])

#: Path segment → the record it addresses.
LABELLED: dict[str, tuple[type[Any], ResourceType, str]] = {
    "artifacts": (Artifact, ResourceType.ARTIFACT, "Artifact"),
    "sites": (Site, ResourceType.SITE, "Site"),
    "projects": (Project, ResourceType.PROJECT, "Project"),
}


class LabelInfo(BaseModel):
    """What a label needs, for a client that renders its own."""

    id: uuid.UUID
    resource_type: ResourceType
    label: str
    public_token: str
    #: The address encoded in the QR code.
    url: str
    qr_image_url: str


def _resolve(kind: str) -> tuple[type[Any], ResourceType, str]:
    entry = LABELLED.get(kind)
    if entry is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=f"Labels are not available for {kind!r}; expected one of {', '.join(LABELLED)}",
        )
    return entry


@router.get(
    "/{kind}/{record_id}/label",
    response_model=LabelInfo,
    summary="Label details for a record",
    description=(
        "The token, the URL a scan opens, and where to fetch the QR image. "
        "Useful for a client laying out its own label sheet."
    ),
)
def read_label(
    kind: str, record_id: uuid.UUID, session: DbSession, user: CurrentUserOptional
) -> LabelInfo:
    model, resource_type, name = _resolve(kind)
    record = records.get_or_404(session, model, record_id, name)
    if not can_view(session, user, record, resource_type):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{name} not found")

    return LabelInfo(
        id=record.id,
        resource_type=resource_type,
        label=records.label_for(record) or str(record.id),
        public_token=record.public_token,
        url=qrcodes.public_url(resource_type, record.public_token),
        qr_image_url=f"/api/v1/{kind}/{record.id}/qr.png",
    )


@router.get(
    "/{kind}/{record_id}/qr.png",
    summary="QR code image for a record",
    description=(
        "A PNG suitable for printing on a finds bag, a site marker or a folder "
        "cover.\n\n"
        "`size` controls the pixel size of each module, so a larger value "
        "prints more crisply. Labels use higher error correction by default, "
        "which keeps the code readable when it is scuffed, damp or partly "
        "obscured by a scale bar."
    ),
    response_class=Response,
    responses={200: {"content": {"image/png": {}}, "description": "The QR code"}},
)
def read_qr_code(
    kind: str,
    record_id: uuid.UUID,
    session: DbSession,
    user: CurrentUserOptional,
    size: Annotated[int, Query(ge=2, le=40, description="Pixels per module")] = 10,
    for_label: Annotated[bool, Query(description="Higher error correction, for print")] = True,
) -> Response:
    model, resource_type, name = _resolve(kind)
    record = records.get_or_404(session, model, record_id, name)
    if not can_view(session, user, record, resource_type):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{name} not found")

    png = qrcodes.render_for_record(
        resource_type, record.public_token, box_size=size, for_label=for_label
    )
    return Response(
        content=png,
        media_type="image/png",
        headers={
            # The token never changes, so the image never changes.
            "Cache-Control": "public, max-age=86400",
            "Content-Disposition": f'inline; filename="{kind}-{record_id}.png"',
        },
    )


@router.get(
    "/scan/{kind}/{token}",
    summary="Resolve a scanned label",
    description=(
        "Looks a record up by the token printed on its label. Access is "
        "checked exactly as for the record's own endpoint — scanning a label "
        "reveals nothing the scanner could not already see."
    ),
    responses={404: {"description": "No such token, or not visible to you"}},
)
def resolve_scan(
    kind: str, token: str, session: DbSession, user: CurrentUserOptional
) -> dict[str, Any]:
    model, resource_type, name = _resolve(kind)

    record = session.scalar(select(model).where(model.public_token == token))
    if record is None or not can_view(session, user, record, resource_type):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{name} not found")

    return {
        "id": str(record.id),
        "resource_type": resource_type.value,
        "label": records.label_for(record),
        "api_url": f"/api/v1/{kind}/{record.id}",
    }
