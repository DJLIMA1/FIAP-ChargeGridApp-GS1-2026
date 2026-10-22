import 'package:chargegrid_map/src/vector_map.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('demonstration stations get a white marker with dark ink', () {
    final palette = markerPalette('demo');
    expect(palette.fill, Colors.white);
    expect(palette.ink, const Color(0xff111111));
    expect(palette.edge, isNotNull);
  });

  test('real stations keep the brand red marker', () {
    for (final tone in [null, '', 'real', 42]) {
      final palette = markerPalette(tone);
      expect(palette.fill, const Color(0xffd72b32));
      expect(palette.ink, Colors.white);
      expect(palette.edge, isNull);
    }
  });
}
