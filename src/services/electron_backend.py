"""Electron 无 GUI 后端：完整 Flask API 服务器。

管理应用状态并暴露 REST 端点给 Electron 渲染进程。
端点清单与 electron/src/services/api-client.js 一一对齐。
"""
from __future__ import annotations

import atexit
import copy
import json
import os
import sys
import threading
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Flask, jsonify, request, send_file

import yaml

from src.models.annotation_marker import AnnotationMarker, marker_to_dict, serialize_annotations_for_web
from src.models.config import Settings, LLMConfig
from src.utils.file_utils import file_key
from src.utils.preview_ink_store import ink_pages_from_json, ink_pages_to_json, normalize_ink_pages
from src.utils.runtime import get_local_config_path


def _save_config_headless(settings: Settings) -> None:
    """保存配置到 local.yaml。"""
    local_path = get_local_config_path()
    local_path.parent.mkdir(parents=True, exist_ok=True)
    with open(local_path, "w", encoding="utf-8") as f:
        yaml.dump(settings.model_dump(), f, allow_unicode=True)


def dict_to_marker(data: Dict[str, Any]) -> AnnotationMarker:
    return AnnotationMarker(
        x=int(data.get("x", 0)),
        y=int(data.get("y", 0)),
        text=str(data.get("text", "")),
        color=str(data.get("color", "#7C3AED")),
        display_mode=str(data.get("display_mode", "marker")),
        original_text=str(data.get("original_text", "")),
        placement=str(data.get("placement", "right")),
        box_width=int(data.get("box_width", 0)),
        box_height=int(data.get("box_height", 0)),
        source_x=data.get("source_x"),
        source_y=data.get("source_y"),
        font_size=int(data.get("font_size", 12)),
        font_family=str(data.get("font_family", "")),
        text_orientation=str(data.get("text_orientation", "horizontal")),
        style_kind=str(data.get("style_kind", "inline")),
    )


# ---------------------------------------------------------------------------
# HeadlessApp — Electron 后端应用状态
# ---------------------------------------------------------------------------

class HeadlessApp:
    """无 GUI 应用状态管理器，模拟 App 类的核心字段和方法。"""

    PPT_IMPORT_ZOOM = 0.6

    def __init__(self, settings: Settings):
        self.settings = settings
        self.selected_files: List[str] = []
        self.current_file_index: int = -1

        self.pdf_doc = None
        self.current_page = 0
        self.total_pages = 0
        self.zoom_level = 1.0
        self.text_positions: Dict[int, list] = {}
        self.ocr_text_positions: Dict[int, List[dict]] = {}
        self.ocr_text_sources: Dict[int, str] = {}
        self.ppt_slide_emu = (9144000, 6858000)

        self.annotations: Dict[int, List[AnnotationMarker]] = {}
        self.annotations_by_file: Dict[str, Dict[int, List[AnnotationMarker]]] = {}
        self.preview_ink_by_file: Dict[str, Dict[int, List[dict]]] = {}
        self.project_file_path: Optional[str] = None
        self.converted_pdf_paths: Dict[str, str] = {}

        self.selected_marker: Optional[AnnotationMarker] = None

        from src.utils.undo_stack import UndoStack
        self._undo_stack: UndoStack = UndoStack(max_size=50)
        self._undo_restoring = False
        self._drag_undo_snap = None
        self._annotating = False
        self._autosave_timer: Optional[threading.Timer] = None
        self._autosave_lock = threading.Lock()
        self.annotate_job: Dict[str, Any] = {
            "status": "idle",
            "current": 0,
            "total": 0,
            "message": "",
            "error": "",
            "last_page": -1,
            "total_ann": 0,
            "pages_with_ann": 0,
        }
        self._annotate_job_lock = threading.Lock()

    # ── 文件操作 ──

    def _current_file_path(self) -> str:
        if 0 <= self.current_file_index < len(self.selected_files):
            return self.selected_files[self.current_file_index]
        return ""

    def _file_key(self, path: str) -> str:
        return file_key(path)

    def get_render_pdf_path(self, file_path: str = "") -> str:
        from src.utils.ppt_converter import get_render_pdf_path
        path = file_path or self._current_file_path()
        return get_render_pdf_path(path, self.converted_pdf_paths)

    def import_files(self, file_paths: List[str]) -> Dict[str, Any]:
        added = []
        for fp in file_paths:
            fp = os.path.normpath(fp)
            if os.path.isfile(fp) and fp not in self.selected_files:
                self.selected_files.append(fp)
                added.append(fp)

        if not added:
            return {"ok": True, "added": 0}

        if self.current_file_index < 0:
            self.current_file_index = 0
            self._load_file(self.selected_files[0])
            self._restore_file_annotations(self.selected_files[0])

        self.schedule_persist()
        return {"ok": True, "added": len(added), "files": self.selected_files}

    def select_file(self, index: int, page: int = None) -> None:
        if not (0 <= index < len(self.selected_files)):
            raise ValueError(f"文件索引越界: {index}")
        self._persist_current_annotations()
        self.current_file_index = index
        self._load_file(self.selected_files[index], page=page)
        self._restore_file_annotations(self.selected_files[index])
        self.schedule_persist()

    def remove_file(self, index: int) -> None:
        if not (0 <= index < len(self.selected_files)):
            raise ValueError(f"文件索引越界: {index}")
        removed = self.selected_files[index]
        key = self._file_key(removed)
        self._persist_current_annotations()
        self.selected_files.pop(index)
        self.annotations_by_file.pop(key, None)
        self.converted_pdf_paths.pop(key, None)

        if index == self.current_file_index:
            if self.pdf_doc:
                self.pdf_doc.close()
                self.pdf_doc = None
            if self.selected_files:
                new_index = min(index, len(self.selected_files) - 1)
                self.current_file_index = new_index
                self._load_file(self.selected_files[new_index])
                self._restore_file_annotations(self.selected_files[new_index])
            else:
                self.current_file_index = -1
                self.total_pages = 0
                self.current_page = 0
                self.annotations = {}
        elif index < self.current_file_index:
            self.current_file_index -= 1

        self.schedule_persist()

    def _load_file(self, file_path: str, page: int = None) -> None:
        lower = file_path.lower()
        if lower.endswith(".pdf"):
            self._load_pdf(file_path, page=page)
        elif lower.endswith((".ppt", ".pptx")):
            self._load_ppt(file_path, page=page)

    _load_file_content = _load_file

    def _get_stored_annotations(self, file_path: str):
        key = self._file_key(file_path)
        stored = self.annotations_by_file.get(key)
        if stored is not None:
            return stored
        for path, pages in self.annotations_by_file.items():
            if file_key(path) == key:
                return pages
        return {}

    def _load_pdf(self, file_path: str, page: int = None) -> None:
        import fitz
        if self.pdf_doc:
            self.pdf_doc.close()
        self.pdf_doc = fitz.open(file_path)
        self.total_pages = len(self.pdf_doc)
        self.current_page = max(0, min(page or 0, self.total_pages - 1))

    def _load_ppt(self, file_path: str, page: int = None) -> None:
        from src.utils.ppt_converter import convert_ppt_to_pdf
        pdf_path = convert_ppt_to_pdf(file_path)
        if pdf_path:
            self.converted_pdf_paths[self._file_key(file_path)] = pdf_path
            self._load_pdf(pdf_path, page=page)

    # ── 批注持久化 ──

    def _persist_current_annotations(self) -> None:
        path = self._current_file_path()
        if path:
            key = self._file_key(path)
            self.annotations_by_file[key] = {
                p: list(markers) for p, markers in self.annotations.items()
            }

    _persist_current_file_annotations = _persist_current_annotations

    def _restore_file_annotations(self, file_path: str) -> None:
        key = self._file_key(file_path)
        stored = self.annotations_by_file.get(key, {})
        self.annotations = {int(p): list(m) for p, m in stored.items()}
        self.selected_marker = None

    def _rekey_annotations_by_file(self) -> None:
        merged: Dict[str, Dict[int, List[AnnotationMarker]]] = {}
        for path, pages in self.annotations_by_file.items():
            fk = file_key(path)
            if fk in merged:
                for p, ms in pages.items():
                    merged[fk].setdefault(p, []).extend(ms)
            else:
                merged[fk] = dict(pages)
        self.annotations_by_file = merged

    # ── 批注 CRUD ──

    def add_annotation(self, page: int, data: Dict[str, Any]) -> Dict[str, Any]:
        page = int(page)
        marker = dict_to_marker(data)
        self.annotations.setdefault(page, []).append(marker)
        self._flush_persist()
        return {"ok": True, "index": len(self.annotations[page]) - 1}

    def update_annotation(self, page: int, index: int, data: Dict[str, Any]) -> Dict[str, Any]:
        page = int(page)
        index = int(index)
        markers = self.annotations.get(page, [])
        if not (0 <= index < len(markers)):
            raise ValueError(f"批注索引越界: page={page} index={index}")
        m = markers[index]
        for k, v in data.items():
            if k in ("page", "index"):
                continue
            if hasattr(m, k):
                setattr(m, k, v)
        self._flush_persist()
        return {"ok": True}

    def delete_annotation(self, page: int, index: int) -> Dict[str, Any]:
        page = int(page)
        index = int(index)
        markers = self.annotations.get(page, [])
        if not (0 <= index < len(markers)):
            raise ValueError(f"批注索引越界: page={page} index={index}")
        markers.pop(index)
        if not markers:
            self.annotations.pop(page, None)
        self._flush_persist()
        return {"ok": True}

    def delete_all_annotations(self, page: int) -> Dict[str, Any]:
        page = int(page)
        count = len(self.annotations.get(page, []))
        self.annotations.pop(page, None)
        self._flush_persist()
        return {"ok": True, "deleted": count}

    # ── 状态快照 ──

    def build_state(self) -> Dict[str, Any]:
        self._persist_current_annotations()
        current_path = self._current_file_path()
        pdf_path = self.get_render_pdf_path(current_path) if current_path else ""
        pdf_available = bool(pdf_path and os.path.isfile(pdf_path))
        pdf_token = ""
        if current_path and pdf_path and os.path.isfile(pdf_path):
            pdf_token = (
                f"{self.current_file_index}:"
                f"{os.path.abspath(current_path)}:"
                f"{os.path.abspath(pdf_path)}:"
                f"{os.path.getmtime(pdf_path)}"
            )

        ann_pages = serialize_annotations_for_web(self.annotations)

        fk = self._file_key(current_path) if current_path else ""
        ink_pages = {}
        if fk:
            raw = self.preview_ink_by_file.get(fk, {})
            ink_pages = {str(p): strokes for p, strokes in raw.items()} if raw else {}

        return {
            "files": self.selected_files,
            "current_file_index": self.current_file_index,
            "pdf_available": pdf_available,
            "pdf_token": pdf_token,
            "current_page": self.current_page,
            "total_pages": self.total_pages,
            "zoom_level": self.zoom_level,
            "annotations": ann_pages,
            "ink_pages": ink_pages,
        }

    # ── 撤销 ──

    def capture_undo_snapshot(self) -> Dict[str, Any]:
        fk = self._file_key(self._current_file_path()) if self._current_file_path() else ""
        if not fk:
            return {}
        ann_pages = self.annotations_by_file.get(fk, {})
        return {
            "file_key": fk,
            "page": self.current_page,
            "annotations": {
                str(p): [marker_to_dict(m) for m in markers]
                for p, markers in ann_pages.items()
            },
        }

    def push_undo(self) -> None:
        snap = self.capture_undo_snapshot()
        if snap:
            self._undo_stack.push(snap)

    def undo(self) -> Dict[str, Any]:
        snap = self._undo_stack.pop()
        if not snap:
            return {"ok": False, "message": "无可撤销操作"}
        fk = snap.get("file_key", "")
        ann_data = snap.get("annotations", {})
        restored: Dict[int, List[AnnotationMarker]] = {}
        for page_key, items in ann_data.items():
            restored[int(page_key)] = [dict_to_marker(d) for d in items]
        if fk:
            self.annotations_by_file[fk] = restored
        current_path = self._current_file_path()
        if current_path and self._file_key(current_path) == fk:
            self.annotations = {p: list(m) for p, m in restored.items()}
        return {"ok": True}

    # ── 会话持久化 ──

    def save_session(self) -> None:
        from src.services import project_service
        project_service.save_session(self)

    def update_file_list(self, files):
        pass

    def _show_annotations(self):
        pass

    def _update_annotation_list(self):
        pass

    def sync_web_preview(self):
        self._flush_persist()

    def schedule_persist(self) -> None:
        if not self.settings.app.auto_save:
            return
        with self._autosave_lock:
            if self._autosave_timer:
                self._autosave_timer.cancel()
            self._autosave_timer = threading.Timer(0.8, self._do_persist)
            self._autosave_timer.daemon = True
            self._autosave_timer.start()

    def _flush_persist(self) -> None:
        with self._autosave_lock:
            if self._autosave_timer:
                self._autosave_timer.cancel()
                self._autosave_timer = None
        self._do_persist()

    def _do_persist(self) -> None:
        self._persist_current_annotations()
        self.save_session()

    def update_status(self, msg: str):
        print(f"[status] {msg}")

    def update_progress(self, current: int, total: int, status: str):
        print(f"[progress] {current}/{total} {status}")


# ---------------------------------------------------------------------------
# Flask API 服务器
# ---------------------------------------------------------------------------

def create_api_server(app_state: HeadlessApp, port: int = 8765) -> Flask:
    """创建完整的 Flask API 服务器，端点对齐 api-client.js"""

    from flask import send_from_directory
    from src.utils.runtime import get_web_dir

    web_dir = str(get_web_dir())
    flask_app = Flask(__name__, static_folder=web_dir, static_url_path="")

    # ── GET / — Web 预览首页 ──
    @flask_app.get("/")
    def index():
        return send_from_directory(web_dir, "index.html")

    @flask_app.get("/favicon.ico")
    def favicon_ico():
        return send_from_directory(web_dir, "favicon.ico")

    # ── GET /api/state ──
    @flask_app.get("/api/state")
    def api_state():
        return jsonify(app_state.build_state())

    # ── GET /api/pdf ──
    @flask_app.get("/api/pdf")
    def api_pdf():
        path = app_state._current_file_path()
        if not path:
            return jsonify({"error": "no file selected"}), 404
        pdf_path = app_state.get_render_pdf_path(path)
        if not pdf_path or not os.path.isfile(pdf_path):
            return jsonify({"error": "pdf not available"}), 404
        response = send_file(pdf_path, mimetype="application/pdf")
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        return response

    # ── GET /api/annotations ──
    @flask_app.get("/api/annotations")
    def api_annotations():
        pages = serialize_annotations_for_web(app_state.annotations)
        return jsonify({
            "pages": pages,
            "current_page": app_state.current_page,
            "zoom_level": app_state.zoom_level,
        })

    # ── GET /api/ink ──
    @flask_app.get("/api/ink")
    def api_ink_get():
        fk = app_state._file_key(app_state._current_file_path()) if app_state._current_file_path() else ""
        pages = app_state.preview_ink_by_file.get(fk, {}) if fk else {}
        return jsonify({"pages": pages})

    # ── PUT /api/ink ──
    @flask_app.put("/api/ink")
    def api_ink_put():
        body = request.get_json(silent=True) or {}
        fk = app_state._file_key(app_state._current_file_path()) if app_state._current_file_path() else ""
        if fk:
            pages = body.get("pages") or {}
            app_state.preview_ink_by_file[fk] = normalize_ink_pages(pages)
            app_state.schedule_persist()
        return jsonify({"ok": True})

    # ── POST /api/ink/save ──
    @flask_app.post("/api/ink/save")
    def api_ink_save():
        return jsonify({"ok": True, "message": "ink save not yet supported in headless mode"})

    # ── POST /api/import ──
    @flask_app.post("/api/import")
    def api_import():
        body = request.get_json(silent=True) or {}
        files = body.get("files", [])
        if not files:
            return jsonify({"error": "no files provided"}), 400
        try:
            result = app_state.import_files(files)
            return jsonify(result)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ── POST /api/select-file ──
    @flask_app.post("/api/select-file")
    def api_select_file():
        body = request.get_json(silent=True) or {}
        index = body.get("index", 0)
        page = body.get("page")
        try:
            app_state.select_file(index, page=page)
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    # ── DELETE /api/file/remove ──
    @flask_app.delete("/api/file/remove")
    def api_file_remove():
        body = request.get_json(silent=True) or {}
        index = body.get("index", 0)
        try:
            app_state.remove_file(index)
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    # ── POST /api/navigate ──
    @flask_app.post("/api/navigate")
    def api_navigate():
        body = request.get_json(silent=True) or {}
        page = body.get("page", 0)
        app_state.current_page = max(0, min(page, app_state.total_pages - 1))
        app_state.schedule_persist()
        return jsonify({"ok": True, "page": app_state.current_page})

    # ── POST /api/annotate/page（单页批注）──
    @flask_app.post("/api/annotate/page")
    def api_annotate_page():
        body = request.get_json(silent=True) or {}
        page_num = body.get("page", 0)

        if app_state._annotating:
            return jsonify({"error": "正在批注中，请稍候"}), 409

        if not app_state.selected_files:
            return jsonify({"error": "请先导入文件"}), 400

        app_state._annotating = True
        try:
            source_path = app_state.selected_files[app_state.current_file_index]
            pdf_path = app_state.get_render_pdf_path(source_path)
            uses_inline = app_state.settings.annotation.mode == "overlay"

            if uses_inline:
                from src.services.inline_translation_service import generate_inline_markers_for_page
                markers = generate_inline_markers_for_page(app_state, page_num, app_state.settings.llm)
                if markers:
                    _apply_inline_markers(app_state, page_num, markers)
                    count = len(markers)
                else:
                    count = 0
            else:
                from src.services.annotation_service import AnnotationService
                service = AnnotationService(app_state.settings.llm)
                from src.models.page import Page
                page_obj = Page(page_number=page_num + 1)
                annotations = service.process_page(
                    page_obj,
                    pdf_path=pdf_path,
                    source_path=source_path,
                    total_pages=app_state.total_pages,
                )
                count = _apply_sidebar_annotations(app_state, page_num, annotations)

            app_state.schedule_persist()
            return jsonify({
                "ok": True,
                "message": f"第 {page_num + 1} 页批注完成，共 {count} 条",
                "count": count,
            })
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500
        finally:
            app_state._annotating = False

    # ── POST /api/annotate（批量批注，后台线程 + 进度轮询）──
    @flask_app.post("/api/annotate")
    def api_annotate_batch():
        body = request.get_json(silent=True) or {}
        start_page = int(body.get("start_page", 0))
        end_page = int(body.get("end_page", 0))

        if app_state._annotating or app_state.annotate_job.get("status") == "running":
            return jsonify({"error": "正在批注中，请稍候"}), 409

        if not app_state.selected_files:
            return jsonify({"error": "请先导入文件"}), 400

        job_total = end_page - start_page + 1
        if job_total <= 0:
            return jsonify({"error": "无效的页码范围"}), 400

        app_state._annotating = True
        with app_state._annotate_job_lock:
            app_state.annotate_job = {
                "status": "running",
                "current": 0,
                "total": job_total,
                "message": "准备中...",
                "error": "",
                "last_page": -1,
                "total_ann": 0,
                "pages_with_ann": 0,
            }

        def worker():
            try:
                _run_batch_annotate_worker(app_state, start_page, end_page)
            except Exception as e:
                traceback.print_exc()
                with app_state._annotate_job_lock:
                    app_state.annotate_job["status"] = "error"
                    app_state.annotate_job["error"] = str(e)
                    app_state.annotate_job["message"] = f"批注失败: {e}"
            finally:
                app_state._annotating = False

        threading.Thread(
            target=worker,
            daemon=True,
            name="batch-annotate",
        ).start()
        return jsonify({"ok": True, "started": True, "total": job_total})

    @flask_app.get("/api/annotate/progress")
    def api_annotate_progress():
        with app_state._annotate_job_lock:
            return jsonify(dict(app_state.annotate_job))

    # ── POST /api/annotation/add ──
    @flask_app.post("/api/annotation/add")
    def api_annotation_add():
        body = request.get_json(silent=True) or {}
        page = body.pop("page", app_state.current_page)
        try:
            result = app_state.add_annotation(page, body)
            return jsonify(result)
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    # ── PUT /api/annotation/update ──
    @flask_app.put("/api/annotation/update")
    def api_annotation_update():
        body = request.get_json(silent=True) or {}
        page = body.pop("page", app_state.current_page)
        index = body.pop("index", 0)
        try:
            result = app_state.update_annotation(page, index, body)
            return jsonify(result)
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    # ── POST/DELETE /api/annotation/delete（兼容旧路径）──
    def _handle_annotation_delete():
        body = request.get_json(silent=True) or {}
        page = int(body.get("page", app_state.current_page))
        index = int(body.get("index", 0))
        try:
            result = app_state.delete_annotation(page, index)
            return jsonify(result)
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    @flask_app.route("/api/annotation/delete", methods=["POST", "DELETE"])
    @flask_app.route("/api/annotation/remove", methods=["POST"])
    def api_annotation_delete():
        return _handle_annotation_delete()

    def _handle_annotation_delete_all():
        body = request.get_json(silent=True) or {}
        page = int(body.get("page", app_state.current_page))
        try:
            result = app_state.delete_all_annotations(page)
            return jsonify(result)
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    @flask_app.route("/api/annotation/delete-all", methods=["POST", "DELETE"])
    @flask_app.route("/api/annotation/remove-all", methods=["POST"])
    def api_annotation_delete_all():
        return _handle_annotation_delete_all()

    @flask_app.get("/api/health")
    def api_health():
        return jsonify({"ok": True, "backend": "electron", "api_version": 2})

    # ── POST /api/export ──
    @flask_app.post("/api/export")
    def api_export():
        body = request.get_json(silent=True) or {}
        output_path = body.get("output_path", "")
        if not output_path:
            return jsonify({"error": "请指定输出路径"}), 400

        try:
            import fitz
            from src.utils.pdf_annotation import draw_page_annotations

            app_state._persist_current_annotations()
            current_path = app_state._current_file_path()
            pdf_path = app_state.get_render_pdf_path(current_path) if current_path else ""
            if not pdf_path or not os.path.isfile(pdf_path):
                return jsonify({"error": "没有可导出的 PDF"}), 400

            doc = fitz.open(pdf_path)
            fk = app_state._file_key(current_path) if current_path else ""

            from src.utils.pdf_ink import draw_page_ink
            ink_pages = normalize_ink_pages(
                app_state.preview_ink_by_file.get(fk, {})
            ) if fk else {}

            for page_num in range(app_state.total_pages):
                page = doc[page_num]
                strokes = ink_pages.get(page_num, [])
                if strokes:
                    draw_page_ink(page, strokes)
                markers = app_state.annotations.get(page_num, [])
                if markers:
                    draw_page_annotations(page, markers)

            doc.save(output_path)
            doc.close()
            return jsonify({"ok": True, "path": output_path})
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    # ── POST /api/project/save ──
    @flask_app.post("/api/project/save")
    def api_project_save():
        body = request.get_json(silent=True) or {}
        path = body.get("path", "")
        if not path:
            return jsonify({"error": "请指定保存路径"}), 400
        try:
            from src.services.project_service import save_project
            app_state._persist_current_annotations()
            save_project(app_state, path)
            return jsonify({"ok": True, "path": path})
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    # ── POST /api/project/open ──
    @flask_app.post("/api/project/open")
    def api_project_open():
        body = request.get_json(silent=True) or {}
        path = body.get("path", "")
        if not path:
            return jsonify({"error": "请指定工程路径"}), 400
        try:
            from src.services.project_service import load_project
            load_project(app_state, path)
            return jsonify({"ok": True})
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    # ── GET /api/settings ──
    @flask_app.get("/api/settings")
    def api_settings_get():
        return jsonify(app_state.settings.model_dump())

    # ── PUT /api/settings ──
    @flask_app.put("/api/settings")
    def api_settings_put():
        body = request.get_json(silent=True) or {}
        try:
            app_state.settings = Settings(**body)
            _save_config_headless(app_state.settings)
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    # ── POST /api/undo ──
    @flask_app.post("/api/undo")
    def api_undo():
        result = app_state.undo()
        return jsonify(result)

    return flask_app


# ---------------------------------------------------------------------------
# 辅助函数：将 AI 批注结果写入 HeadlessApp 状态
# ---------------------------------------------------------------------------

def _update_annotate_job(app_state: HeadlessApp, **fields) -> None:
    with app_state._annotate_job_lock:
        app_state.annotate_job.update(fields)


def _run_batch_annotate_worker(app_state: HeadlessApp, start_page: int, end_page: int) -> None:
    """后台批量批注 worker"""
    job_total = end_page - start_page + 1
    source_path = app_state.selected_files[app_state.current_file_index]
    pdf_path = app_state.get_render_pdf_path(source_path)
    uses_inline = app_state.settings.annotation.mode == "overlay"
    total_ann = 0
    pages_with_ann = 0

    _update_annotate_job(
        app_state,
        status="running",
        current=0,
        total=job_total,
        message="准备中...",
        last_page=-1,
    )

    if uses_inline:
        from src.services.inline_translation_service import generate_inline_markers_for_page

        for offset, page_num in enumerate(range(start_page, end_page + 1)):
            done = offset + 1
            _update_annotate_job(
                app_state,
                current=done,
                message=f"翻译第 {page_num + 1} 页（{done}/{job_total}）...",
            )
            markers = generate_inline_markers_for_page(
                app_state, page_num, app_state.settings.llm
            )
            if markers:
                pages_with_ann += 1
                total_ann += len(markers)
                _apply_inline_markers(app_state, page_num, markers)
            app_state.schedule_persist()
            _update_annotate_job(
                app_state,
                current=done,
                message=f"第 {page_num + 1} 页翻译完成（{done}/{job_total}）",
                last_page=page_num,
                total_ann=total_ann,
                pages_with_ann=pages_with_ann,
            )
    else:
        from src.models.page import Page
        from src.services.annotation_service import AnnotationService

        service = AnnotationService(app_state.settings.llm)

        _update_annotate_job(app_state, message="正在将所选页转为图片...")

        def on_render(current: int, render_total: int) -> None:
            _update_annotate_job(
                app_state,
                message=f"正在渲染 {current}/{render_total} 页图片...",
            )

        page_images = service.render_document_page_images(
            total_pages=app_state.total_pages,
            pdf_path=pdf_path,
            pdf_doc=app_state.pdf_doc,
            source_path=source_path,
            on_progress=on_render,
            start_page=start_page,
            end_page=end_page,
        )
        images_by_page = {img.page_number: img for img in page_images}

        _update_annotate_job(app_state, message="正在理解文档上下文...")
        document_context = service.analyze_document_context(
            page_images,
            total_pages=app_state.total_pages,
            source_path=source_path,
            multi_agent=False,
            cache_friendly=True,
        )

        _update_annotate_job(app_state, message="全局理解完成，逐页批注...")

        for offset, page_num in enumerate(range(start_page, end_page + 1)):
            done = offset + 1
            _update_annotate_job(
                app_state,
                current=done,
                message=f"批注第 {page_num + 1} 页（{done}/{job_total}）...",
            )
            page_img = images_by_page.get(page_num)
            page_obj = Page(page_number=page_num + 1)
            if app_state.pdf_doc and 0 <= page_num < len(app_state.pdf_doc):
                page = app_state.pdf_doc[page_num]
                page_obj.width = page.rect.width
                page_obj.height = page.rect.height
            annotations = service.process_page(
                page_obj,
                pdf_path=pdf_path,
                pdf_doc=app_state.pdf_doc,
                source_path=source_path,
                document_context=document_context,
                total_pages=app_state.total_pages,
                page_image=page_img,
                cache_friendly=True,
            )
            count = _apply_sidebar_annotations(app_state, page_num, annotations)
            if count:
                pages_with_ann += 1
                total_ann += count
            app_state.schedule_persist()
            _update_annotate_job(
                app_state,
                current=done,
                message=f"第 {page_num + 1} 页批注完成（{done}/{job_total}）",
                last_page=page_num,
                total_ann=total_ann,
                pages_with_ann=pages_with_ann,
            )

    _update_annotate_job(
        app_state,
        status="done",
        current=job_total,
        total=job_total,
        message=(
            f"第 {start_page + 1}–{end_page + 1} 页批注完成，"
            f"共 {pages_with_ann} 页 {total_ann} 条"
        ),
        total_ann=total_ann,
        pages_with_ann=pages_with_ann,
    )


def _apply_inline_markers(app_state: HeadlessApp, page_num: int, markers: list) -> None:
    """将 inline_translation_service 返回的 marker 列表写入状态"""
    if page_num not in app_state.annotations:
        app_state.annotations[page_num] = []
    existing = [m for m in app_state.annotations[page_num] if not getattr(m, "original_text", "")]
    new_markers = []
    for m in markers:
        if isinstance(m, AnnotationMarker):
            new_markers.append(m)
        elif isinstance(m, dict):
            new_markers.append(dict_to_marker(m))
        else:
            new_markers.append(AnnotationMarker(
                x=getattr(m, "x", 0),
                y=getattr(m, "y", 0),
                text=getattr(m, "text", ""),
                color=getattr(m, "color", "#7C2D12"),
                display_mode=getattr(m, "display_mode", "inline"),
                original_text=getattr(m, "original_text", ""),
                placement=getattr(m, "placement", "right"),
                box_width=getattr(m, "box_width", 0),
                box_height=getattr(m, "box_height", 0),
                source_x=getattr(m, "source_x", None),
                source_y=getattr(m, "source_y", None),
                font_size=getattr(m, "font_size", 12),
                font_family=getattr(m, "font_family", ""),
                text_orientation=getattr(m, "text_orientation", "horizontal"),
                style_kind=getattr(m, "style_kind", "inline"),
            ))
    app_state.annotations[page_num] = existing + new_markers


def _apply_sidebar_annotations(app_state: HeadlessApp, page_num: int, annotations: list) -> int:
    """将 AnnotationService 返回的 Annotation 列表转为 AnnotationMarker 并写入"""
    if not annotations:
        return 0
    if page_num not in app_state.annotations:
        app_state.annotations[page_num] = []
    count = 0
    for ann in annotations:
        marker = AnnotationMarker(
            x=int(getattr(ann, "position_x", 50)),
            y=int(getattr(ann, "position_y", 50 + count * 30)),
            text=getattr(ann, "content", ""),
            color="#7C3AED",
            display_mode="marker",
            original_text=getattr(ann, "original_text", "") or "",
        )
        app_state.annotations[page_num].append(marker)
        count += 1
    return count


# ---------------------------------------------------------------------------
# 启动入口
# ---------------------------------------------------------------------------

def run_electron_backend(settings: Settings, port: int = 8765) -> None:
    """启动无 GUI 的 Electron 后端"""
    app_state = HeadlessApp(settings)

    from src.services.project_service import load_session, apply_snapshot
    session = load_session()
    if session:
        try:
            apply_snapshot(app_state, session)
            print(f"[electron] 已恢复上次会话 ({len(app_state.selected_files)} 个文件)")
        except Exception as e:
            print(f"[electron] 会话恢复失败: {e}")

    flask_app = create_api_server(app_state, port=port)

    atexit.register(app_state._flush_persist)

    print(f"[electron] Flask API 服务器启动: http://127.0.0.1:{port}")
    print(f"[electron] 等待 Electron 前端连接...")

    flask_app.run(host="127.0.0.1", port=port, threaded=True, use_reloader=False)
