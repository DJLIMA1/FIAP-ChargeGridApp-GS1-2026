"""Build the Android APK with MapLibre Gradle and release JNI configuration.

Flet 1.0 has no settings.gradle customization hook. Apply this small addition
after either template pass, without changing the SDK or pub cache. MapLibre
Android 0.3.6 requests ktlint without declaring its version in the plugin.
Its dynamic JNI PlatformView implementations also need explicit R8 keep rules.
"""

import os
import sys
from pathlib import Path

from configure_mobile import configure_mobile
from flet_cli.commands.build_base import BaseBuildCommand
from verify_android_map_release import verify_apk

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = '    id("org.jlleitschuh.gradle.ktlint") version "13.1.0" apply false\n'


def build_then_verify(build, verify):
    try:
        build()
    except SystemExit as result:
        # Flet's successful cleanup also exits; do not skip APK validation.
        if result.code not in (None, 0):
            raise
    verify()


def main() -> None:
    configure_mobile()
    original = BaseBuildCommand.create_flutter_project
    build_environment = {}

    def create_flutter_project(self, second_pass=False):
        changed = original(self, second_pass=second_pass)
        build_environment.update(self.env)
        settings = self.flutter_dir / "android" / "settings.gradle.kts"
        source = settings.read_text()
        if PLUGIN not in source:
            anchor = '    id("dev.flutter.flutter-plugin-loader") version "1.0.0"\n'
            if anchor not in source:
                raise RuntimeError("Flet Android template changed; review Gradle plugin configuration.")
            settings.write_text(source.replace(anchor, anchor + PLUGIN, 1))
        app_dir = self.flutter_dir / "android" / "app"
        (app_dir / "chargegrid-map-rules.pro").write_text(
            (ROOT / "tools" / "android" / "map-proguard-rules.pro").read_text()
        )
        gradle = app_dir / "build.gradle.kts"
        source = gradle.read_text()
        rules = '            proguardFiles("chargegrid-map-rules.pro")\n'
        if rules not in source:
            anchor = '        release {\n'
            if anchor not in source:
                raise RuntimeError("Flet Android release configuration changed; review map JNI keep rules.")
            gradle.write_text(source.replace(anchor, anchor + rules, 1))
        return changed

    BaseBuildCommand.create_flutter_project = create_flutter_project
    os.chdir(ROOT / "apps" / "mobile")
    sys.argv = ["flet", "build", "apk", ".", "--yes", "--no-rich-output", *sys.argv[1:]]
    from flet_cli.cli import main as flet_main

    build_then_verify(
        flet_main,
        lambda: verify_apk(ROOT / "apps" / "mobile" / "build" / "apk" / "chargegrid.apk", build_environment),
    )


if __name__ == "__main__":
    main()
