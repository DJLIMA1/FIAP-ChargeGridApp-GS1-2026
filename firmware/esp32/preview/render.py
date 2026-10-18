"""Render the totem screens on the host with the real LVGL + src/panel_ui.cpp.

    .venv/bin/python firmware/esp32/preview/render.py [--output DIR] [--reference DIR]

Needs clang/clang++ and the libraries fetched by `pio run -d firmware/esp32
-e waveshare_panel_ui`. Writes totem-*.png (800x480, exactly what the panel
draws) and, when --reference points at the design renders (1.jpg..4.jpg),
compare-*.png with design | firmware side by side. Never opens a serial port.
"""
import argparse
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

NAMES = {1: "totem-1-setup", 2: "totem-2-ready", 3: "totem-3-unavailable", 4: "totem-4-maintenance"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("tmp/panel-preview"))
    parser.add_argument("--reference", type=Path, help="folder with the design's 1.jpg..4.jpg")
    parser.add_argument("--lv-mem", default="65536U", help="LV_MEM_SIZE; matches platformio.ini")
    args = parser.parse_args()
    firmware = Path(__file__).resolve().parents[1]
    lvgl = firmware / ".pio/libdeps/waveshare_panel_ui/lvgl"
    json_lib = firmware / ".pio/libdeps/waveshare_panel_ui/ArduinoJson/src"
    stubs = firmware.parents[1] / "tools/tests/firmware_stubs"
    if not (lvgl / "lvgl.h").is_file():
        raise SystemExit("Run the waveshare_panel_ui PlatformIO build first.")
    out = args.output.resolve()
    objects = out / "objects"
    objects.mkdir(parents=True, exist_ok=True)
    flags = ["-DCHARGEGRID_PANEL_ENABLED", "-DLV_CONF_SKIP", "-DLV_COLOR_DEPTH=16", "-DLV_FONT_MONTSERRAT_14=1",
             "-DLV_USE_QRCODE=1", f"-DLV_MEM_SIZE={args.lv_mem}", "-I" + str(lvgl), "-I" + str(firmware / "include")]
    sources = sorted((lvgl / "src").rglob("*.c"))
    sources += sorted((firmware / "src").glob("panel_font*.c")) + [firmware / "src/chargegrid_logo.c"]
    stamp = args.lv_mem.replace("*", "x").replace("(", "").replace(")", "")

    def compile_source(source):
        obj = objects / (stamp + "_" + str(source.relative_to(firmware)).replace("/", "_") + ".o")
        if not obj.exists() or obj.stat().st_mtime < source.stat().st_mtime:
            subprocess.run(["clang", "-O1", *flags, "-c", str(source), "-o", str(obj)], check=True, capture_output=True)
        return str(obj)

    with ThreadPoolExecutor(max_workers=8) as pool:
        compiled = list(pool.map(compile_source, sources))
    exe = out / "panel_preview"
    subprocess.run(["clang++", "-std=c++17", "-O1", *flags, "-I" + str(stubs), "-I" + str(json_lib),
                    str(firmware / "preview/panel_preview.cpp"), *compiled, "-o", str(exe)], check=True)
    subprocess.run([str(exe), str(out)], check=True)
    from PIL import Image
    for ppm in sorted(out.glob("totem-*.ppm")):
        Image.open(ppm).save(ppm.with_suffix(".png"))
        ppm.unlink()
    if args.reference:
        for index, name in NAMES.items():
            ref = Image.open(args.reference / f"{index}.jpg").convert("RGB").resize((800, 480), Image.LANCZOS)
            mine = Image.open(out / f"{name}.png").convert("RGB")
            # The design is 2:1; the panel is 5:3: the UI stretches its vertical positions by 1.2
            # to fill 800x480, so the reference is shown stretched the same way.
            sheet = Image.new("RGB", (800, 480 + 480 + 12), (255, 255, 255))
            sheet.paste(ref, (0, 0))
            sheet.paste(mine, (0, 492))
            sheet.save(out / f"compare-{index}.png")
    print(f"Frames: {out}")


if __name__ == "__main__":
    main()
