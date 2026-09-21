# ChargeGrid QR scanner

Local extension for **Flet 1.0.0 / Android**, backed by
**mobile_scanner 7.4.2** and bundled ML Kit. No image upload and no network
service is used to decode the QR. Camera is rear-facing, QR-only, one-shot.

## Integration

Install this directory as a local Python dependency when packaging the app.
Its wheel includes both `chargegrid_scanner` and the Flutter extension under
`flutter/chargegrid_scanner`, which Flet's packaging step discovers.

```python
from chargegrid_scanner import QRScanner

# Only in the explicit "Escanear QR" handler, never at page load:
scanner = QRScanner(
    active=True,
    width=300,
    height=320,
    on_scan=on_scan,
    on_error=on_error,
)
```

Mount the control inside a closable dialog/screen. `on_scan` receives the exact
decoded text in `event.data`; validate this as untrusted data in the application
and API before claiming ownership. The camera stops **before** the scan event is
delivered. No automatic request to the ownership API is made by this extension.

In every cancel/dismiss/back handler, set `scanner.active = False`, update the
page and remove the scanner/close the dialog. Widget disposal also releases the
camera, including a permission prompt that completes after the dialog closes.
Create a **new** scanner instance to retry after a scan/error. Reusing a finished
instance intentionally cannot reopen the camera or emit a second result.

`active` defaults to `False`, so constructing an inactive control does not request
permission. The native lifecycle observer stops the camera while the application
is inactive and resumes an unfinished, active scan on foregrounding.

`on_error` emits one of these codes without native details or QR contents:

- `permission_denied`: provide guidance to grant Camera permission in Settings.
- `camera_unavailable` / `camera_error`: offer a new attempt and paste-code fallback.
- `unsupported_platform`: offer paste-code fallback.

## Build requirements

- Flet 1.0.0 and Flutter >=3.35 / Dart >=3.9 (validated with Flutter 3.44.8).
- Include the local Python package in the app build dependency list. Rebuild the
  Flutter APK after Dart changes; Python hot reload cannot install an extension.
- Android `android.permission.CAMERA`. The dependency declares this in its Android
  manifest; the host can additionally declare Flet's `camera` permission.
- Keep ML Kit bundled (default). **Do not** enable
  `dev.steenbakker.mobile_scanner.useUnbundled=true`, which downloads its model.
- Stock `flet run --web` does not contain this custom extension. The host must not
  mount the scanner in that preview: use the same validated paste-code form there.
- Web camera scanning is intentionally disabled; mobile_scanner's web decoder
  can download a JavaScript library. This avoids CDN availability/privacy coupling.
- iOS/macOS/Linux/Windows camera scanning is not enabled in this implementation.

## Tests and limits

From `src/flutter/chargegrid_scanner`:

```sh
flutter pub get
flutter analyze --no-pub
flutter test --no-pub
```

Eight widget tests exercise the actual extension and MobileScanner controller
against a fake native-camera boundary: no implicit start, QR-only/no image export,
one-shot detection, empty detections, cancellation/late events, denied permission,
disposal during permission prompt, lifecycle stop/resume and unsupported platform.
The wheel was built and its Dart assets verified. These are **not a physical
camera test**; no Android phone was available during implementation. APK build and
real-device scanning remain integration checks for the host app.

Primary references:

- [Flet extension structure](https://flet.dev/docs/extend/user-extensions/)
- [Flet's official extension packaging example](https://github.com/flet-dev/flet-geolocator/blob/main/pyproject.toml)
- [mobile_scanner configuration and lifecycle](https://pub.dev/packages/mobile_scanner)

The code was also checked against the locally installed Flet 1.0.0 and
mobile_scanner 7.4.2 sources, including controller start/error/disposal behavior.
