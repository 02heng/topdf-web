"""Vercel Python 无服务器入口 — 统一处理 /api/* 路由。"""
from __future__ import annotations

import json
import sys
import traceback
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

_API_DIR = Path(__file__).resolve().parent
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

from web_handlers import (
    health,
    process_annotate_page,
    process_export,
    process_upload,
)


def _read_body(handler: BaseHTTPRequestHandler) -> bytes:
    length = int(handler.headers.get("Content-Length", 0))
    if length <= 0:
        return b""
    return handler.rfile.read(length)


def _parse_multipart(handler: BaseHTTPRequestHandler):
    import cgi

    env = {
        "REQUEST_METHOD": handler.command,
        "CONTENT_TYPE": handler.headers.get("Content-Type", ""),
        "CONTENT_LENGTH": handler.headers.get("Content-Length", "0"),
    }
    return cgi.FieldStorage(fp=handler.rfile, headers=handler.headers, environ=env)


class handler(BaseHTTPRequestHandler):
    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, data: bytes, content_type="application/pdf", status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/api/health", "/api"):
            return self._send_json(health())
        return self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            if path == "/api/upload":
                form = _parse_multipart(self)
                files = []
                if hasattr(form, "list") and form.list:
                    for field in form.list:
                        if field.name == "files" and getattr(field, "file", None):
                            files.append(field)
                elif form.filename:
                    files = [form]
                result = process_upload(files)
                return self._send_json(result)

            body_raw = _read_body(self)
            body = json.loads(body_raw.decode("utf-8") or "{}") if body_raw else {}

            if path == "/api/annotate/page":
                result = process_annotate_page(body)
                return self._send_json(result)

            if path == "/api/export":
                pdf_bytes = process_export(body)
                return self._send_bytes(pdf_bytes)

            return self._send_json({"error": f"unknown route: {path}"}, 404)
        except Exception as exc:
            traceback.print_exc()
            return self._send_json({"error": str(exc)}, 500)
