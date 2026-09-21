"""Camera access is opt-in: mount QRScanner only after an explicit scan action."""

from typing import Optional

import flet as ft

__all__ = ["QRScanner"]


@ft.control("ChargeGridQRScanner")
class QRScanner(ft.LayoutControl):
    """One-shot, on-device QR reader.

    Instantiate with ``active=True`` only after the user taps Scan. ``on_scan``
    receives the decoded text in ``event.data`` exactly once for this instance.
    Set active=False and update/remove the control when cancelling. Disposing
    the widget also releases the camera. A new scan needs a new instance.

    ``on_error`` receives a stable code, never camera frames or native details:
    unsupported_platform, permission_denied, camera_unavailable, camera_error.
    Web intentionally uses the application's paste-code fallback (no CDN).
    """

    active: bool = False
    on_scan: Optional[ft.ControlEventHandler["QRScanner"]] = None
    on_error: Optional[ft.ControlEventHandler["QRScanner"]] = None
