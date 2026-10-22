"""Flicker check for the pitch videos (needs numpy: run with python3 from Homebrew or `uv run --with numpy`).

    python3 tools/pitch_videos/check_flicker.py output/pitch-videos/app/*.mp4

Two tests per video; both must print 0:
  flicker  3+ grid cells (2+ rows) change and come back within 4 frames (A-B-A): a frame of another size, a stale frame
  dips     the whole picture loses most of its detail for <= 12 frames (a blank/half-painted screen, a fade)
"""
import subprocess
import sys

import numpy as np


def gray(path, width):
    size = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v', '-show_entries', 'stream=width,height',
                           '-of', 'csv=p=0', path], capture_output=True, text=True).stdout.strip().split(',')
    w, h = int(size[0]), int(size[1])
    height = round(h * width / w / 2) * 2
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-vf', f'scale={width}:{height},format=gray',
                          '-f', 'rawvideo', '-'], capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, height, width).astype(np.float32)


def flicker(path):
    f = gray(path, 120)
    _, hh, ww = f.shape
    gy, gx = (12, 6) if hh > ww else (6, 10)
    ch, cw = hh // gy, ww // gx
    c = f[:, :gy * ch, :gx * cw].reshape(len(f), gy, ch, gx, cw).mean(axis=(2, 4))
    hits = []
    for i in range(1, len(c) - 1):
        jump = np.abs(c[i] - c[i - 1])
        if jump.max() < 18:
            continue
        for k in range(1, 5):
            j = i + k
            if j >= len(c):
                break
            cells = (jump > 18) & (np.abs(c[j] - c[i - 1]) < 4)
            # 3+ cells over 2+ rows: a button's own pressed/busy state (one row of cells for a few frames,
            # e.g. "Continuar" greying out while the next screen loads) is the app's feedback, not flicker
            rows = np.nonzero(cells.any(axis=1))[0]
            if cells.sum() >= 3 and len(rows) >= 2 and (np.abs(c[j] - c[i]) > 18)[cells].all():
                hits.append(f'{i / 30:.2f}s x{k}')
                break
    return hits


def dips(path):
    s = gray(path, 90).std(axis=(1, 2))
    hits, i = [], 1
    while i < len(s) - 1:
        for length in range(1, 13):
            j = i + length
            if j >= len(s):
                break
            if s[i:j].max() < 0.6 * min(s[i - 1], s[j]):
                hits.append(f'{i / 30:.2f}s len{length}')
                i = j
                break
        i += 1
    return hits


if __name__ == '__main__':
    for video in sys.argv[1:]:
        a, b = flicker(video), dips(video)
        print(f'{video}: flicker={len(a)} {a[:6]} dips={len(b)} {b[:6]}')
