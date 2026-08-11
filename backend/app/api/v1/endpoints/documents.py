"""Document upload and retrieval."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select

from app.api.deps import CurrentUser, CurrentUserOptional, DbSession
from app.core.config import settings
from app.core.permissions import can_delete, can_edit, visibility_filter
from app.models.enums import DocumentType, ResourceType
from app.models.media import Document
from app.models.user import User
from app.schemas.common import Message, Page
from app.schemas.media import DocumentDetail, DocumentSummary, DocumentUpdate
from app.services import attachments, records
from app.services import documents as document_service
from app.services.storage import CATEGORY_DOCUMENTS, storage

router = APIRouter(prefix="/documents", tags=["Documents"])

RESOURCE = ResourceType.DOCUMENT


def _summary(document: Document) -> DocumentSummary:
    return DocumentSummary.model_validate(document)


def _detail(session: DbSession, document: Document, user: User | None) -> DocumentDetail:
    payload = DocumentDetail.model_validate(document)
    payload.has_extracted_text = bool(document.extracted_text)
    payload.can_edit = can_edit(session, user, document, RESOURCE)
    payload.can_delete = can_delete(session, user, document, RESOURCE)
    return payload


@router.post(
    "",
    response_model=DocumentDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a document",
    description=(
        "Multipart upload for reports, permits, spreadsheets and field notes.\n\n"
        "The file type is checked against its own leading bytes as well as its "
        "extension, so a renamed file is refused. Archives and HTML are not "
        "accepted, and documents are always served back as downloads rather "
        "than rendered.\n\n"
        "Text-based formats have their contents indexed for search; PDF and "
        "Office extraction arrives with OCR in a later milestone."
    ),
    responses={
        413: {"description": "The file is larger than the configured limit"},
        422: {"description": "Unsupported type, contents do not match, or attached to nothing"},
    },
)
async def upload_document(
    session: DbSession,
    request: Request,
    user: CurrentUser,
    file: Annotated[UploadFile, File(description="The document")],
    title: Annotated[str | None, Form(max_length=300)] = None,
    description: Annotated[str | None, Form()] = None,
    document_type: Annotated[DocumentType | None, Form()] = None,
    author: Annotated[str | None, Form(max_length=300)] = None,
    document_date: Annotated[date | None, Form()] = None,
    language: Annotated[str | None, Form(max_length=10)] = None,
    tags: Annotated[str | None, Form(description="Comma-separated")] = None,
    publication_id: Annotated[uuid.UUID | None, Form()] = None,
    is_public: Annotated[bool, Form()] = False,
    project_id: Annotated[uuid.UUID | None, Form()] = None,
    site_id: Annotated[uuid.UUID | None, Form()] = None,
    artifact_id: Annotated[uuid.UUID | None, Form()] = None,
    context_id: Annotated[uuid.UUID | None, Form()] = None,
    museum_object_id: Annotated[uuid.UUID | None, Form()] = None,
) -> DocumentDetail:
    links = attachments.resolve_attachment(
        session,
        user,
        project_id=project_id,
        site_id=site_id,
        artifact_id=artifact_id,
        context_id=context_id,
        museum_object_id=museum_object_id,
    )

    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    data = bytearray()
    while chunk := await file.read(1024 * 1024):
        data.extend(chunk)
        if len(data) > max_bytes:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"That file is larger than the {settings.MAX_UPLOAD_SIZE_MB} MB limit",
            )
    payload = bytes(data)

    try:
        facts = document_service.inspect(payload, file.filename)
    except document_service.DocumentError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    stored = storage.save_bytes(payload, category=CATEGORY_DOCUMENTS, extension=facts.extension)

    document = Document(
        title=title or (file.filename or "Untitled document"),
        description=description,
        document_type=document_type or document_service.guess_type(facts.extension, file.filename),
        author=author or user.full_name,
        document_date=document_date,
        language=language,
        file_path=stored.path,
        original_filename=file.filename,
        mime_type=facts.mime_type,
        file_size=stored.size,
        checksum=stored.checksum,
        extracted_text=document_service.extract_text(payload, facts.extension),
        tags=[tag.strip() for tag in tags.split(",") if tag.strip()] if tags else None,
        publication_id=publication_id,
        researcher_id=user.id,
        is_public=is_public,
        owner_id=user.id,
        review_status=records.initial_review_status(user),
        **links,
    )
    session.add(document)
    session.flush()

    attachments.log_upload(
        session,
        record=document,
        resource_type=RESOURCE,
        user=user,
        request=request,
        summary=f"Uploaded {facts.description}: {document.title!r}",
    )
    session.flush()
    return _detail(session, document, user)


@router.get("", response_model=Page[DocumentSummary], summary="List documents")
def list_documents(
    session: DbSession,
    user: CurrentUserOptional,
    q: Annotated[
        str | None, Query(description="Match title, description, author or extracted text")
    ] = None,
    project_id: Annotated[uuid.UUID | None, Query()] = None,
    site_id: Annotated[uuid.UUID | None, Query()] = None,
    artifact_id: Annotated[uuid.UUID | None, Query()] = None,
    context_id: Annotated[uuid.UUID | None, Query()] = None,
    museum_object_id: Annotated[uuid.UUID | None, Query()] = None,
    document_type: Annotated[DocumentType | None, Query()] = None,
    author: Annotated[str | None, Query()] = None,
    sort: Annotated[str, Query(pattern="^-?(created_at|title|document_date)$")] = "-created_at",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[DocumentSummary]:
    statement = select(Document).where(visibility_filter(user, Document, RESOURCE))

    if q:
        pattern = f"%{q.lower()}%"
        statement = statement.where(
            or_(
                func.lower(Document.title).like(pattern),
                func.lower(Document.description).like(pattern),
                func.lower(Document.author).like(pattern),
                func.lower(Document.extracted_text).like(pattern),
                func.lower(func.array_to_string(Document.tags, " ")).like(pattern),
            )
        )
    if project_id is not None:
        statement = statement.where(Document.project_id == project_id)
    if site_id is not None:
        statement = statement.where(Document.site_id == site_id)
    if artifact_id is not None:
        statement = statement.where(Document.artifact_id == artifact_id)
    if context_id is not None:
        statement = statement.where(Document.context_id == context_id)
    if museum_object_id is not None:
        statement = statement.where(Document.museum_object_id == museum_object_id)
    if document_type is not None:
        statement = statement.where(Document.document_type == document_type)
    if author:
        statement = statement.where(func.lower(Document.author).like(f"%{author.lower()}%"))

    descending = sort.startswith("-")
    column = getattr(Document, sort.lstrip("-"))
    statement = statement.order_by(column.desc() if descending else column.asc())

    rows, total = records.paginate(session, statement, limit, offset)
    return Page[DocumentSummary](
        items=[_summary(row) for row in rows], total=total, limit=limit, offset=offset
    )


@router.get("/{document_id}", response_model=DocumentDetail, summary="Read a document's details")
def read_document(
    document_id: uuid.UUID, session: DbSession, user: CurrentUserOptional
) -> DocumentDetail:
    document = records.get_or_404(session, Document, document_id, "Document")
    attachments.require_readable(session, user, document, RESOURCE, "Document")
    return _detail(session, document, user)


@router.get(
    "/{document_id}/file",
    summary="Download a document",
    description=(
        "Always sent as an attachment, never rendered in the page. An uploaded "
        "file rendered inline from this origin could run script as the platform."
    ),
    response_class=FileResponse,
    responses={200: {"content": {"application/octet-stream": {}}, "description": "The document"}},
)
def download_document(
    document_id: uuid.UUID, session: DbSession, user: CurrentUserOptional
) -> FileResponse:
    document = records.get_or_404(session, Document, document_id, "Document")
    attachments.require_readable(session, user, document, RESOURCE, "Document")
    return attachments.serve(
        document.file_path,
        filename=document.original_filename or document.title,
        media_type=document.mime_type,
        inline=False,
    )


@router.patch("/{document_id}", response_model=DocumentDetail, summary="Update a document")
def update_document(
    document_id: uuid.UUID,
    payload: DocumentUpdate,
    session: DbSession,
    request: Request,
    user: CurrentUser,
) -> DocumentDetail:
    document = records.get_or_404(session, Document, document_id, "Document")
    attachments.require_editable(session, user, document, RESOURCE, "Document")

    changes = payload.model_dump(exclude_unset=True)
    before = records.apply_changes(document, changes)
    records.on_updated(session, document, RESOURCE, before=before, user=user, request=request)
    session.flush()
    return _detail(session, document, user)


@router.delete("/{document_id}", response_model=Message, summary="Delete a document")
def delete_document(
    document_id: uuid.UUID, session: DbSession, request: Request, user: CurrentUser
) -> Message:
    document = records.get_or_404(session, Document, document_id, "Document")
    attachments.require_readable(session, user, document, RESOURCE, "Document")
    if not can_delete(session, user, document, RESOURCE):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="You may not delete this document")

    label = document.title
    records.on_deleted(session, document, RESOURCE, user=user, request=request, label=label)
    session.delete(document)
    return Message(detail=f"Document {label!r} deleted")
