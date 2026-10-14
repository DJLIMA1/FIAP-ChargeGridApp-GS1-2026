"""Serve o build estático do dashboard e faz proxy de ``/v1`` para uma API — como a Vercel fará.

Somente para testes locais (escuta em 127.0.0.1)::

    .venv/bin/python tools/serve_dashboard_web.py --port 8650 --api http://127.0.0.1:8631

``--login-tokens`` (opcional) aceita o JSON de ``tools/live_contract_check/tokens.py``: um
``POST /v1/auth/login`` com ``owner@live.test`` (ou ``driver@``/``rival@``) devolve o token local
correspondente, simulando o Supabase que não existe na API local. Nunca use fora de localhost.
"""

import argparse
import functools
import gzip
import json
import mimetypes
import posixpath
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SITE = ROOT_DIR / "apps" / "dashboard" / "build" / "vercel" / "public"
# Como a Vercel, comprime texto e wasm (zip/png já são comprimidos).
COMPRESSIBLE = (".js", ".mjs", ".wasm", ".json", ".html", ".otf", ".ttf", ".svg", ".bin", ".css")
FORWARDED_HEADERS = ("authorization", "content-type", "idempotency-key", "accept")
mimetypes.add_type("application/wasm", ".wasm")
mimetypes.add_type("text/javascript", ".mjs")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


OPENER = urllib.request.build_opener(_NoRedirect)


@functools.lru_cache(maxsize=64)
def compressed(path: Path, mtime: float) -> bytes:
    return gzip.compress(path.read_bytes(), compresslevel=6)


def make_handler(site: Path, api: str | None, login_tokens: dict):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(site), **kwargs)

        def log_message(self, format, *args):
            pass

        def end_headers(self):
            if not self.path.startswith("/v1/"):
                self.send_header("Cache-Control", "no-cache")
            super().end_headers()

        def do_GET(self):
            if self.path.startswith("/v1/"):
                return self.proxy()
            path = posixpath.normpath(urlsplit(self.path).path)
            target = site / path.lstrip("/")
            if not target.is_file() and not (target / "index.html").is_file():
                self.path, target = "/index.html", site / "index.html"  # fallback SPA, como o rewrite da Vercel
            elif target.is_dir():
                target = target / "index.html"
            if target.suffix in COMPRESSIBLE and "gzip" in self.headers.get("Accept-Encoding", ""):
                body = compressed(target, target.stat().st_mtime)
                return self.reply(200, body, [("Content-Type", self.guess_type(str(target))),
                                              ("Content-Encoding", "gzip")])
            return super().do_GET()

        def do_HEAD(self):
            return self.do_GET() if self.path.startswith("/v1/") else super().do_HEAD()

        def do_POST(self):
            return self.proxy()

        do_PUT = do_PATCH = do_DELETE = do_POST

        def reply(self, status, body=b"", headers=()):
            self.send_response(status)
            for key, value in headers:
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def proxy(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else None
            if self.command == "POST" and self.path == "/v1/auth/login" and login_tokens:
                email = (json.loads(body or b"{}").get("email") or "").strip().lower()
                role = email.split("@")[0] if email.endswith("@live.test") else None
                if role in login_tokens:
                    payload = {"access_token": login_tokens[role], "refresh_token": "local-" + role,
                               "expires_in": 3500, "token_type": "bearer", "user": {"email": email}}
                    return self.reply(200, json.dumps(payload).encode(), [("Content-Type", "application/json")])
            if not api:
                return self.reply(502, b'{"error":{"code":"no_api","message":"API local ausente"}}',
                                  [("Content-Type", "application/json")])
            request = urllib.request.Request(api.rstrip("/") + self.path, data=body, method=self.command)
            for name in FORWARDED_HEADERS:
                if self.headers.get(name):
                    request.add_header(name, self.headers[name])
            try:
                with OPENER.open(request, timeout=30) as response:
                    status, data, headers = response.status, response.read(), response.headers
            except urllib.error.HTTPError as error:
                status, data, headers = error.code, error.read(), error.headers
            except OSError as error:
                return self.reply(502, json.dumps({"error": {"code": "bad_gateway", "message": str(error)}}).encode(),
                                  [("Content-Type", "application/json")])
            passthrough = [(k, v) for k, v in headers.items()
                           if k.lower() in ("content-type", "content-disposition", "location", "retry-after")]
            return self.reply(status, data, passthrough)

    return Handler


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", type=Path, default=DEFAULT_SITE)
    parser.add_argument("--port", type=int, default=8650)
    parser.add_argument("--api", help="origem da API local, ex.: http://127.0.0.1:8631")
    parser.add_argument("--login-tokens", type=Path, help="JSON de tools/live_contract_check/tokens.py")
    args = parser.parse_args(argv)
    if args.api and urlsplit(args.api).hostname not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("Somente API local (localhost).")
    tokens = json.loads(args.login_tokens.read_text()) if args.login_tokens else {}
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(args.dir.resolve(), args.api, tokens))
    print(f"Dashboard em http://127.0.0.1:{args.port} (site: {args.dir}, API: {args.api or '—'})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
