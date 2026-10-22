"""Build the hosted Flet web client with ChargeGrid's local vector-map extension.

Run with the repository venv, then set FLET_WEB_PATH to the printed directory
when using ft.run(..., view=None). Packaged Android/iOS builds include the same
extension through apps/mobile/pyproject.toml.
"""
import os
import shutil
import subprocess
from importlib.util import find_spec
from pathlib import Path

import flet_web

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / 'apps/mobile/.flet/vector-client'
OUTPUT = PROJECT / 'build/web'


def build():
    flutter = os.getenv('FLUTTER_BIN') or shutil.which('flutter')
    if not flutter:
        candidates = sorted((Path.home() / 'flutter').glob('*/bin/flutter'))
        flutter = str(candidates[-1]) if candidates else None
    if not flutter:
        raise SystemExit('Flutter SDK required. Set FLUTTER_BIN to its bin/flutter executable.')
    (PROJECT / 'lib').mkdir(parents=True, exist_ok=True)
    (PROJECT / 'web').mkdir(exist_ok=True)
    source = ROOT / 'apps/mobile/packages/chargegrid_map/src/flutter/chargegrid_map'
    geolocator = Path(next(iter(find_spec('flutter.flet_geolocator').submodule_search_locations)))
    (PROJECT / 'pubspec.yaml').write_text(f'''name: chargegrid_vector_client
environment:
  sdk: '>=3.12.0 <4.0.0'
dependencies:
  flutter:
    sdk: flutter
  flutter_web_plugins:
    sdk: flutter
  flet: 1.0.0
  flet_geolocator:
    path: {geolocator}
  chargegrid_map:
    path: {source}
dependency_overrides:
  flet: 1.0.0
flutter:
  uses-material-design: true
''')
    (PROJECT / 'lib/main.dart').write_text('''import 'package:flutter/material.dart';
import 'package:flutter_web_plugins/url_strategy.dart';
import 'package:flet/flet.dart';
import 'package:chargegrid_map/chargegrid_map.dart' as maps;
import 'package:flet_geolocator/flet_geolocator.dart' as location;
void main() {
  usePathUrlStrategy();
  FletDeepLinkingBootstrap.install();
  final extensions = [maps.Extension(), location.Extension()];
  for (final extension in extensions) { extension.ensureInitialized(); }
  runApp(FletApp(pageUrl: Uri.base.toString(), assetsDir: getAssetsDir(),
    forcePyodide: false, extensions: extensions));
}
''')
    baseline = Path(flet_web.__file__).parent / 'web'
    index = (baseline / 'index.html').read_text()
    (PROJECT / 'web/index.html').write_text(index)
    (PROJECT / 'web/flutter_bootstrap.js').write_text('''{{flutter_js}}
{{flutter_build_config}}
window.addEventListener('flutter-first-frame', () => document.getElementById('loading')?.remove(), {once: true});
const config = {entrypointBaseUrl: flet.entrypointBaseUrl, assetBase: flet.assetBase};
_flutter.loader.load({config, onEntrypointLoaded: async initializer => {
  const engine = await initializer.initializeEngine(config);
  flet.flutterApp = await engine.runApp();
  flet.flutterAppResolve(flet.flutterApp);
}});
''')
    subprocess.run([flutter, 'build', 'web', '--release', '--no-tree-shake-icons'], cwd=PROJECT, check=True)
    for name in ('python.js', 'python-worker.js', 'manifest.json', 'favicon.png'):
        shutil.copy2(baseline / name, OUTPUT / name)
    print(f'FLET_WEB_PATH={OUTPUT}')


if __name__ == '__main__':
    build()
