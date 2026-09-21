"""Safe serial diagnostics and provisioning for the simulated ChargeGrid panel.

No START command exists. Device keys are read from a local file and never printed.
"""
import argparse
import json
import re
import select
import sys
import time
from pathlib import Path

import serial


def save_frame(port, header, output):
    _, width, height, count = header.split()
    width, height, count = int(width), int(height), int(count)
    if not (width == 400 and height == 240 and count == width * height * 2):
        raise SystemExit("Unexpected framebuffer dimensions")
    port.timeout = 30
    pixels = port.read(count)
    if len(pixels) != count:
        raise SystemExit("Incomplete framebuffer capture")
    footer = port.read_until(b"CG_FRAME_END")
    port.timeout = 0.2
    if not footer.endswith(b"CG_FRAME_END"):
        raise SystemExit("Invalid framebuffer terminator")
    rgb = bytearray()
    for offset in range(0, count, 2):
        pixel = pixels[offset] | (pixels[offset + 1] << 8)
        rgb.extend((((pixel >> 11) & 31) * 255 // 31,
                    ((pixel >> 5) & 63) * 255 // 63,
                    (pixel & 31) * 255 // 31))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(f"P6\n{width} {height}\n255\n".encode() + rgb)
    print(f"Captured physical LCD framebuffer: {output}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--action", choices=["status", "stop", "key", "boot", "screen", "live", "factory"], default="status")
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--factory-artifact", type=Path)
    parser.add_argument("--output", type=Path, default=Path("tmp/panel-validation/panel-physical.ppm"))
    parser.add_argument("--seconds", type=float, default=12)
    args = parser.parse_args()
    key = None
    claim = None
    if args.action == "factory":
        if not args.factory_artifact:
            parser.error("--factory-artifact is required for factory provisioning")
        if args.factory_artifact.stat().st_mode & 0o077:
            parser.error("Private factory artifact must not be readable by other users")
        artifact = json.loads(args.factory_artifact.read_text())
        key, claim = artifact.get("device_key"), artifact.get("claim_token")
        if not all(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{43}", value)
                   for value in (key, claim)):
            parser.error("Invalid private factory artifact")
    if args.action == "key" or args.key_file:
        if not args.key_file:
            parser.error("--key-file is required")
        key = args.key_file.read_text().strip()
        if not 16 <= len(key) <= 192 or any(c.isspace() for c in key):
            parser.error("Invalid device key file")
    port = serial.Serial(baudrate=115200, timeout=0.2)
    port.dtr = False
    port.rts = False
    port.port = args.port
    port.open()
    with port:
        if args.action == "boot":
            port.rts = True
            time.sleep(0.15)
            port.rts = False
        # Some CH340 macOS drivers reset at open. Wait for a status response
        # before provisioning/capture; never reopen the port during a live flow.
        port.write(b"CG_STATUS\n")
        deadline = time.monotonic() + args.seconds
        last_status = time.monotonic()
        sent_key = False
        factory_step = 0
        ready = False
        commands = {"status": b"CG_STATUS\n", "stop": b"CG_STOP\n", "screen": b"CG_SCREEN\n"}
        while time.monotonic() < deadline:
            line = port.readline().decode("utf-8", errors="replace").strip()
            if line:
                if line.startswith("CG_FRAME_RGB565 "):
                    save_frame(port, line, args.output)
                    if args.action == "screen":
                        return
                    continue
                if key:
                    line = line.replace(key, "[redacted]")
                if claim:
                    line = line.replace(claim, "[redacted]")
                print(line, flush=True)
                if line.startswith("[status]") and not ready:
                    ready = True
                    if args.action == "factory":
                        if "identity=missing" not in line or "session=none" not in line or "state=idle" not in line:
                            raise SystemExit("Factory provisioning requires a blank, idle panel")
                        port.write(b"CG_KEY\n")
                        factory_step = 1
                    elif key:
                        port.write(b"CG_KEY\n")
                    elif args.action in commands:
                        port.write(commands[args.action])
                    if args.action == "live":
                        print("LIVE: stdin commands status / stop / screen / quit; keep this port open during E2E.", flush=True)
                if args.action == "factory" and factory_step == 1 and "Device key (input hidden)" in line:
                    port.write((key + "\n").encode())
                    factory_step = 2
                elif args.action == "factory" and factory_step == 2 and "Device key saved" in line:
                    port.write(b"CG_CLAIM\n")
                    factory_step = 3
                elif args.action == "factory" and factory_step == 3 and "Claim token (input hidden)" in line:
                    port.write((claim + "\n").encode())
                    factory_step = 4
                elif args.action == "factory" and factory_step == 4 and "Claim token saved" in line:
                    print("Factory identity and private QR provisioned on the panel.", flush=True)
                    return
                elif args.action == "key" and key and "Device key (input hidden)" in line and not sent_key:
                    port.write((key + "\n").encode())
                    sent_key = True
            if args.action == "live" and ready and select.select([sys.stdin], [], [], 0)[0]:
                command = sys.stdin.readline().strip()
                if command == "quit":
                    return
                if command in commands:
                    port.write(commands[command])
            if time.monotonic() - last_status >= 4:
                port.write(b"CG_STATUS\n")
                last_status = time.monotonic()


if __name__ == "__main__":
    main()
