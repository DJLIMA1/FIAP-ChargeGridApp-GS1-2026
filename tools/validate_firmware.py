"""Compile real ESP32 controller/UI for host behavior tests and LVGL frame capture.

Requires clang/clang++, and libraries installed by `pio run -d firmware/esp32
-e waveshare_panel_ui`. Never opens a serial port or touches hardware.
"""
import argparse
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("tmp/panel-validation"))
    parser.add_argument("--decode-qr", action="store_true", help="Decode rendered QR frames with Pillow and zxing-cpp")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    firmware = root / "firmware/esp32"
    libraries = firmware / ".pio/libdeps/waveshare_panel_ui"
    lvgl = libraries / "lvgl"
    if not (lvgl / "lvgl.h").is_file():
        raise SystemExit("Run the waveshare_panel_ui PlatformIO build first.")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    objects = output / "objects"
    objects.mkdir(exist_ok=True)
    flags = ["-DCHARGEGRID_PANEL_ENABLED", "-DLV_CONF_SKIP", "-DLV_COLOR_DEPTH=16", "-DLV_FONT_MONTSERRAT_14=1", "-DLV_USE_QRCODE=1",
             "-I" + str(lvgl), "-I" + str(firmware / "include")]
    sources = sorted((lvgl / "src").rglob("*.c"))
    sources += sorted((firmware / "src").glob("panel_font*.c"))
    sources += [firmware / "src/chargegrid_logo.c"]

    def compile_source(source):
        obj = objects / (str(source.relative_to(firmware)).replace("/", "_") + ".o")
        if not obj.exists() or obj.stat().st_mtime < max(source.stat().st_mtime, Path(__file__).stat().st_mtime):
            subprocess.run(["clang", "-O1", *flags, "-c", str(source), "-o", str(obj)],
                           check=True, capture_output=True)
        return str(obj)

    with ThreadPoolExecutor(max_workers=8) as pool:
        compiled = list(pool.map(compile_source, sources))
    executable = output / "firmware_behavior"
    subprocess.run(["clang++", "-std=c++17", "-DCHARGEGRID_PANEL_ENABLED", *flags,
                    "-I" + str(root / "tools/tests/firmware_stubs"),
                    "-I" + str(libraries / "ArduinoJson/src"),
                    str(root / "tools/tests/firmware_behavior.cpp"), *compiled,
                    "-o", str(executable)], check=True)
    subprocess.run([str(executable), str(output)], check=True)
    if args.decode_qr:
        import zxingcpp
        from PIL import Image

        expected = "chargegrid://claim?token=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefg"
        for name in ("panel-factory-qr-offline", "panel-factory-qr-online"):
            found = zxingcpp.read_barcodes(Image.open(output / (name + ".ppm")))
            assert [result.text for result in found] == [expected], f"Unexpected rendered QR in {name}"
        for name in ("panel-factory-claimed-inactive", "panel-factory-claimed-active", "panel-legacy-owner-no-qr"):
            assert not zxingcpp.read_barcodes(Image.open(output / (name + ".ppm"))), f"Claim QR leaked in {name}"
        print("PASS: actual LVGL QR decoded offline/online, absent after ownership and for legacy owner")
    print(f"Actual firmware LVGL frames: {output}")


if __name__ == "__main__":
    main()
