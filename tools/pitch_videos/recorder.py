"""Shared recorder for the pitch interaction videos (one style for every flow).

Every flow script under tools/pitch_videos/flows/ uses this module so all videos share the
same look: same touch ripple (app) / cursor (web), same pacing, same encoding.

    from recorder import AppSession, WebSession, PACE

    with AppSession(port=8931, route='home', mode='consumer') as s:   # Flet app, demo account
        s.hold(PACE.intro)
        s.tap_text('Recarga')          # finds the Flutter semantics node by its label
        s.tap(201, 640)                # or css-pt coordinates in the 402x874 viewport
        s.type('Villa Lobos')
        s.scroll(300)
        s.hold(PACE.outro)
        s.render('output/pitch-videos/app/04-busca-postos.mp4')

    with WebSession(url='http://127.0.0.1:5179/painel/') as s:     # owner-web (mock), 1440x810
        s.click_text('Estações'); s.render('output/pitch-videos/web/....mp4')

Frames come from the Chrome DevTools screencast (real pixels of the real app), are timed by their
own timestamps and encoded to constant 30 fps H.264 (yuv420p, CRF 16, faststart): Canva-ready.

Output sizes: app 1080x2348 (402x874 pt phone, 9:19.5), web 1920x1080 (16:9).
The totem (LVGL, 800x480) has its own helper: totem.py.
"""

import base64
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHROME = os.environ.get('CHROME_BIN', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
FPS = 30
VECTOR_CLIENT = ROOT / 'apps/mobile/.flet/vector-client/build/web'


class PACE:
    """Shared timing (seconds). Use these instead of ad-hoc numbers so every video breathes the same."""
    intro = 1.2        # first screen visible before the first touch
    after_tap = 1.0    # after a tap, before the next action (screen transition + reading)
    read = 2.0         # a screen worth reading (result, chart, receipt)
    outro = 2.0        # last screen held at the end
    type_cps = 14      # typing speed, characters per second
    move = 0.55        # web cursor travel time


# Touch ripple: white ring + translucent white fill (visible on the red brand buttons and the dark UI), 520 ms.
OVERLAY_JS = r"""
(() => {
  if (window.__cg) return;
  const style = document.createElement('style');
  style.textContent = `
  #cg-layer{position:fixed;inset:0;pointer-events:none;z-index:2147483647}
  .cg-touch{position:absolute;width:46px;height:46px;margin:-23px 0 0 -23px;border-radius:50%;
    background:rgba(255,255,255,.26);border:2.5px solid rgba(255,255,255,.95);
    box-shadow:0 0 0 1px rgba(0,0,0,.25),0 2px 10px rgba(0,0,0,.35);transform:scale(.6);opacity:0;
    transition:transform .18s ease-out,opacity .18s ease-out}
  .cg-touch.on{transform:scale(1);opacity:1}
  .cg-touch.off{transform:scale(1.7);opacity:0;transition:transform .34s ease-out,opacity .34s ease-out}
  #cg-cursor{position:absolute;left:0;top:0;width:26px;height:26px;transition:none;
    filter:drop-shadow(0 2px 3px rgba(0,0,0,.45))}
  .cg-click{position:absolute;width:34px;height:34px;margin:-17px 0 0 -17px;border-radius:50%;
    border:2.5px solid rgba(255,255,255,.95);box-shadow:0 0 0 1px rgba(0,0,0,.3);opacity:.9;transform:scale(.4);
    transition:transform .38s ease-out,opacity .38s ease-out}
  .cg-click.go{transform:scale(1.5);opacity:0}`;
  document.head.appendChild(style);
  const layer = document.createElement('div'); layer.id = 'cg-layer'; document.body.appendChild(layer);
  window.__cg = {
    touch(x, y, hold) {
      const d = document.createElement('div'); d.className = 'cg-touch';
      d.style.left = x + 'px'; d.style.top = y + 'px'; layer.appendChild(d);
      requestAnimationFrame(() => d.classList.add('on'));
      setTimeout(() => { d.classList.add('off'); setTimeout(() => d.remove(), 400); }, hold || 260);
    },
    cursor(x, y, ms) {
      let c = document.getElementById('cg-cursor');
      if (!c) {
        c = document.createElement('div'); c.id = 'cg-cursor';
        c.innerHTML = '<svg viewBox="0 0 24 24" width="26" height="26"><path d="M3 2l7.5 19 2.6-7.6L21 11z" fill="#fff" stroke="#111" stroke-width="1.4" stroke-linejoin="round"/></svg>';
        layer.appendChild(c); c.style.transform = `translate(${x}px,${y}px)`; return;
      }
      c.style.transition = `transform ${ms}ms cubic-bezier(.45,0,.25,1)`;
      c.style.transform = `translate(${x}px,${y}px)`;
    },
    click(x, y) {
      const d = document.createElement('div'); d.className = 'cg-click';
      d.style.left = x + 'px'; d.style.top = y + 'px'; layer.appendChild(d);
      requestAnimationFrame(() => requestAnimationFrame(() => d.classList.add('go')));
      setTimeout(() => d.remove(), 500);
    },
  };
})();
"""

# Flutter web: turn on the semantics tree so labels can be located; returns [{label,x,y,w,h}].
SEMANTICS_JS = r"""
(() => {
  const ph = document.querySelector('flt-semantics-placeholder');
  if (ph) ph.click();
  const out = [];
  const nodes = [];
  const walk = (root) => {
    root.querySelectorAll('flt-semantics, [role], input, textarea').forEach(n => nodes.push(n));
    root.querySelectorAll('*').forEach(n => { if (n.shadowRoot) walk(n.shadowRoot); });
  };
  walk(document);
  for (const n of nodes) {
    const r = n.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    const label = (n.getAttribute('aria-label') || n.innerText || n.getAttribute('placeholder') || '').trim();
    if (!label) continue;
    out.push({label, role: n.getAttribute('role') || n.tagName.toLowerCase(), x: r.left, y: r.top, w: r.width, h: r.height});
  }
  return out;
})()
"""


def _leaves(items):
    """Drop matches that contain another match (containers repeat their children's text)."""
    def inside(a, b):
        return (a is not b and b['x'] >= a['x'] - 0.5 and b['y'] >= a['y'] - 0.5 and
                b['x'] + b['w'] <= a['x'] + a['w'] + 0.5 and b['y'] + b['h'] <= a['y'] + a['h'] + 0.5)
    unique = []
    for item in items:
        if not any(abs(item['x'] - u['x']) < 1 and abs(item['y'] - u['y']) < 1 and abs(item['w'] - u['w']) < 1
                   and abs(item['h'] - u['h']) < 1 for u in unique):
            unique.append(item)
    return [a for a in unique if not any(inside(a, b) for b in unique)]


def free(port):
    with socket.socket() as sock:
        return sock.connect_ex(('127.0.0.1', port)) != 0


def wait_http(url, seconds):
    end = time.time() + seconds
    while time.time() < end:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return True
        except OSError:
            time.sleep(0.3)
    return False


class CDP:
    """Minimal DevTools client: one reader thread, synchronous calls, screencast frames stored with timestamps."""

    def __init__(self, ws_url):
        from websockets.sync.client import connect
        self.ws = connect(ws_url, max_size=256 * 1024 * 1024)
        self.counter = 0
        self.pending = {}
        self.lock = threading.Lock()
        self.frames = []          # (timestamp, jpeg bytes)
        self.recording = False
        self.offset = 0.0         # seconds cut out by pause()/resume()
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _read(self):
        while True:
            try:
                message = json.loads(self.ws.recv())
            except Exception:
                return
            if 'id' in message:
                slot = self.pending.get(message['id'])
                if slot:
                    slot['result'] = message
                    slot['event'].set()
            elif message.get('method') == 'Page.screencastFrame':
                params = message['params']
                if self.recording:
                    self.frames.append((params['metadata']['timestamp'] - self.offset, base64.b64decode(params['data'])))
                threading.Thread(target=self.call, args=('Page.screencastFrameAck',),
                                 kwargs={'sessionId': params['sessionId']}, daemon=True).start()

    def call(self, method, timeout=60, **params):
        with self.lock:
            self.counter += 1
            ident = self.counter
            slot = {'event': threading.Event()}
            self.pending[ident] = slot
            self.ws.send(json.dumps({'id': ident, 'method': method, 'params': params}))
        if not slot['event'].wait(timeout):
            raise TimeoutError(method)
        self.pending.pop(ident, None)
        result = slot['result']
        if 'error' in result:
            raise RuntimeError(f"{method}: {result['error']}")
        return result.get('result', {})

    def js(self, expression):
        result = self.call('Runtime.evaluate', expression=expression, returnByValue=True, awaitPromise=True)
        return result.get('result', {}).get('value')

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


SLOTS = int(os.environ.get('CG_PITCH_SLOTS', '4'))   # recordings allowed at once on this machine
SLOT_DIR = Path(tempfile.gettempdir()) / 'cg-pitch-slots'


def _acquire_slot():
    """Many flow scripts may run in parallel (one per agent); only SLOTS record at the same time so the
    software-rendered Chrome keeps a smooth frame rate. Blocks until a slot is free."""
    import fcntl
    SLOT_DIR.mkdir(exist_ok=True)
    while True:
        for index in range(SLOTS):
            handle = open(SLOT_DIR / f'slot{index}', 'w')  # noqa: SIM115 (released in close)
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return handle
            except OSError:
                handle.close()
        time.sleep(1.0)


class _Session:
    width = height = 0
    scale = 1.0
    out_size = (0, 0)

    def __init__(self, port):
        self.slot = _acquire_slot()
        self.port = port
        self.workdir = Path(tempfile.mkdtemp(prefix=f'cg_pitch_{port}_'))
        self.chrome = None
        self.cdp = None

    # -- browser -------------------------------------------------------------------------------
    def _start_chrome(self):
        debug_port = next(p for p in range(self.port + 1000, self.port + 1100) if free(p))
        self.chrome = subprocess.Popen([
            CHROME, '--headless=new', '--hide-scrollbars', f'--window-size={self.width},{self.height}',
            f'--remote-debugging-port={debug_port}', f'--user-data-dir={self.workdir / "chrome"}', '--no-first-run',
            '--no-default-browser-check', '--disable-background-timer-throttling', '--disable-renderer-backgrounding',
            '--disable-backgrounding-occluded-windows', '--enable-unsafe-swiftshader', '--use-angle=swiftshader',
            '--ignore-gpu-blocklist', '--lang=pt-BR', 'about:blank',
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        if not wait_http(f'http://127.0.0.1:{debug_port}/json/version', 30):
            raise RuntimeError('Chrome did not start')
        targets = json.load(urllib.request.urlopen(f'http://127.0.0.1:{debug_port}/json'))
        page = next(item for item in targets if item.get('type') == 'page')
        self.cdp = CDP(page['webSocketDebuggerUrl'])
        self.cdp.call('Page.enable')
        self.cdp.call('Runtime.enable')
        self.cdp.call('Emulation.setDeviceMetricsOverride', width=self.width, height=self.height,
                      deviceScaleFactor=self.scale, mobile=False)

    def _start_screencast(self):
        self.cdp.call('Page.startScreencast', format='jpeg', quality=95,
                      maxWidth=round(self.width * self.scale), maxHeight=round(self.height * self.scale), everyNthFrame=1)

    def overlay(self):
        self.cdp.js(OVERLAY_JS)

    def record(self):
        """Start keeping frames (call after the first screen is ready; loading is never recorded)."""
        self.overlay()
        time.sleep(0.15)
        first = self.cdp.call('Page.captureScreenshot', format='jpeg', quality=95)['data']
        self.cdp.frames.clear()
        self.cdp.frames.append((time.time() - self.cdp.offset, base64.b64decode(first)))
        self.cdp.recording = True

    def pause(self):
        """Stop keeping frames (e.g. to set up a state off camera); resume() continues without a gap."""
        self.cdp.recording = False
        self._paused_at = time.time()

    def resume(self):
        time.sleep(0.15)
        self.cdp.offset += time.time() - self._paused_at
        shot = self.cdp.call('Page.captureScreenshot', format='jpeg', quality=95)['data']
        self.cdp.frames.append((time.time() - self.cdp.offset, base64.b64decode(shot)))
        self.cdp.recording = True

    # -- pacing --------------------------------------------------------------------------------
    def hold(self, seconds):
        time.sleep(seconds)

    def shot(self, path):
        """Debug PNG of the current screen (not part of the video)."""
        data = self.cdp.call('Page.captureScreenshot', format='png')['data']
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(base64.b64decode(data))
        return path

    # -- input ---------------------------------------------------------------------------------
    def _mouse(self, kind, x, y, **extra):
        self.cdp.call('Input.dispatchMouseEvent', type=kind, x=x, y=y, button='left', **extra)

    def type(self, text, cps=None):
        delay = 1.0 / (cps or PACE.type_cps)
        for char in text:
            self.cdp.call('Input.insertText', text=char)
            time.sleep(delay)

    def key(self, name, code=None, vk=None):
        """Special key, e.g. key('Enter', 'Enter', 13), key('Backspace', 'Backspace', 8)."""
        params = {'key': name, 'code': code or name}
        if vk:
            params['windowsVirtualKeyCode'] = vk
        self.cdp.call('Input.dispatchKeyEvent', type='keyDown', **params)
        self.cdp.call('Input.dispatchKeyEvent', type='keyUp', **params)

    def scroll(self, dy, x=None, y=None, steps=12, seconds=0.6):
        """Smooth wheel scroll by dy css px (positive = down)."""
        x = self.width / 2 if x is None else x
        y = self.height / 2 if y is None else y
        for _ in range(steps):
            self.cdp.call('Input.dispatchMouseEvent', type='mouseWheel', x=x, y=y, deltaX=0, deltaY=dy / steps)
            time.sleep(seconds / steps)

    def labels(self):
        """[{label, role, x, y, w, h}] of what is on screen (Flutter semantics / DOM)."""
        return self.cdp.js(SEMANTICS_JS) or []

    def find(self, text, exact=False, index=0, timeout=15):
        """Center (x, y) of the index-th element whose label contains (or equals) text."""
        end = time.time() + timeout
        while True:
            found = [item for item in self.labels()
                     if (item['label'] == text if exact else text.casefold() in item['label'].casefold())]
            found = _leaves(found)
            found.sort(key=lambda item: (round(item['y']), item['x']))
            if len(found) > index:
                item = found[index]
                return item['x'] + item['w'] / 2, item['y'] + item['h'] / 2
            if time.time() > end:
                names = sorted({item['label'][:40] for item in self.labels()})
                raise LookupError(f'{text!r} not on screen; labels: {names}')
            time.sleep(0.4)

    # -- output --------------------------------------------------------------------------------
    def render(self, out, crop=None):
        """Encode the recorded frames to a constant-30-fps MP4 at self.out_size."""
        end = time.time() - self.cdp.offset
        self.cdp.recording = False
        time.sleep(0.2)
        frames = sorted(self.cdp.frames, key=lambda frame: frame[0])
        if not frames:
            raise RuntimeError('no frames recorded (did you call record()?)')
        folder = self.workdir / 'frames'
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir()
        sources = []
        for index, (_, data) in enumerate(frames):
            source = folder / f'src{index:06d}.jpg'
            source.write_bytes(data)
            sources.append(source)
        # Constant frame rate: each output tick shows the latest real frame at that instant.
        start, current = frames[0][0], 0
        for tick in range(int((end - start) * FPS) + 1):
            moment = start + tick / FPS
            while current + 1 < len(frames) and frames[current + 1][0] <= moment:
                current += 1
            os.link(sources[current], folder / f'{tick:06d}.jpg')
        out = ROOT / out if not Path(out).is_absolute() else Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        width, height = self.out_size
        filters = (f'{crop},' if crop else '') + f'scale={width}:{height}:flags=lanczos,format=yuv420p'
        subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-framerate', str(FPS), '-i', str(folder / '%06d.jpg'),
                        '-vf', filters, '-c:v', 'libx264', '-preset', 'slow', '-crf', '16', '-profile:v', 'high',
                        '-movflags', '+faststart', '-an', str(out)], check=True)
        print(f'{out}  ({len(frames)} frames, {end - frames[0][0]:.1f}s)')
        return out

    def close(self):
        if self.cdp:
            try:
                self.cdp.call('Page.stopScreencast', timeout=5)
            except Exception:
                pass
            self.cdp.close()
        if self.chrome:
            self.chrome.terminate()
            try:
                self.chrome.wait(5)
            except subprocess.TimeoutExpired:
                self.chrome.kill()
        shutil.rmtree(self.workdir, ignore_errors=True)
        if self.slot:
            self.slot.close()
            self.slot = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


SERVER_CODE = """
import flet as ft
from chargegrid_app.app import ASSETS_DIR, main
ft.run(main, view=None, host='127.0.0.1', port={port}, assets_dir=ASSETS_DIR)
"""

LOADING = {(34, 34, 34), (183, 183, 183), (255, 255, 255), (0, 0, 0)}


class AppSession(_Session):
    """The real Flet app (demo account, in-memory, never Supabase/ESP) at 402x874 pt, dark theme.

    route=None  -> the real login screen (nobody signed in)
    route='home', mode='consumer'|'vendor', params={...}, setup=[[method, path, body], ...]
                -> demo account already signed in, opened on that route (see app.capture_boot)
    """
    width, height, scale = 402, 874, 3
    out_size = (1080, 2348)

    def __init__(self, port, route=None, mode='consumer', params=None, setup=None, theme='dark'):
        super().__init__(port)
        if not free(port):
            raise SystemExit(f'port {port} is already in use')
        env = dict(os.environ)
        env.update({'CHARGEGRID_ENABLE_DEMO': '1', 'FLET_FORCE_WEB_SERVER': '1',
                    'FLET_APP_STORAGE_DATA': str(self.workdir / 'storage'),
                    'PYTHONPATH': os.pathsep.join(filter(None, [str(ROOT / 'apps/mobile/src'), env.get('PYTHONPATH')]))})
        if VECTOR_CLIENT.is_dir():
            env['FLET_WEB_PATH'] = str(VECTOR_CLIENT)
        if route:
            env.update({'CHARGEGRID_CAPTURE_ROUTE': route, 'CHARGEGRID_CAPTURE_MODE': mode,
                        'CHARGEGRID_CAPTURE_THEME': theme, 'CHARGEGRID_CAPTURE_PARAMS': json.dumps(params or {})})
            if setup:
                env['CHARGEGRID_CAPTURE_SETUP'] = json.dumps(setup)
        env.pop('OPENROUTER_API_KEY', None)
        self.log = open(self.workdir / 'server.log', 'w')  # noqa: SIM115
        self.server = subprocess.Popen([sys.executable, '-c', SERVER_CODE.format(port=port)], env=env, cwd=ROOT,
                                       stdout=self.log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            if not wait_http(f'http://127.0.0.1:{port}/', 60):
                raise RuntimeError('demo server did not start:\n' + (self.workdir / 'server.log').read_text()[-2000:])
            self._start_chrome()
            self._start_screencast()
            self.cdp.call('Page.navigate', url=f'http://127.0.0.1:{port}/')
            self._wait_rendered()
            self.labels()   # enables the semantics tree once
            time.sleep(1.0)
            self.record()
        except Exception:
            self.close()
            raise

    def _wait_rendered(self, timeout=240, settle=2.5):
        import io

        from PIL import Image
        end = time.time() + timeout
        settled = None
        while time.time() < end:
            time.sleep(0.6)
            data = base64.b64decode(self.cdp.call('Page.captureScreenshot', format='png')['data'])
            image = Image.open(io.BytesIO(data)).convert('RGB')
            h = image.height
            if all(image.getpixel((3, y)) not in LOADING for y in (h // 2, h // 3)):
                settled = settled or time.time()
                if time.time() - settled >= settle:
                    return
            else:
                settled = None
        raise RuntimeError('the Flet canvas never rendered')

    def tap(self, x, y, hold=0.09, wait=None):
        """Tap at css-pt (x, y): ripple + press/release, then PACE.after_tap."""
        self.cdp.js(f'window.__cg.touch({x},{y},260)')
        time.sleep(0.12)
        self._mouse('mouseMoved', x, y)
        self._mouse('mousePressed', x, y, clickCount=1)
        time.sleep(hold)
        self._mouse('mouseReleased', x, y, clickCount=1)
        time.sleep(PACE.after_tap if wait is None else wait)

    def tap_text(self, text, exact=False, index=0, wait=None, dx=0, dy=0):
        x, y = self.find(text, exact=exact, index=index)
        self.tap(x + dx, y + dy, wait=wait)

    def swipe(self, x1, y1, x2, y2, seconds=0.45, steps=18):
        """Finger drag (shows the touch ring at the start)."""
        self.cdp.js(f'window.__cg.touch({x1},{y1},{int(seconds * 1000)})')
        self._mouse('mouseMoved', x1, y1)
        self._mouse('mousePressed', x1, y1, clickCount=1)
        for i in range(1, steps + 1):
            t = i / steps
            self._mouse('mouseMoved', x1 + (x2 - x1) * t, y1 + (y2 - y1) * t, buttons=1)
            time.sleep(seconds / steps)
        self._mouse('mouseReleased', x2, y2, clickCount=1)
        time.sleep(0.6)

    def close(self):
        super().close()
        server = getattr(self, 'server', None)
        if server:
            try:
                os.killpg(server.pid, signal.SIGTERM)
            except OSError:
                pass
            self.log.close()


class WebSession(_Session):
    """owner-web (React painel) in Chrome at 1440x810 css px, scale 4/3 -> 1920x1080 frames, mouse cursor overlay."""
    width, height, scale = 1440, 810, 4 / 3
    out_size = (1920, 1080)

    def __init__(self, url, port=9500, local_storage=None):
        super().__init__(port)
        self.cursor_at = (self.width * 0.62, self.height * 0.62)
        try:
            self._start_chrome()
            self._start_screencast()
            self.cdp.call('Page.navigate', url=url)
            if local_storage:
                for key, value in local_storage.items():
                    self.cdp.js(f'localStorage.setItem({json.dumps(key)}, {json.dumps(value)})')
                self.cdp.call('Page.reload')
            self._wait_ready()
            self.record()
            self.cdp.js(f'window.__cg.cursor({self.cursor_at[0]},{self.cursor_at[1]},0)')
        except Exception:
            self.close()
            raise

    def _wait_ready(self, timeout=60):
        end = time.time() + timeout
        while time.time() < end:
            if self.cdp.js("document.readyState === 'complete' && document.body && document.body.innerText.length > 20"):
                time.sleep(1.5)
                return
            time.sleep(0.4)
        raise RuntimeError('page never became ready')

    def navigated(self):
        """Call after a full page navigation/reload so the cursor overlay comes back."""
        self._wait_ready()
        self.overlay()
        self.cdp.js(f'window.__cg.cursor({self.cursor_at[0]},{self.cursor_at[1]},0)')

    def move(self, x, y, seconds=None):
        seconds = PACE.move if seconds is None else seconds
        self.cdp.js(f'window.__cg.cursor({x},{y},{int(seconds * 1000)})')
        self._mouse('mouseMoved', x, y)
        time.sleep(seconds + 0.05)
        self.cursor_at = (x, y)

    def click(self, x, y, wait=None):
        self.move(x, y)
        time.sleep(0.12)
        self.cdp.js(f'window.__cg.click({x},{y})')
        self._mouse('mousePressed', x, y, clickCount=1)
        time.sleep(0.06)
        self._mouse('mouseReleased', x, y, clickCount=1)
        time.sleep(PACE.after_tap if wait is None else wait)

    def find_css(self, selector, index=0, timeout=15):
        end = time.time() + timeout
        while True:
            rect = self.cdp.js(f"""(() => {{ const n = document.querySelectorAll({json.dumps(selector)})[{index}];
                if (!n) return null; n.scrollIntoView({{block: 'nearest'}}); const r = n.getBoundingClientRect();
                return [r.left + r.width / 2, r.top + r.height / 2]; }})()""")
            if rect:
                return rect
            if time.time() > end:
                raise LookupError(selector)
            time.sleep(0.3)

    def click_css(self, selector, index=0, wait=None):
        x, y = self.find_css(selector, index)
        self.click(x, y, wait=wait)

    def click_text(self, text, exact=False, index=0, wait=None):
        x, y = self.find(text, exact=exact, index=index)
        self.click(x, y, wait=wait)

    def hover_text(self, text, exact=False, index=0):
        x, y = self.find(text, exact=exact, index=index)
        self.move(x, y)

    def labels(self):
        return self.cdp.js(r"""(() => { const out = [];
          document.querySelectorAll('a,button,input,select,textarea,[role],label,h1,h2,h3,th,td,li,span,p,div').forEach(n => {
            const r = n.getBoundingClientRect(); if (r.width < 2 || r.height < 2 || r.bottom < 0 || r.top > innerHeight) return;
            const own = [...n.childNodes].filter(c => c.nodeType === 3).map(c => c.textContent).join(' ').trim();
            const label = (n.getAttribute('aria-label') || n.getAttribute('placeholder') ||
                           (['A','BUTTON','INPUT','SELECT','TEXTAREA','LABEL'].includes(n.tagName) ? n.innerText : own) || '').trim();
            if (label) out.push({label, role: n.getAttribute('role') || n.tagName.toLowerCase(), x: r.left, y: r.top, w: r.width, h: r.height});
          }); return out; })()""") or []

    def type_into(self, selector, text, clear=True):
        self.click_css(selector, wait=0.25)
        if clear:
            self.cdp.js(f"(() => {{ const n = document.querySelector({json.dumps(selector)}); n.select && n.select(); }})()")
        self.type(text)
