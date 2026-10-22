"""Compile real ESP32 controller/UI for host behavior tests and LVGL frame capture.

Requires clang/clang++, and libraries installed by `pio run -d firmware/esp32
-e waveshare_panel_ui`. Never opens a serial port or touches hardware.

Also runs the pure host tests of the simulated GoodWe HCA G2 charger
(firmware/goodwe-hca-sim) and of the panel's Modbus link to it, and builds the host
Modbus TCP server used by tools/tests/test_hca_sim_e2e.py. `--hca-only` runs just those
(no LVGL/PlatformIO libraries needed).
"""
import argparse
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("tmp/panel-validation"))
    parser.add_argument("--decode-qr", action="store_true", help="Decode rendered QR frames with Pillow and zxing-cpp")
    parser.add_argument("--compare-panel", type=Path, help="Directory with panel-*.ppm frames from a previous firmware; "
                        "every current panel frame (totem off) must be byte-identical")
    parser.add_argument("--hca-only", action="store_true",
                        help="Only the HCA G2 charger simulator and panel link host tests (no LVGL needed)")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    firmware = root / "firmware/esp32"
    if args.hca_only:
        output = args.output.resolve()
        output.mkdir(parents=True, exist_ok=True)
        run_hca_tests(root, output)
        return
    libraries = firmware / ".pio/libdeps/waveshare_panel_ui"
    lvgl = libraries / "lvgl"
    if not (lvgl / "lvgl.h").is_file():
        raise SystemExit("Run the waveshare_panel_ui PlatformIO build first.")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    objects = output / "objects"
    objects.mkdir(exist_ok=True)
    # Mesmas opções LVGL do env waveshare_panel_ui (Montserrat 28: LV_SYMBOL_BACKSPACE do teclado).
    flags = ["-DCHARGEGRID_PANEL_ENABLED", "-DCHARGEGRID_KIOSK", "-DLV_CONF_SKIP", "-DLV_COLOR_DEPTH=16",
             "-DLV_FONT_MONTSERRAT_14=1", "-DLV_FONT_MONTSERRAT_28=1", "-DLV_USE_QRCODE=1", "-DLV_MEM_SIZE=65536U",
             "-I" + str(lvgl), "-I" + str(firmware / "include")]
    run_hca_tests(root, output)
    api_test = output / "firmware_api_test"
    subprocess.run(["clang++", "-std=c++20", "-Wall", "-Wextra", "-Werror", "-g", "-fsanitize=address,undefined",
                    "-I" + str(root / "tools/tests/http_stubs"),
                    "-I" + str(root / "tools/tests/firmware_stubs"),
                    "-I" + str(firmware / "include"), "-I" + str(root / "firmware/shared/hca_g2/src"),
                    "-I" + str(libraries / "ArduinoJson/src"),
                    str(root / "tools/tests/firmware_api_test.cpp"), "-o", str(api_test)], check=True)
    subprocess.run([str(api_test)], check=True)
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
    # Totem 0.8.0: máquina de estados pura (sem Arduino/LVGL), com sanitizers.
    flow_test = output / "kiosk_flow_test"
    subprocess.run(["clang++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-g", "-fsanitize=address,undefined",
                    "-I" + str(firmware / "include"), "-I" + str(libraries / "ArduinoJson/src"),
                    str(root / "tools/tests/kiosk_flow_test.cpp"), str(firmware / "src/kiosk_flow.cpp"),
                    "-o", str(flow_test)], check=True)
    subprocess.run([str(flow_test)], check=True)
    executable = output / "firmware_behavior"
    hca = hca_paths(root)
    subprocess.run(["clang++", "-std=c++17", "-DCHARGEGRID_PANEL_ENABLED", *flags,
                    "-I" + str(root / "tools/tests/firmware_stubs"),
                    "-I" + str(libraries / "ArduinoJson/src"), *hca["includes"],
                    str(root / "tools/tests/firmware_behavior.cpp"), *compiled, *hca["sources"],
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
        kiosk = "https://chargegrid-api-preview-djlima1s-projects.vercel.app/pay/k/CG-01?c=12345"
        for name in ("panel-kiosk-qr", "panel-kiosk-awaiting"):
            found = zxingcpp.read_barcodes(Image.open(output / (name + ".ppm")))
            assert [result.text for result in found] == [kiosk], f"Unexpected payment QR in {name}"
        for name in ("panel-idle", "panel-overstay-fee"):
            assert not zxingcpp.read_barcodes(Image.open(output / (name + ".ppm"))), f"Payment QR leaked in {name}"
        base = "https://chargegrid-api-preview-djlima1s-projects.vercel.app"
        token = "?t=QUJDREVGR0hJSktMTU5PUFFSU1RVVldY"
        order = "7d0c9a52-3f1e-4b5a-9a51-2c0d5e8f1a10"
        totem = {"kiosk-pay-simulated": f"{base}/pay/o/{order}{token}", "kiosk-pay-stripe": f"{base}/pay/o/{order}{token}", "kiosk-receipt": f"{base}/pay/r/{order}{token}"}
        for name, expected_url in totem.items():
            found = zxingcpp.read_barcodes(Image.open(output / (name + ".ppm")))
            assert [result.text for result in found] == [expected_url], f"Unexpected totem QR in {name}: {found}"
        for name in ("kiosk-ready", "kiosk-live", "kiosk-review", "kiosk-receipt-expired-connected"):
            assert not zxingcpp.read_barcodes(Image.open(output / (name + ".ppm"))), f"Unexpected QR in {name}"
        print("PASS: actual LVGL QR decoded offline/online, absent after ownership and for legacy owner")
        print("PASS: totem order QR (Stripe, T4) and receipt QR (T8) decoded; no QR on live/review")
        print("PASS: payment kiosk QR decoded on the Ready screen, absent without kiosk_url")
    if args.compare_panel:
        frames = sorted(path.name for path in output.glob("panel-*.ppm") if path.name != "panel-idle-after-kiosk.ppm")
        previous = args.compare_panel.resolve()
        compared = 0
        for name in frames:
            if (previous / name).is_file():
                assert (previous / name).read_bytes() == (output / name).read_bytes(), f"{name} changed with the totem off"
                compared += 1
        assert compared, "No panel frames to compare"
        print(f"PASS: {compared} panel frames byte-identical to {previous} (totem off)")
    print(f"Actual firmware LVGL frames: {output}")


def hca_paths(root):
    shared = root / "firmware/shared/hca_g2/src"
    core = root / "firmware/goodwe-hca-sim/lib/hca_sim_core/src"
    return {"includes": ["-I" + str(shared), "-I" + str(core), "-I" + str(root / "firmware/esp32/include")],
            "sources": [str(core / "hca_sim_core.cpp"), str(shared / "modbus_tcp.cpp")]}


def run_hca_tests(root, output):
    """Carregador HCA G2 simulado + link da tela: C++ puro com sanitizers, e o servidor de host."""
    hca = hca_paths(root)
    strict = ["clang++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-g", "-fsanitize=address,undefined",
              *hca["includes"]]
    tests = {"hca_sim_test": [], "charger_link_test": [str(root / "firmware/esp32/src/charger_link.cpp")]}
    for name, extra in tests.items():
        binary = output / name
        subprocess.run([*strict, str(root / "tools/tests" / (name + ".cpp")), *extra, *hca["sources"],
                        "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True)
    transport = output / "charger_transport_test"
    subprocess.run([*strict, "-I" + str(root / "tools/tests/transport_stubs"),
                    str(root / "tools/tests/charger_transport_test.cpp"),
                    str(root / "firmware/esp32/src/charger_link.cpp"), *hca["sources"],
                    "-o", str(transport)], check=True)
    subprocess.run([str(transport)], check=True)
    server = output / "hca_sim_host"
    subprocess.run(["clang++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-O1", *hca["includes"],
                    str(root / "firmware/goodwe-hca-sim/host/hca_sim_host.cpp"), *hca["sources"],
                    "-o", str(server)], check=True)
    print(f"PASS: HCA G2 host Modbus TCP server built: {server}")


if __name__ == "__main__":
    main()
