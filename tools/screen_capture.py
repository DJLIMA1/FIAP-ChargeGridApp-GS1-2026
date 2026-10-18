"""Screenshot harness for the ChargeGrid Flet app (demo account, 402x874 @2x).

Starts the demo app on its own port, opens it in headless Google Chrome, waits until the
Flutter canvas has really rendered (not the splash / a blank page), saves a PNG and stops
the server. Several instances can run at the same time as long as each uses its own --port.

    PYTHONPATH=apps/mobile/src .venv/bin/python tools/screen_capture.py \\
        --port 8901 --mode consumer --route home --out /tmp/home.png
    ... --route booking --param step=3 --param station_id=@first_station --out /tmp/x.png
    ... --route home --mode vendor --out /tmp/v.png --compare ref.png   # also writes x.compare.png

Options
  --port N          free TCP port for the temporary demo server (required for parallel runs)
  --mode            consumer | vendor (browsing mode after the automatic demo sign-in)
  --route NAME      route registered in navigation.SCREENS (home, stations, booking, wallet, ...)
  --param K=V       route parameter (repeatable); V is parsed as JSON when possible (3, true, "x");
                    @first_station / @first_connector resolve to the demo account's first ids
  --out FILE.png    output screenshot (804x1748 px: 402x874 pt at device scale 2)
  --theme           dark (default, the reference) | light
  --wait SECONDS    extra settle time after the first render (default 2); the harness also keeps
                    waiting up to --timeout seconds for the canvas to render
  --scroll PX       mouse-wheel scroll by PX css pixels before the screenshot (optional)
  --timeout SECONDS max time to wait for the first render (default 240; the machine may be loaded)
  --compare REF.png writes <out>.compare.png = reference | app side by side (+ a thin gap)

How it works: app.py has a startup hook (``capture_boot``) that is active only when the env var
CHARGEGRID_CAPTURE_ROUTE is set AND the demo is enabled; it signs in to the demo account, sets the
browsing mode and navigates to the route with the params. Chrome is driven through the DevTools
protocol (needs the ``websockets`` package that Flet already installs).
"""

import argparse
import base64
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHROME = os.environ.get('CHROME_BIN', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
SERVER_CODE = """
import flet as ft
from chargegrid_app.app import ASSETS_DIR, main
ft.run(main, view=None, host='127.0.0.1', port={port}, assets_dir=ASSETS_DIR)
"""


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


def start_server(args, workdir):
    env = dict(os.environ)
    env.update({
        'CHARGEGRID_ENABLE_DEMO': '1', 'FLET_FORCE_WEB_SERVER': '1', 'CHARGEGRID_CAPTURE_ROUTE': args.route,
        'CHARGEGRID_CAPTURE_MODE': args.mode, 'CHARGEGRID_CAPTURE_THEME': args.theme,
        'CHARGEGRID_CAPTURE_PARAMS': json.dumps(dict(item.split('=', 1) for item in args.param)),
        'FLET_APP_STORAGE_DATA': str(workdir / 'storage'),
        'PYTHONPATH': os.pathsep.join(filter(None, [str(ROOT / 'apps/mobile/src'), env.get('PYTHONPATH')])),
    })
    env.pop('OPENROUTER_API_KEY', None)
    log = open(workdir / 'server.log', 'w')  # noqa: SIM115 (closed by main)
    process = subprocess.Popen([sys.executable, '-c', SERVER_CODE.format(port=args.port)], env=env, cwd=ROOT,
                               stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    return process, log


def cdp_capture(args, workdir):
    """Open the app in headless Chrome and return PNG bytes once the canvas is rendered."""
    import io

    from PIL import Image
    from websockets.sync.client import connect

    debug_port = None
    for candidate in range(args.port + 1000, args.port + 1100):
        if free(candidate):
            debug_port = candidate
            break
    profile = workdir / 'chrome'
    chrome = subprocess.Popen([
        CHROME, '--headless=new', '--hide-scrollbars', '--force-device-scale-factor=2', '--window-size=402,874',
        f'--remote-debugging-port={debug_port}', f'--user-data-dir={profile}', '--no-first-run',
        '--no-default-browser-check', '--disable-background-timer-throttling', '--disable-renderer-backgrounding',
        '--enable-unsafe-swiftshader', '--use-angle=swiftshader', '--ignore-gpu-blocklist', 'about:blank',
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        if not wait_http(f'http://127.0.0.1:{debug_port}/json/version', 20):
            raise RuntimeError('Chrome did not start')
        targets = json.load(urllib.request.urlopen(f'http://127.0.0.1:{debug_port}/json'))
        page = next(item for item in targets if item.get('type') == 'page')
        with connect(page['webSocketDebuggerUrl'], max_size=64 * 1024 * 1024) as socket_:
            counter = [0]

            def call(method, **params):
                counter[0] += 1
                socket_.send(json.dumps({'id': counter[0], 'method': method, 'params': params}))
                while True:
                    message = json.loads(socket_.recv(timeout=60))
                    if message.get('id') == counter[0]:
                        return message.get('result', {})

            call('Page.enable')
            call('Emulation.setDeviceMetricsOverride', width=402, height=874, deviceScaleFactor=2, mobile=False)
            call('Page.navigate', url=f'http://127.0.0.1:{args.port}/')
            end = time.time() + args.timeout
            settled = None
            png = None
            data = None
            while time.time() < end:
                time.sleep(0.7)
                shot = call('Page.captureScreenshot', format='png', captureBeyondViewport=False)
                data = base64.b64decode(shot['data'])
                image = Image.open(io.BytesIO(data)).convert('RGB')
                if rendered(image):
                    settled = settled or time.time()
                    png = data
                    if time.time() - settled >= args.wait:
                        break
                else:
                    settled = None
            if png is None:
                if data:
                    Path(args.out).with_suffix('.fail.png').write_bytes(data)
                raise RuntimeError('the Flet canvas never rendered the app (still blank/splash)')
            if args.scroll:
                call('Input.dispatchMouseEvent', type='mouseWheel', x=200, y=400, deltaX=0, deltaY=args.scroll)
                time.sleep(1.2)
                shot = call('Page.captureScreenshot', format='png')
                png = base64.b64decode(shot['data'])
            elif settled is not None and time.time() - settled >= args.wait:
                shot = call('Page.captureScreenshot', format='png')
                png = base64.b64decode(shot['data'])
            return png
    finally:
        chrome.terminate()
        try:
            chrome.wait(5)
        except subprocess.TimeoutExpired:
            chrome.kill()


LOADING_COLOURS = {(34, 34, 34), (183, 183, 183), (255, 255, 255), (0, 0, 0)}


def rendered(image):
    """True when the screenshot shows the app and not Flet's splash (#222), Flutter's grey
    first frame (#B7B7B7) or a blank page. Samples pixels on the left edge, mid-height,
    which are always page background once the app has painted (light page bg is #F2F2F3)."""
    _, height = image.size
    samples = [image.getpixel((2, y)) for y in (height // 2, height // 3)]
    return all(pixel not in LOADING_COLOURS for pixel in samples)


def compare(reference, shot, target):
    from PIL import Image
    ref = Image.open(reference).convert('RGB')
    app = Image.open(shot).convert('RGB')
    height = max(ref.height, app.height)
    sheet = Image.new('RGB', (ref.width + app.width + 24, height), (255, 0, 255))
    sheet.paste(ref, (0, 0))
    sheet.paste(app, (ref.width + 24, 0))
    sheet.save(target)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--mode', choices=('consumer', 'vendor'), default='consumer')
    parser.add_argument('--route', default='home')
    parser.add_argument('--param', action='append', default=[], metavar='K=V')
    parser.add_argument('--out', required=True)
    parser.add_argument('--theme', choices=('dark', 'light'), default='dark')
    parser.add_argument('--wait', type=float, default=2.0)
    parser.add_argument('--timeout', type=float, default=240.0)
    parser.add_argument('--scroll', type=int, default=0)
    parser.add_argument('--compare')
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))  # still stop the server/Chrome on kill
    if not free(args.port):
        sys.exit(f'port {args.port} is already in use')
    workdir = Path(tempfile.mkdtemp(prefix=f'cg_capture_{args.port}_'))
    server, log = start_server(args, workdir)
    try:
        if not wait_http(f'http://127.0.0.1:{args.port}/', 40):
            raise RuntimeError('demo server did not start:\n' + (workdir / 'server.log').read_text()[-2000:])
        png = None
        for attempt in range(2):
            try:
                png = cdp_capture(args, workdir)
                break
            except RuntimeError as error:
                if attempt:
                    raise
                print(f'retrying: {error}', file=sys.stderr)
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(png)
        print(out)
        if args.compare:
            print(compare(args.compare, out, out.with_suffix('.compare.png')))
    except Exception:
        print((workdir / 'server.log').read_text()[-3000:], file=sys.stderr)
        raise
    finally:
        try:
            os.killpg(server.pid, signal.SIGTERM)
        except OSError:
            pass
        log.close()
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == '__main__':
    main()
