"""Package a compiled Waveshare panel update, explicitly excluding NVS/secrets."""
import hashlib
import zipfile
from pathlib import Path

# Deve ser igual a CHARGEGRID_FIRMWARE_VERSION em firmware/esp32/include/runtime.h.
FIRMWARE_VERSION = "0.9.5"


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
    for path in sorted((root / "tmp/kiosk-validation").glob("kiosk-*.png")):
        files["preview/" + path.name] = path.read_bytes()
    files["README.md"] = f"""# ChargeGrid panel {FIRMWARE_VERSION}

Only for Waveshare ESP32-S3-Touch-LCD-7 (not 7B), 800x480,
ESP32-S3, 16 MB flash, 8 MB OPI PSRAM, DIO/40 MHz.
Version {FIRMWARE_VERSION} adds optional account login, account vehicle/autonomy,
maximum/reduced power, Pix/card or shared SIMULATED balance, review, live status and receipt.
The user-facing choices are value, time and account vehicle autonomy (no energy option).
Visitors see autonomy disabled with a login requirement; accounts also need a saved vehicle.
The payment screen shows a QR and the button "Já efetuei o pagamento". Opening the
presentation QR never confirms payment or debits a wallet; Stripe confirms server-side.
Charging and completion use one shared renderer for app-started and self-service sessions.
Stop confirmation retains the live card and measurements. Receipt QR visibility ends
after 30 seconds, with a countdown that touches cannot extend. Cable/overstay safety remains.
Maximum and reduced speeds have separate tariffs, editable in the owner's existing menu.
Reduced defaults to 20 percent cheaper. The purchased tier stays fixed during grid balancing.
The rotating #F code stays visible during reservations; their deadline has a separate area.
The top method badge is hidden. Offline chargers are distinct from an offline central;
pre-payment failures can be retried without the previous six-second return to the home screen.
The RGB panel uses the matching Espressif Arduino 3.1.1-h SDK (64-byte cache, PSRAM XIP),
two framebuffers, 20-line bounce buffers and the board's standard 16 MHz pixel clock.
The screen selects only chargers managed by its central. Every request, local Stop
and resumed order keeps the selected charger address. Account credentials/JWT stay
only in RAM and are cleared at completion, cancellation and inactivity timeout.
Wallet synchronization requires the updated mobile source included with this change;
old installed APKs still keep their simulated balance locally until updated.
API migration b6d2e8f1a490 adds the shared simulated wallet on top of d3f8a1c6e2b7.
Card/Pix payments use the hosted test checkout; no physical card terminal is assumed.

The panel displays the rotating #F station code with a countdown and
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

This is a lab using GoodWe HCA G2 simulators. With charger_link configured,
START requires the corresponding Modbus charger and readback; there is no fallback
to screen simulation. All START commands are authorized by the server.
Local Stop addresses only the selected charger. Wi-Fi and keys are provisioned separately.
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
