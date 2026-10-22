import 'package:chargegrid_map/src/map_attribution.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

Widget subject({int interaction = 0}) => MaterialApp(
  home: Scaffold(
    body: Center(child: MapAttribution(interaction: interaction)),
  ),
);

void main() {
  testWidgets(
    'shows credits for five seconds, then lets the user reopen them',
    (tester) async {
      await tester.pumpWidget(subject());
      expect(find.text('© OpenStreetMap'), findsOneWidget);
      expect(find.text('© OpenMapTiles'), findsOneWidget);
      await tester.pump(const Duration(seconds: 4));
      expect(find.text('© OpenStreetMap'), findsOneWidget);
      await tester.pump(const Duration(seconds: 1));
      expect(find.text('© OpenStreetMap'), findsNothing);
      await tester.tap(find.byTooltip('Créditos e licenças do mapa'));
      await tester.pump();
      expect(find.text('© OpenStreetMap'), findsOneWidget);
      await tester.pump(const Duration(seconds: 10));
      expect(find.text('© OpenStreetMap'), findsOneWidget);
      await tester.tap(find.byTooltip('Recolher créditos do mapa'));
      await tester.pump();
      expect(find.text('© OpenStreetMap'), findsNothing);
    },
  );

  testWidgets(
    'map interaction collapses credits and keeps the licence button reachable',
    (tester) async {
      await tester.pumpWidget(subject());
      await tester.pumpWidget(subject(interaction: 1));
      expect(find.text('© OpenStreetMap'), findsNothing);
      expect(find.byTooltip('Créditos e licenças do mapa'), findsOneWidget);
      await tester.tap(find.byTooltip('Créditos e licenças do mapa'));
      await tester.pump();
      expect(find.text('© OpenMapTiles'), findsOneWidget);
      await tester.pumpWidget(subject(interaction: 2));
      expect(find.text('© OpenMapTiles'), findsNothing);
    },
  );
}
