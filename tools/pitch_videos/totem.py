"""Totem (self-service panel, LVGL 800x480) videos in the same style as recorder.py.

The totem has no browser: its frames are the real LVGL renders produced on the host by
tools/tests/firmware_behavior.cpp (``kioskShot``/``kioskTap``; run tools/validate_firmware.py).
This helper turns a list of steps into a 30 fps MP4 at 1600x960 (5:3, the panel's ratio, 2x),
drawing the same touch ripple as the app videos (white ring + translucent white fill) at the tapped point.

    from totem import Step, build
    build([
        Step('tmp/panel-validation/kiosk-ready.png', hold=1.2, tap=(400, 380)),   # tap shown at the end
        Step('tmp/panel-validation/kiosk-welcome.png', hold=1.0, tap=(620, 400)),
        Step('tmp/panel-validation/kiosk-live.png', hold=2.0),
    ], 'output/pitch-videos/totem/01-autoatendimento.mp4')

Coordinates are panel pixels (800x480). Timing defaults come from recorder.PACE.
"""

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

from recorder import FPS, PACE, ROOT

SCALE = 2
SIZE = (800 * SCALE, 480 * SCALE)


@dataclass
class Step:
    image: str
    hold: float = PACE.after_tap      # seconds the screen is shown before the tap (or in total, if no tap)
    tap: tuple | None = None          # (x, y) in panel pixels; ripple plays at the end of the hold
    type_text: str | None = None      # unused placeholder for symmetry with the app (keypad taps are steps)


def _ripple(frame, x, y, t):
    """t in [0, 1] over 0.52 s: grow in (0-0.35), then expand and fade."""
    over = frame.convert('RGBA')
    layer = Image.new('RGBA', over.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    base = 23 * SCALE
    if t < 0.35:
        k = t / 0.35
        radius, alpha = base * (0.6 + 0.4 * k), k
    else:
        k = (t - 0.35) / 0.65
        radius, alpha = base * (1 + 0.7 * k), 1 - k
    cx, cy = x * SCALE, y * SCALE
    box = (cx - radius, cy - radius, cx + radius, cy + radius)
    draw.ellipse(box, fill=(255, 255, 255, int(66 * alpha)), outline=(255, 255, 255, int(242 * alpha)), width=int(2.5 * SCALE))
    return Image.alpha_composite(over, layer).convert('RGB')


def build(steps, out):
    work = Path(tempfile.mkdtemp(prefix='cg_totem_'))
    try:
        index = 0

        def emit(image):
            nonlocal index
            image.save(work / f'{index:06d}.png')
            index += 1

        for step in steps:
            frame = Image.open(ROOT / step.image).convert('RGB').resize(SIZE, Image.LANCZOS)
            for _ in range(round(step.hold * FPS)):
                emit(frame)
            if step.tap:
                ticks = round(0.52 * FPS)
                for tick in range(ticks):
                    emit(_ripple(frame, *step.tap, tick / ticks))
        last = Image.open(work / f'{index - 1:06d}.png')
        for _ in range(round(PACE.outro * FPS)):
            emit(last)
        target = ROOT / out
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-framerate', str(FPS), '-i', str(work / '%06d.png'),
                        '-vf', 'format=yuv420p', '-c:v', 'libx264', '-preset', 'slow', '-crf', '16', '-profile:v', 'high',
                        '-movflags', '+faststart', '-an', str(target)], check=True)
        print(f'{target}  ({index / FPS:.1f}s)')
        return target
    finally:
        shutil.rmtree(work, ignore_errors=True)
