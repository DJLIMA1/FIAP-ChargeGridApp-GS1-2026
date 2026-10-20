"""Package a compiled Waveshare panel update, explicitly excluding NVS/secrets."""
import hashlib
import zipfile
from pathlib import Path

# Deve ser igual a CHARGEGRID_FIRMWARE_VERSION em firmware/esp32/include/runtime.h.
FIRMWARE_VERSION = "0.8.0"


def main():
    root = Path(__file__).resolve().parents[1]
    build = root / "firmware/esp32/.pio/build/waveshare_panel_ui"
    output = root / f"builds/chargegrid-waveshare-7-{FIRMWARE_VERSION}.zip"
    files = {name: (build / name).read_bytes() for name in
             ("firmware.bin", "bootloader.bin", "partitions.bin")}
    for name in ("panel-idle.png", "panel-charging.png", "panel-maintenance.png"):
        path = root / "tmp/panel-validation" / name
        if path.exists():
            files[name] = path.read_bytes()
    files["README.md"] = f"""# ChargeGrid panel {FIRMWARE_VERSION}

Only for Waveshare ESP32-S3-Touch-LCD-7 (not 7B), 800x480,
ESP32-S3, 16 MB flash, 8 MB OPI PSRAM, DIO/40 MHz.
Version {FIRMWARE_VERSION} displays the rotating #F station code with a countdown and
progress bar. The server validates this code when a user starts charging.
It applies live power changes (SET_POWER, 0 W pauses), keeps the simulated cable
connected after a stop when the driver accepted the overstay fee (unplug with
"Desconectar"), and shows the Stripe test-mode payment QR on the Ready screen.
When the seller turns on the station's self-service totem, the panel also runs the
no-phone flow (choose, review, pay, charge, receipt); with the totem off or on an
older API it keeps the 0.7.0 screens.
The device key stays private. Seller-confirmed factory reset preserves Wi-Fi,
replaces the device identity and shows a fresh private ownership QR.

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

UI references use the actual firmware LVGL renderer.
No device key, network credentials, NVS image, or merged flash image is included.

Build and behavioral checks from repository root:

    pio run -d firmware/esp32 -e waveshare_panel_ui
    python tools/validate_firmware.py
""".encode()
    files["SHA256SUMS.txt"] = "".join(
        f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in files.items()).encode()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    print(output)
    print("sha256", hashlib.sha256(output.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
