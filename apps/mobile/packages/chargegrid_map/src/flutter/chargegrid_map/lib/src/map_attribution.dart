import 'dart:async';

import 'package:flutter/material.dart';
import 'package:pointer_interceptor/pointer_interceptor.dart';
import 'package:url_launcher/url_launcher.dart';

/// Show attribution before collapsing it; licence links always remain reachable.
class MapAttribution extends StatefulWidget {
  const MapAttribution({super.key, this.interaction = 0});
  final int interaction;

  @override
  State<MapAttribution> createState() => _MapAttributionState();
}

class _MapAttributionState extends State<MapAttribution> {
  bool _expanded = true;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _timer = Timer(const Duration(seconds: 5), _collapse);
  }

  @override
  void didUpdateWidget(covariant MapAttribution oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.interaction != widget.interaction) _collapse();
  }

  void _collapse() {
    _timer?.cancel();
    if (mounted && _expanded) setState(() => _expanded = false);
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return PointerInterceptor(
      child: Material(
        color: Theme.of(context).colorScheme.surface.withValues(alpha: .94),
        borderRadius: BorderRadius.circular(8),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (_expanded) ...[
              const SizedBox(width: 5),
              for (final entry in const {
                '© OpenMapTiles': 'https://openmaptiles.org/',
                '© OpenStreetMap': 'https://www.openstreetmap.org/copyright',
              }.entries)
                TextButton(
                  onPressed: () => launchUrl(Uri.parse(entry.value)),
                  style: TextButton.styleFrom(
                    foregroundColor: Theme.of(context).colorScheme.onSurface,
                    minimumSize: Size.zero,
                    padding: const EdgeInsets.symmetric(
                      horizontal: 4,
                      vertical: 6,
                    ),
                    tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                    textStyle: const TextStyle(
                      fontSize: 10,
                      fontFamily: 'Inter',
                    ),
                  ),
                  child: Text(entry.key),
                ),
            ],
            IconButton(
              tooltip: _expanded
                  ? 'Recolher créditos do mapa'
                  : 'Créditos e licenças do mapa',
              constraints: const BoxConstraints.tightFor(width: 32, height: 32),
              padding: EdgeInsets.zero,
              iconSize: 17,
              icon: Icon(
                _expanded ? Icons.close_rounded : Icons.info_outline_rounded,
              ),
              onPressed: () {
                _timer?.cancel();
                setState(() => _expanded = !_expanded);
              },
            ),
          ],
        ),
      ),
    );
  }
}
