#!/usr/bin/env python3

from __future__ import annotations

import argparse
import posixpath
import urllib.parse
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def _resolve_dataset_path(root: Path, request_path: str) -> Path | None:
    parsed = urllib.parse.urlsplit(request_path)
    normalized = posixpath.normpath(urllib.parse.unquote(parsed.path))
    parts = [part for part in normalized.split("/") if part and part != "."]
    if len(parts) < 5:
        return None
    if parts[0] != "datasets" or parts[1] != "local" or parts[3] != "resolve" or parts[4] != "main":
        return None

    dataset_id = parts[2]
    relative_parts = parts[5:]
    dataset_root = (root / dataset_id).resolve()
    target = dataset_root
    if relative_parts:
        target = (dataset_root.joinpath(*relative_parts)).resolve()

    try:
        target.relative_to(dataset_root)
    except ValueError:
        return None
    return target


def _build_handler(root: Path):
    class LocalDatasetHandler(SimpleHTTPRequestHandler):
        server_version = "SPARKLocalDatasetServer/1.0"

        def _write_healthz(self) -> None:
            body = b"ok\n"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def end_headers(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Range, Content-Type")
            self.send_header("Access-Control-Expose-Headers", "Accept-Ranges, Content-Length, Content-Range")
            super().end_headers()

        def do_OPTIONS(self) -> None:
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()

        def do_GET(self) -> None:
            if self.path == "/healthz":
                self._write_healthz()
                return
            super().do_GET()

        def do_HEAD(self) -> None:
            if self.path == "/healthz":
                self._write_healthz()
                return
            super().do_HEAD()

        def translate_path(self, path: str) -> str:
            resolved = _resolve_dataset_path(root, path)
            if resolved is None:
                return str(root / "__invalid__")
            return str(resolved)

        def list_directory(self, path: str):
            self.send_error(HTTPStatus.NOT_FOUND, "Directory listing is disabled")
            return None

        def log_message(self, format: str, *args) -> None:
            return

    return LocalDatasetHandler


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve local published datasets for the SPARK viewer.")
    parser.add_argument("--root", required=True, help="Published dataset root directory")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", required=True, type=int, help="Bind port")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    if not root.exists():
        raise SystemExit(f"Published dataset root does not exist: {root}")
    if not root.is_dir():
        raise SystemExit(f"Published dataset root is not a directory: {root}")

    handler = _build_handler(root)
    server = ReusableThreadingHTTPServer((args.host, args.port), handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
