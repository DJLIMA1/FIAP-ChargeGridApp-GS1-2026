import 'dart:async';

import 'package:chargegrid_scanner/src/qr_scanner.dart';
import 'package:flet/flet.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

class Backend implements FletBackend {
  final events = <(String, dynamic)>[];
  @override
  void triggerControlEvent(Control control, String name, [dynamic data]) {
    events.add((name, data));
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

class Camera extends MobileScannerPlatform {
  final captures = StreamController<BarcodeCapture?>.broadcast();
  int starts = 0;
  int stops = 0;
  int disposes = 0;
  StartOptions? options;
  Completer<void>? gate;
  bool denied = false;
  @override
  Stream<BarcodeCapture?> get barcodesStream => captures.stream;
  @override
  Stream<TorchState> get torchStateStream => const Stream.empty();
  @override
  Stream<double> get zoomScaleStateStream => const Stream.empty();
  @override
  Widget buildCameraView() => const SizedBox.expand();
  @override
  Future<void> updateScanWindow(Rect? window) async {}
  @override
  Future<MobileScannerViewAttributes> start(StartOptions startOptions) async {
    starts++;
    options = startOptions;
    await gate?.future;
    if (denied) {
      throw const MobileScannerException(
        errorCode: MobileScannerErrorCode.permissionDenied,
      );
    }
    return const MobileScannerViewAttributes(
      cameraDirection: CameraFacing.back,
      currentTorchMode: TorchState.off,
      size: Size(640, 480),
    );
  }

  @override
  Future<void> stop() async {
    stops++;
  }

  @override
  Future<void> dispose() async {
    disposes++;
  }

  void emit(String? value) => captures.add(
    BarcodeCapture(
      barcodes: [Barcode(rawValue: value, format: BarcodeFormat.qrCode)],
    ),
  );
}

void main() {
  late Camera camera;
  late Backend backend;
  late Control control;
  late MobileScannerPlatform original;
  setUp(() {
    original = MobileScannerPlatform.instance;
    camera = Camera();
    MobileScannerPlatform.instance = camera;
    backend = Backend();
    control = Control(
      id: 5,
      type: 'ChargeGridQRScanner',
      backend: backend,
      properties: {'active': true, 'on_scan': true, 'on_error': true},
    );
  });
  tearDown(() async {
    MobileScannerPlatform.instance = original;
    debugDefaultTargetPlatformOverride = null;
    await camera.captures.close();
  });
  Future<void> mount(WidgetTester tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: SizedBox(
          width: 300,
          height: 320,
          child: QRScannerControl(
            key: const ValueKey('scanner'),
            control: control,
          ),
        ),
      ),
    );
    await tester.pump();
    await tester.pump();
  }

  testWidgets('inactive is camera-free; explicit activation opens QR only', (
    tester,
  ) async {
    control.properties['active'] = false;
    await mount(tester);
    expect(camera.starts, 0);
    control.properties['active'] = true;
    await mount(tester);
    expect(camera.starts, 1);
    expect(camera.options!.formats, [BarcodeFormat.qrCode]);
    expect(camera.options!.returnImage, false);
  });
  testWidgets('one scan stops camera and delivers text once', (tester) async {
    await mount(tester);
    camera.emit('chargegrid://claim/example');
    camera.emit('chargegrid://claim/duplicate');
    await tester.pump();
    expect(backend.events, [('scan', 'chargegrid://claim/example')]);
    expect(camera.stops, 1);
  });
  testWidgets('null/blank scan is ignored', (tester) async {
    await mount(tester);
    camera.emit(null);
    camera.emit(' ');
    await tester.pump();
    expect(backend.events, isEmpty);
    expect(camera.stops, 0);
  });
  testWidgets('cancel stops and rejects late camera events', (tester) async {
    await mount(tester);
    control.properties['active'] = false;
    await mount(tester);
    camera.emit('late');
    await tester.pump();
    expect(camera.stops, 1);
    expect(backend.events, isEmpty);
    await tester.pumpWidget(const SizedBox());
    await tester.pump();
    expect(camera.disposes, 1);
  });
  testWidgets('permission denial emits safe error code', (tester) async {
    camera.denied = true;
    await mount(tester);
    expect(backend.events, [('error', 'permission_denied')]);
  });
  testWidgets('dispose during permission prompt releases late camera', (
    tester,
  ) async {
    camera.gate = Completer<void>();
    await mount(tester);
    expect(camera.starts, 1);
    await tester.pumpWidget(const SizedBox());
    camera.gate!.complete();
    await tester.pump();
    expect(camera.disposes, 1);
    expect(backend.events, isEmpty);
  });
  testWidgets('background stops and foreground resumes unless finished', (
    tester,
  ) async {
    await mount(tester);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    await tester.pump();
    expect(camera.stops, 1);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pump();
    expect(camera.starts, 2);
    camera.emit('one');
    await tester.pump();
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pump();
    expect(camera.starts, 2);
  });
  testWidgets('unsupported platform never asks for camera', (tester) async {
    debugDefaultTargetPlatformOverride = TargetPlatform.linux;
    await mount(tester);
    expect(camera.starts, 0);
    expect(backend.events, [('error', 'unsupported_platform')]);
    debugDefaultTargetPlatformOverride = null;
  });
}
