#!/usr/bin/env python3
"""本地开发服务器：静态文件 (public/) + /api/* 路由。"""
from __future__ import annotations

import json
import mimetypes
import socket
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "public"
API_DIR = ROOT / "api"

sys.path.insert(0, str(API_DIR))
from web_handlers import health, process_annotate_page, process_export, process_upload  # noqa: E402


class DevHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC), **kwargs)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length > 0 else b""

    def _handle_api(self):
        path = urlparse(self.path).path
        try:
            if path == "/api/health" and self.command == "GET":
                return self._send_json(health())

            if path == "/api/upload" and self.command == "POST":
                import cgi

                env = {
                    "REQUEST_METHOD": self.command,
                    "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                    "CONTENT_LENGTH": self.headers.get("Content-Length", "0"),
                }
                form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ=env)
                files = []
                if hasattr(form, "list") and form.list:
                    for field in form.list:
                        if field.name == "files" and getattr(field, "file", None):
                            files.append(field)
                elif form.filename:
                    files = [form]
                return self._send_json(process_upload(files))

            body_raw = self._read_body()
            body = json.loads(body_raw.decode("utf-8") or "{}") if body_raw else {}

            if path == "/api/annotate/page" and self.command == "POST":
                return self._send_json(process_annotate_page(body))

            if path == "/api/export" and self.command == "POST":
                pdf_bytes = process_export(body)
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(pdf_bytes)
                return

            return self._send_json({"error": f"unknown route: {path}"}, 404)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            return self._send_json({"error": str(exc)}, 500)

    def do_GET(self):
        if urlparse(self.path).path.startswith("/api/"):
            return self._handle_api()
        if self.path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        if urlparse(self.path).path.startswith("/api/"):
            return self._handle_api()
        return self.send_error(405)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()


def _port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def main():
    port = 3000
    host = "127.0.0.1"
    if _port_in_use(host, port):
        print(f"[dev] 错误: {host}:{port} 已被占用，页面会打不开或一直加载。")
        print("[dev] 请先结束旧的 dev 进程，再重新运行 npm run dev。")
        print("[dev] PowerShell 示例: Get-NetTCPConnection -LocalPort 3000 | Select OwningProcess")
        raise SystemExit(1)

    server = HTTPServer((host, port), DevHandler)
    print(f"[dev] TO PDF Web: http://{host}:{port}")
    print("[dev] 按 Ctrl+C 停止")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[dev] 已停止")


if __name__ == "__main__":
    main()
