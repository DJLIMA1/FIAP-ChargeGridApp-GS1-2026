"""Package a compiled Waveshare panel update, explicitly excluding NVS/secrets."""
import hashlib
import zipfile
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    build = root / "firmware/esp32/.pio/build/waveshare_panel_ui"
    output = root / "builds/chargegrid-waveshare-7-0.3.4.zip"
    files = {name: (build / name).read_bytes() for name in
             ("firmware.bin", "bootloader.bin", "partitions.bin")}
    for name in ("panel-idle.png", "panel-charging.png", "panel-maintenance.png", "panel-physical-0.3.4.png"):
        path = root / "tmp/panel-validation" / name
        if path.exists():
            files[name] = path.read_bytes()
    files["README.md"] = b"""# ChargeGrid panel 0.3.4

Only for Waveshare ESP32-S3-Touch-LCD-7 (not 7B), 800x480,
ESP32-S3, 16 MB flash, 8 MB OPI PSRAM, DIO/40 MHz.
Version 0.3.4 keeps the synchronized display buffers, replaces engineering
metrics with customer-facing status and steps, and aligns the logo with the app.

Update an already configured panel (preserves NVS, Wi-Fi, identity and session journal):

    esptool.py --chip esp32s3 --port PORT --baud 460800 write_flash --flash_mode dio --flash_freq 40m --flash_size 16MB 0x10000 firmware.bin

Do not use erase_flash. Do not overwrite NVS at 0x9000..0xdfff.
bootloader.bin (0x0) and partitions.bin (0x8000) are included for recovery;
normal updates only need firmware.bin at 0x10000 on the existing partition map.
Perform updates only after the station is idle and no session is pending.

This is a simulated lab: no relay or vehicle charger is controlled.
START is authorized only by the server. Local Stop always de-energizes the
simulated state. Wi-Fi and per-device key are provisioned separately.
Factory units additionally receive a separate private ownership claim QR.
Do not put a device API key in a QR. Existing owners are preserved on update.

UI references use the actual firmware LVGL renderer. panel-physical-0.3.4.png,
when included, is a 400x240 capture of the connected LCD framebuffer.
No device key, network credentials, NVS image, or merged flash image is included.

Build and behavioral checks from repository root:

    pio run -d firmware/esp32 -e waveshare_panel_ui
    python tools/validate_firmware.py
"""
    files["SHA256SUMS.txt"] = "".join(
        f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in files.items()).encode()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    print(output)
    print("sha256", hashlib.sha256(output.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
