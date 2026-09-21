import 'dart:async';

import 'package:flet/flet.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

/// No camera is created until active is explicitly true. Images never leave
/// MobileScanner; only a single decoded QR text crosses the Flet bridge.
class QRScannerControl extends StatefulWidget {
  final Control control;
  const QRScannerControl({super.key, required this.control});

  @override
  State<QRScannerControl> createState() => _QRScannerControlState();
}

class _QRScannerControlState extends State<QRScannerControl>
    with WidgetsBindingObserver {
  MobileScannerController? _camera;
  StreamSubscription<BarcodeCapture>? _subscription;
  Future<void>? _nativeStart;
  bool _finished = false;
  bool _starting = false;
  bool _foreground = true;
  String? _error;

  bool get _active => widget.control.getBool('active', false)!;
  bool get _supported =>
      !kIsWeb && defaultTargetPlatform == TargetPlatform.android;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    WidgetsBinding.instance.addPostFrameCallback((_) => _syncCamera());
  }

  @override
  void didUpdateWidget(covariant QRScannerControl oldWidget) {
    super.didUpdateWidget(oldWidget);
    WidgetsBinding.instance.addPostFrameCallback((_) => _syncCamera());
  }

  Future<void> _syncCamera() async {
    if (!mounted) return;
    if (!_active || _finished || !_foreground) {
      await _stop();
      return;
    }
    if (!_supported) {
      _fail('unsupported_platform');
      return;
    }
    if (_starting || _camera?.value.isRunning == true) return;
    _starting = true;
    try {
      if (_camera == null) {
        _camera = MobileScannerController(
          autoStart: false,
          formats: const [BarcodeFormat.qrCode],
          detectionSpeed: DetectionSpeed.noDuplicates,
          returnImage: false,
          facing: CameraFacing.back,
        );
        _subscription = _camera!.barcodes.listen(_detected);
        setState(() {});
        // The scanner widget must mount before controller.start().
        await WidgetsBinding.instance.endOfFrame;
      }
      if (!mounted || !_active || _finished || !_foreground) return;
      _nativeStart = _camera!.start();
      await _nativeStart;
      // The permission dialog may outlive the Python route or cancellation.
      if (!mounted || !_active || _finished || !_foreground) await _stop();
      final error = _camera!.value.error;
      if (mounted && _active && !_finished && error != null) {
        _fail(
          error.errorCode == MobileScannerErrorCode.permissionDenied
              ? 'permission_denied'
              : 'camera_unavailable',
        );
      }
    } on MobileScannerException catch (error) {
      if (mounted && _active && !_finished) {
        _fail(
          error.errorCode == MobileScannerErrorCode.permissionDenied
              ? 'permission_denied'
              : 'camera_unavailable',
        );
      }
    } catch (_) {
      if (mounted && _active && !_finished) _fail('camera_error');
    } finally {
      _starting = false;
    }
  }

  Future<void> _stop() async {
    try {
      await _camera?.stop();
    } catch (_) {
      // Disposal also releases native resources, including an opening camera.
    }
  }

  Future<void> _detected(BarcodeCapture capture) async {
    if (!mounted || !_active || _finished || !_foreground) return;
    for (final barcode in capture.barcodes) {
      final text = barcode.rawValue;
      if (text == null || text.trim().isEmpty) continue;
      _finished = true; // Lock synchronously before awaiting camera shutdown.
      await _stop();
      if (mounted && _active) widget.control.triggerEvent('scan', text);
      return;
    }
  }

  void _fail(String code) {
    if (_finished || !mounted) return;
    _finished = true;
    _error = code;
    unawaited(_stop());
    widget.control.triggerEvent('error', code);
    setState(() {});
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _foreground = state == AppLifecycleState.resumed;
    // The permission prompt emits inactive/resumed before start() completes.
    // Reconcile again at the end of start(), without opening a second camera.
    unawaited(_syncCamera());
  }

  @override
  void dispose() {
    _finished = true;
    WidgetsBinding.instance.removeObserver(this);
    unawaited(_subscription?.cancel());
    final camera = _camera;
    if (camera != null) unawaited(_release(camera, _nativeStart));
    super.dispose();
  }

  Future<void> _release(
    MobileScannerController camera,
    Future<void>? pendingStart,
  ) async {
    // Wait for a pending permission/start operation before disposing. Otherwise
    // a late native start can acquire the camera *after* disposal ran.
    try {
      await pendingStart;
    } catch (_) {}
    await camera.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return LayoutControl(
      control: widget.control,
      child: ClipRRect(
        borderRadius: BorderRadius.circular(16),
        child: ColoredBox(
          color: const Color(0xff17181c),
          child: _camera != null && _active && _error == null
              ? Stack(
                  fit: StackFit.expand,
                  children: [
                    MobileScanner(
                      controller: _camera,
                      errorBuilder: (context, error) => const Center(
                        child: Icon(
                          Icons.videocam_off_outlined,
                          color: Colors.white70,
                          size: 40,
                        ),
                      ),
                    ),
                    IgnorePointer(
                      child: Center(
                        child: Container(
                          width: 210,
                          height: 210,
                          decoration: BoxDecoration(
                            border: Border.all(color: Colors.white70, width: 2),
                            borderRadius: BorderRadius.circular(20),
                          ),
                        ),
                      ),
                    ),
                  ],
                )
              : const Center(
                  child: Icon(
                    Icons.qr_code_scanner,
                    color: Colors.white70,
                    size: 40,
                  ),
                ),
        ),
      ),
    );
  }
}
