import 'dart:async';
import 'dart:convert';

import 'package:flet/flet.dart';
import 'package:flutter/material.dart';
import 'package:maplibre/maplibre.dart';
import 'map_attribution.dart';
import 'runtime_stub.dart' if (dart.library.js_interop) 'runtime_web.dart';

/// Marker colours: demonstration stations (presentation mode, ``tone: 'demo'``) are white with
/// dark ink; every real station keeps the brand red with white ink.
({Color fill, Color ink, BoxBorder? edge}) markerPalette(Object? tone) =>
    tone == 'demo'
    ? (
        fill: Colors.white,
        ink: const Color(0xff111111),
        edge: Border.all(color: const Color(0xffcfd4d8)),
      )
    : (fill: const Color(0xffd72b32), ink: Colors.white, edge: null);

class VectorMapControl extends StatefulWidget {
  const VectorMapControl({super.key, required this.control});
  final Control control;
  @override
  State<VectorMapControl> createState() => _VectorMapControlState();
}

class _VectorMapControlState extends State<VectorMapControl> {
  MapController? _map;
  int _revision = -1;
  int _retry = 0;
  String _style = '';
  bool _ready = false;
  bool _failed = false;
  bool _userMoved = false;
  bool _runtimeReady = false;
  int _interaction = 0;
  Timer? _timeout;

  double number(String key, double fallback) =>
      (widget.control.get(key) as num?)?.toDouble() ?? fallback;
  Geographic get center => Geographic(
    lon: number('longitude', -46.6333),
    lat: number('latitude', -23.5505),
  );
  String get style => widget.control.getString('style_json', '')!;

  @override
  void initState() {
    super.initState();
    _style = style;
    _revision = widget.control.getInt('camera_revision', 0)!;
    _watchLoad();
    _loadRuntime();
  }

  Future<void> _loadRuntime() async {
    try {
      await prepareRuntime(
        widget.control.backend.getAssetSource('maps/maplibre-gl.js').path,
        widget.control.backend.getAssetSource('maps/maplibre-gl.css').path,
      );
      if (mounted) setState(() => _runtimeReady = true);
    } catch (_) {
      if (mounted) setState(() => _failed = true);
    }
  }

  void _watchLoad() {
    _timeout?.cancel();
    _timeout = Timer(const Duration(seconds: 18), () {
      if (mounted && !_ready) setState(() => _failed = true);
    });
  }

  @override
  void didUpdateWidget(covariant VectorMapControl oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (_style != style) {
      _style = style;
      _ready = false;
      _watchLoad();
      _map?.setStyle(_style);
    }
    final revision = widget.control.getInt('camera_revision', 0)!;
    if (_revision != revision) {
      _revision = revision;
      _userMoved = false;
      unawaited(_map?.moveCamera(center: center, zoom: number('zoom', 13)));
    }
  }

  void event(MapEvent event) {
    if (event is MapEventStartMoveCamera &&
        event.reason == CameraChangeReason.apiGesture) {
      _userMoved = true;
      if (mounted) setState(() => _interaction++);
    }
    if (event is MapEventCameraIdle && _userMoved && _map?.camera != null) {
      _userMoved = false;
      final camera = _map!.camera!;
      widget.control.triggerEvent(
        'camera',
        jsonEncode({
          'latitude': camera.center.lat,
          'longitude': camera.center.lon,
          'zoom': camera.zoom,
        }),
      );
    }
  }

  List<Marker> markers() {
    final rows = (widget.control.get('markers') as List? ?? [])
        .whereType<Map>()
        .toList();
    final selected = widget.control.getString('selected');
    rows.sort(
      (a, b) =>
          (a['id'] == selected ? 1 : 0).compareTo(b['id'] == selected ? 1 : 0),
    );
    return rows.map((row) {
      final name = row['name']?.toString() ?? 'Estação de recarga';
      final active = row['id'] == selected;
      final (:fill, :ink, :edge) = markerPalette(row['tone']);
      final width = (38 + name.length * 6.3).clamp(118, 205).toDouble();
      return Marker(
        point: Geographic(
          lon: (row['longitude'] as num).toDouble(),
          lat: (row['latitude'] as num).toDouble(),
        ),
        size: Size(width, active ? 52 : 48),
        alignment: Alignment.bottomCenter,
        child: Semantics(
          button: true,
          label: '$name · ${row['status'] ?? ''}',
          child: GestureDetector(
            onTap: () =>
                widget.control.triggerEvent('select', row['id'].toString()),
            child: Column(
              children: [
                Container(
                  height: active ? 42 : 38,
                  padding: const EdgeInsets.symmetric(horizontal: 10),
                  decoration: BoxDecoration(
                    color: fill,
                    border: edge,
                    borderRadius: BorderRadius.circular(8),
                    boxShadow: [
                      BoxShadow(
                        color: Colors.black.withValues(
                          alpha: active ? .30 : .18,
                        ),
                        blurRadius: 10,
                        offset: const Offset(0, 3),
                      ),
                    ],
                  ),
                  child: Row(
                    children: [
                      Icon(Icons.ev_station_rounded, color: ink, size: 17),
                      const SizedBox(width: 6),
                      Expanded(
                        child: Text(
                          name,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(
                            fontFamily: 'InterBold',
                            color: ink,
                            fontSize: 11,
                            height: 1.2,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 4),
                Container(
                  width: 6,
                  height: 6,
                  decoration: BoxDecoration(
                    color: fill,
                    border: edge,
                    shape: BoxShape.circle,
                  ),
                ),
              ],
            ),
          ),
        ),
      );
    }).toList();
  }

  @override
  void dispose() {
    _timeout?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final interactive = widget.control.getBool('interactive', true)!;
    return LayoutControl(
      control: widget.control,
      child: Stack(
        fit: StackFit.expand,
        children: [
          if (_runtimeReady)
            MapLibreMap(
              key: ValueKey(_retry),
              options: MapOptions(
                initStyle: _style,
                initCenter: center,
                initZoom: number('zoom', 13),
                minZoom: 2,
                maxZoom: 19,
                maxPitch: 0,
                gestures: interactive
                    ? const MapGestures.all(rotate: false, pitch: false)
                    : const MapGestures.none(),
              ),
              onMapCreated: (controller) {
                _map = controller;
                unawaited(
                  controller.moveCamera(
                    center: center,
                    zoom: number('zoom', 13),
                  ),
                );
              },
              onStyleLoaded: (_) {
                if (!mounted) return;
                _timeout?.cancel();
                setState(() {
                  _ready = true;
                  _failed = false;
                });
                widget.control.triggerEvent('ready', '');
              },
              onEvent: event,
              children: [
                WidgetLayer(markers: markers(), allowInteraction: true),
              ],
            ),
          if (_ready)
            Positioned(
              left: 8,
              bottom: number('credit_bottom', 8),
              child: MapAttribution(interaction: _interaction),
            ),
          if (!_ready && !_failed)
            const Center(
              child: SizedBox(
                width: 22,
                height: 22,
                child: CircularProgressIndicator(strokeWidth: 2),
              ),
            ),
          if (_failed)
            Center(
              child: FilledButton.tonalIcon(
                icon: const Icon(Icons.refresh),
                label: const Text('Mapa indisponível · tentar novamente'),
                onPressed: () {
                  setState(() {
                    _failed = false;
                    _ready = false;
                    _retry++;
                  });
                  _watchLoad();
                  if (!_runtimeReady) _loadRuntime();
                },
              ),
            ),
        ],
      ),
    );
  }
}
