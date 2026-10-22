"""Reject release APKs whose MapLibre JNI factory was optimized to return null."""

import os
import re
import subprocess
from pathlib import Path


def verify_factory_code(code: str) -> None:
    method = re.search(r"\.method public create\(.*?\.end method", code, re.DOTALL)
    if not method:
        raise ValueError("MapLibre Android factory is missing from the APK.")
    instructions = [line.strip() for line in method[0].splitlines()
                    if line.strip() and not line.strip().startswith((".", "#"))]
    call = next((i for i, line in enumerate(instructions)
                 if "->createPlatformView(I)Lio/flutter/plugin/platform/PlatformView;" in line), None)
    if call is None or call + 2 >= len(instructions):
        raise ValueError("MapLibre Android factory has no JNI creation call.")
    result = re.fullmatch(r"move-result-object (\w+)", instructions[call + 1])
    if not result or instructions[call + 2] != f"return-object {result[1]}":
        raise ValueError("R8 discarded the MapLibre JNI result: the map would be unavailable on Android.")


def verify_apk(apk: Path, env=None) -> None:
    env = env or os.environ
    sdk = Path(env["ANDROID_HOME"])
    candidates = sorted(sdk.glob("cmdline-tools/*/bin/apkanalyzer"), reverse=True)
    if not candidates:
        raise RuntimeError("Android apkanalyzer is required to validate the release map factory.")
    code = subprocess.check_output(
        [str(candidates[0]), "dex", "code", "--class",
         "com.github.josxha.maplibre.MapLibreMapFactory", str(apk)],
        env=env, text=True,
    )
    verify_factory_code(code)
    print("Android release: MapLibre JNI factory preserved.", flush=True)
