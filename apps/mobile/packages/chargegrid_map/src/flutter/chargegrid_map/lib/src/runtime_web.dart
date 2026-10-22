import 'dart:async';
import 'package:web/web.dart' as web;

Future<void>? _loading;

Future<void> prepareRuntime(String script, String stylesheet) {
  return _loading ??= _load(script, stylesheet).catchError((Object error) {
    _loading = null;
    throw error;
  });
}

Future<void> _load(String script, String stylesheet) async {
  final link = web.HTMLLinkElement()
    ..rel = 'stylesheet'
    ..href = stylesheet;
  web.document.head!.append(link);
  final element = web.HTMLScriptElement()..src = script;
  final loaded = element.onLoad.first;
  final failed = element.onError.first.then(
    (_) => throw StateError('Map runtime unavailable'),
  );
  web.document.head!.append(element);
  await Future.any([loaded, failed]).timeout(const Duration(seconds: 15));
  final settings = web.HTMLScriptElement()
    ..src = Uri.parse(script).resolve('map-runtime.js').toString();
  final configured = settings.onLoad.first;
  final settingsFailed = settings.onError.first.then(
    (_) => throw StateError('Map settings unavailable'),
  );
  web.document.head!.append(settings);
  await Future.any([
    configured,
    settingsFailed,
  ]).timeout(const Duration(seconds: 15));
}
