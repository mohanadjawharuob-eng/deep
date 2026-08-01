"""QR codes for physical labels.

A finds tray, a site marker and a project folder all end up with a printed
label. Scanning it should open that record in a browser.

The encoded URL points at the **frontend**, not at this API: a curator scanning
a label wants a page, not JSON. It carries the record's ``public_token`` rather
than its database id, so a label keeps working if the record is renumbered, and
so the printed code is not a database identifier anyone can iterate over.
"""

from __future__ import annotations

import io

import qrcode
from qrcode.constants import ERROR_CORRECT_M, ERROR_CORRECT_Q

from app.core.config import settings
from app.models.enums import ResourceType

#: Frontend route per record type. These must match the frontend's routing.
_ROUTES: dict[ResourceType, str] = {
    ResourceType.ARTIFACT: "a",
    ResourceType.SITE: "s",
    ResourceType.PROJECT: "p",
}


def public_url(resource_type: ResourceType, token: str) -> str:
    """The address a scan should open.

    Short by design: ``/a/<token>`` rather than ``/artifacts/<token>``. Fewer
    characters means a sparser QR code, which survives being printed small on a
    label and photographed in bad light at the trench edge.
    """
    route = _ROUTES.get(resource_type)
    if route is None:
        raise ValueError(f"No public route defined for {resource_type.value}")
    return f"{settings.FRONTEND_URL.rstrip('/')}/{route}/{token}"


def render_png(
    data: str,
    *,
    box_size: int = 10,
    border: int = 4,
    high_correction: bool = False,
) -> bytes:
    """Render a QR code as a PNG.

    ``high_correction`` raises redundancy from roughly 15% to 25%, which is
    worth the denser code for labels that will live in a finds tray and get
    scuffed, damp or partly covered by a scale bar.
    """
    code = qrcode.QRCode(
        version=None,  # chosen automatically from the payload length
        error_correction=ERROR_CORRECT_Q if high_correction else ERROR_CORRECT_M,
        box_size=box_size,
        # The quiet zone is not decoration: scanners need it to find the code.
        border=max(border, 4),
    )
    code.add_data(data)
    code.make(fit=True)

    image = code.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def render_for_record(
    resource_type: ResourceType, token: str, *, box_size: int = 10, for_label: bool = True
) -> bytes:
    """PNG for a record's public URL, ready to print."""
    return render_png(
        public_url(resource_type, token), box_size=box_size, high_correction=for_label
    )
