"""从 PDF 页面图片中 OCR 提取带坐标的文字块（图表、扫描页）。"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import tempfile
from collections import defaultdict
from typing import Any, Dict, List, Optional, TYPE_CHECKING

import fitz

from src.utils.block_font_size import font_size_from_line_height

if TYPE_CHECKING:
    from src.models.config import LLMConfig

OCR_DPI = 280
MIN_BLOCK_CHARS = 2
MIN_OCR_BLOCKS_TARGET = 12
VISION_OCR_MIN_BLOCKS = 15
TEXT_PARAGRAPHS_SKIP_IMAGE_OCR = 5

VISION_OCR_BLOCKS_PROMPT = """你是文档页面文字定位引擎。识别整张幻灯片/PDF页面上每一处可见英文（含图表内文字）。

【图表 — 必须逐项列出】
折线图、坐标图、流程图、表格中的文字必须单独成块，例如：
- 坐标轴名：Costs、Volume
- 每条曲线旁标签：Fixed-position、Functional、Cell、Line
- 分区标题：Use fixed-position、Use functional、Use cell、Use line
不得把整张图合并成一块；每个可见英文词组各一块，x/y/width/height 必须框住该词在画面中的真实位置。

【分行规则】
1. 独立一行 = 一个块；列表每一项单独一块。
2. 仅同一段落自动折行才可合并为一个块（text 内用 \\n）。
3. 不要漏掉页面中部、右侧大图区域内的文字。

返回 JSON 数组，每项：
{"text":"原文","x":0.12,"y":0.34,"width":0.08,"height":0.02}
x,y,width,height 为相对整页宽高的比例（0~1，左上为原点）。只输出 JSON 数组，不要 Markdown。"""


def _scale_blocks_to_pdf(
    blocks: List[Dict[str, Any]],
    img_w: float,
    img_h: float,
    page_w: float,
    page_h: float,
) -> List[Dict[str, Any]]:
    if img_w <= 0 or img_h <= 0:
        return []
    sx = page_w / img_w
    sy = page_h / img_h
    out: List[Dict[str, Any]] = []
    for b in blocks:
        text = (b.get("text") or "").strip()
        if len(text) < MIN_BLOCK_CHARS:
            continue
        x = float(b.get("x", 0)) * sx
        y = float(b.get("y", 0)) * sy
        w = max(float(b.get("width", 0)) * sx, 8)
        h = max(float(b.get("height", 0)) * sy, 8)
        out.append(
            {
                "text": text,
                "x": x,
                "y": y,
                "width": w,
                "height": h,
                "font_size": font_size_from_line_height(h),
            }
        )
    return out


def _blocks_from_liteparse_image(png_bytes: bytes, page_w: float, page_h: float) -> List[Dict[str, Any]]:
    try:
        from liteparse import LiteParse
    except ImportError:
        return []

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp.write(png_bytes)
        tmp_path = tmp.name

    try:
        parser = LiteParse(ocr_enabled=True)
        result = parser.parse(tmp_path)
        if not result.pages:
            return []
        page_data = result.pages[0]
        img_w = float(getattr(page_data, "width", 0) or page_w)
        img_h = float(getattr(page_data, "height", 0) or page_h)
        raw: List[Dict[str, Any]] = []
        for item in getattr(page_data, "text_items", None) or []:
            text = (getattr(item, "text", "") or "").strip()
            if not text:
                continue
            raw.append(
                {
                    "text": text,
                    "x": float(getattr(item, "x", 0)),
                    "y": float(getattr(item, "y", 0)),
                    "width": float(getattr(item, "width", 0) or 8),
                    "height": float(getattr(item, "height", 0) or 8),
                }
            )
        return _scale_blocks_to_pdf(raw, img_w, img_h, page_w, page_h)
    except Exception:
        return []
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _group_tesseract_lines(data: dict, img_w: float, img_h: float) -> List[Dict[str, Any]]:
    """将 Tesseract 词级结果按行合并为文本块。"""
    lines: Dict[tuple, List[dict]] = defaultdict(list)
    n = len(data.get("text", []))
    for i in range(n):
        text = (data["text"][i] or "").strip()
        if not text:
            continue
        try:
            conf = int(float(data["conf"][i]))
        except (ValueError, TypeError):
            conf = -1
        if conf < 15:
            continue
        key = (
            int(data.get("block_num", [0])[i]),
            int(data.get("par_num", [0])[i]),
            int(data.get("line_num", [0])[i]),
        )
        lines[key].append(
            {
                "text": text,
                "left": float(data["left"][i]),
                "top": float(data["top"][i]),
                "width": float(data["width"][i]),
                "height": float(data["height"][i]),
            }
        )

    raw: List[Dict[str, Any]] = []
    for parts in lines.values():
        if not parts:
            continue
        parts.sort(key=lambda p: p["left"])
        text = " ".join(p["text"] for p in parts).strip()
        if len(text) < MIN_BLOCK_CHARS:
            continue
        x0 = min(p["left"] for p in parts)
        y0 = min(p["top"] for p in parts)
        x1 = max(p["left"] + p["width"] for p in parts)
        y1 = max(p["top"] + p["height"] for p in parts)
        raw.append(
            {
                "text": text,
                "x": x0,
                "y": y0,
                "width": max(x1 - x0, 8),
                "height": max(y1 - y0, 8),
            }
        )
    return raw


def _configure_tesseract_cmd() -> bool:
    """Windows 上尝试常见安装路径。"""
    try:
        import pytesseract
    except ImportError:
        return False
    cmd = getattr(pytesseract.pytesseract, "tesseract_cmd", None)
    if cmd and os.path.isfile(cmd):
        return True
    if os.name != "nt":
        return True
    for candidate in (
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ):
        if os.path.isfile(candidate):
            pytesseract.pytesseract.tesseract_cmd = candidate
            return True
    return False


def _tesseract_usable() -> bool:
    try:
        import pytesseract

        _configure_tesseract_cmd()
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def vision_native_for_inline(llm_config: Optional["LLMConfig"]) -> bool:
    """当前配置是否用全模态识图代替 Tesseract/LiteParse OCR（原位翻译补块）。"""
    if not _vision_ocr_usable(llm_config):
        return False
    provider = llm_config.provider
    if provider in ("openai", "ollama", "xiaomi", "agnes"):
        return True
    if provider == "deepseek":
        name = (llm_config.deepseek.model or "deepseek-v4-pro").lower()
        return any(k in name for k in ("vl", "vision", "janus"))
    return False


def _vision_ocr_usable(llm_config: Optional["LLMConfig"]) -> bool:
    if not llm_config:
        return False
    provider = llm_config.provider
    if provider == "openai":
        return bool(llm_config.openai.api_key)
    if provider == "ollama":
        return bool(llm_config.ollama.base_url)
    if provider == "deepseek":
        return bool(llm_config.deepseek.api_key)
    if provider == "xiaomi":
        return bool(llm_config.xiaomi.api_key)
    if provider == "agnes":
        return bool(llm_config.agnes.api_key)
    return False


def _ocr_empty_status_hint(
    llm_config: Optional["LLMConfig"],
    *,
    text_layer_paragraphs: int = 0,
) -> str:
    if text_layer_paragraphs > 0:
        return (
            f"图内 OCR 未补充到文字，已使用页面文字层（{text_layer_paragraphs} 段）"
        )
    parts = ["本页图内 OCR 未识别到文字。"]
    if not _tesseract_usable():
        parts.append("可安装 Tesseract（含 eng/chi_sim 语言包）")
    if _vision_ocr_usable(llm_config):
        prov = getattr(llm_config, "provider", "")
        if prov == "xiaomi":
            parts.append("或确认小米 MiMo API Key 有效（识图请用 mimo-v2.5）")
        else:
            parts.append("或确认已配置 OpenAI/Ollama/小米 视觉模型")
    elif llm_config and llm_config.provider == "deepseek":
        parts.append("DeepSeek 文本接口不支持识图，请改用 OpenAI 或 Ollama 视觉")
    else:
        parts.append("或在「系统 API 设置」中配置带视觉的模型")
    return "；".join(parts)


def _blocks_from_tesseract(png_bytes: bytes, page_w: float, page_h: float) -> List[Dict[str, Any]]:
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return []

    if not _configure_tesseract_cmd():
        return []

    try:
        image = Image.open(io.BytesIO(png_bytes))
        img_w, img_h = image.size
        for psm in (11, 6, 3):
            try:
                config = f"--psm {psm} --oem 3"
                data = pytesseract.image_to_data(
                    image,
                    lang="eng+chi_sim",
                    config=config,
                    output_type=pytesseract.Output.DICT,
                )
                raw = _group_tesseract_lines(data, img_w, img_h)
                blocks = _scale_blocks_to_pdf(raw, img_w, img_h, page_w, page_h)
                if len(blocks) >= MIN_OCR_BLOCKS_TARGET:
                    return blocks
            except Exception:
                continue
        data = pytesseract.image_to_data(
            image, lang="eng+chi_sim", output_type=pytesseract.Output.DICT
        )
        raw = _group_tesseract_lines(data, img_w, img_h)
        return _scale_blocks_to_pdf(raw, img_w, img_h, page_w, page_h)
    except Exception:
        return []


def _parse_vision_ocr_json(text: str, page_w: float, page_h: float) -> List[Dict[str, Any]]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        t = (item.get("text") or "").strip()
        if len(t) < MIN_BLOCK_CHARS:
            continue
        x = float(item.get("x", 0))
        y = float(item.get("y", 0))
        w = float(item.get("width", 0.05))
        h = float(item.get("height", 0.02))
        if w <= 1.5 and h <= 1.5:
            x, y, w, h = x * page_w, y * page_h, w * page_w, h * page_h
        h = max(h, 8)
        out.append(
            {
                "text": t,
                "x": max(0, x),
                "y": max(0, y),
                "width": max(w, 8),
                "height": h,
                "font_size": font_size_from_line_height(h),
            }
        )
    return out


def _vision_extract_max_tokens(llm_config: "LLMConfig") -> int:
    """图表页需返回大量 JSON 块，避免 MiMo 等模型输出被截断。"""
    cap = 8192
    if llm_config.provider == "xiaomi":
        cap = max(cap, int(llm_config.xiaomi.max_tokens or 4096))
    elif llm_config.provider == "openai":
        cap = max(cap, int(llm_config.openai.max_tokens or 4096))
    elif llm_config.provider == "agnes":
        cap = max(cap, int(llm_config.agnes.max_tokens or 4096))
    return min(cap, 16384)


def extract_page_vision_blocks(
    page: fitz.Page,
    llm_config: "LLMConfig",
) -> List[Dict[str, Any]]:
    """整页渲染后由全模态模型返回带坐标的文字块（不用本地 OCR）。"""
    page_w = page.rect.width
    page_h = page.rect.height
    zoom = OCR_DPI / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    image_b64 = base64.b64encode(pix.tobytes("png")).decode("utf-8")
    blocks = _blocks_from_vision_llm(
        image_b64,
        page_w,
        page_h,
        llm_config,
        max_tokens=_vision_extract_max_tokens(llm_config),
    )
    if len(blocks) < 8:
        retry = _blocks_from_vision_llm(
            image_b64,
            page_w,
            page_h,
            llm_config,
            max_tokens=_vision_extract_max_tokens(llm_config),
            prompt_suffix="\n请特别补全图表区域（Costs、Volume、Fixed-position、Functional、Cell、Line、Use …）内每个英文标签，单独成块。",
        )
        if len(retry) > len(blocks):
            blocks = retry
    return blocks


def _blocks_from_vision_llm(
    image_b64: str,
    page_w: float,
    page_h: float,
    llm_config: "LLMConfig",
    *,
    max_tokens: Optional[int] = None,
    prompt_suffix: str = "",
) -> List[Dict[str, Any]]:
    try:
        from src.services.vision_annotation_service import VisionAnnotationService
    except ImportError:
        return []

    svc = VisionAnnotationService(llm_config)
    provider = llm_config.provider
    prompt = VISION_OCR_BLOCKS_PROMPT + (prompt_suffix or "")
    tok = max_tokens or _vision_extract_max_tokens(llm_config)
    raw = ""
    try:
        if provider == "openai":
            raw = svc._call_openai_compatible_vision(
                api_key=llm_config.openai.api_key,
                base_url="",
                model=llm_config.openai.model,
                temperature=llm_config.openai.temperature,
                max_tokens=tok,
                images_b64=[image_b64],
                prompt=prompt,
            )
        elif provider == "xiaomi":
            cfg = llm_config.xiaomi
            raw = svc._call_openai_compatible_vision(
                api_key=cfg.api_key,
                base_url=cfg.base_url,
                model=svc._xiaomi_api_model(),
                temperature=cfg.temperature,
                max_tokens=tok,
                images_b64=[image_b64],
                prompt=prompt,
            )
        elif provider == "ollama":
            raw = svc._call_ollama_vision_multi([image_b64], prompt)
        elif provider == "deepseek":
            try:
                raw = svc._call_openai_compatible_vision(
                    api_key=llm_config.deepseek.api_key,
                    base_url=llm_config.deepseek.base_url,
                    model=llm_config.deepseek.model,
                    temperature=llm_config.deepseek.temperature,
                    max_tokens=tok,
                    images_b64=[image_b64],
                    prompt=prompt,
                )
            except Exception:
                raw = ""
        elif provider == "agnes":
            cfg = llm_config.agnes
            raw = svc._call_openai_compatible_vision(
                api_key=cfg.api_key,
                base_url=cfg.base_url or "https://apihub.agnes-ai.com/v1",
                model=svc._agnes_api_model(),
                temperature=cfg.temperature,
                max_tokens=tok,
                images_b64=[image_b64],
                prompt=prompt,
            )
    except Exception:
        return []

    return _parse_vision_ocr_json(raw, page_w, page_h)


def _ocr_region(
    page: fitz.Page,
    clip: fitz.Rect,
    page_w: float,
    page_h: float,
    zoom: float,
) -> List[Dict[str, Any]]:
    """对页面局部区域 OCR，坐标换算回整页 PDF 点。"""
    matrix = fitz.Matrix(zoom, zoom)
    try:
        pix = page.get_pixmap(matrix=matrix, clip=clip, alpha=False)
    except Exception:
        return []
    png_bytes = pix.tobytes("png")
    blocks = _blocks_from_liteparse_image(png_bytes, clip.width, clip.height)
    blocks = _merge_blocks(blocks, _blocks_from_tesseract(png_bytes, clip.width, clip.height))
    offset_x = clip.x0
    offset_y = clip.y0
    shifted: List[Dict[str, Any]] = []
    for b in blocks:
        shifted.append(
            {
                "text": b["text"],
                "x": float(b["x"]) + offset_x,
                "y": float(b["y"]) + offset_y,
                "width": b["width"],
                "height": b["height"],
            }
        )
    return shifted


def extract_page_ocr_blocks(
    page: fitz.Page,
    *,
    pdf_doc: Optional[fitz.Document] = None,
    page_num: int = 0,
    llm_config: Optional["LLMConfig"] = None,
    use_vision_fallback: bool = True,
) -> List[Dict[str, Any]]:
    """渲染当前页并 OCR（整页 + 下半区加强），返回 PDF 点坐标下的文字块。"""
    page_w = page.rect.width
    page_h = page.rect.height
    zoom = OCR_DPI / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    png_bytes = pix.tobytes("png")
    image_b64 = base64.b64encode(png_bytes).decode("utf-8")

    blocks = _blocks_from_liteparse_image(png_bytes, page_w, page_h)
    blocks = _merge_blocks(blocks, _blocks_from_tesseract(png_bytes, page_w, page_h))

    # 幻灯片/教材：页眉、中部大图、下半区正文 — 中部带覆盖常见坐标图与流程图
    bands = (
        (0.0, 0.0, 1.0, 0.38),
        (0.05, 0.10, 0.95, 0.88),
        (0.0, 0.32, 1.0, 0.72),
        (0.0, 0.52, 1.0, 1.0),
    )
    for x0r, y0r, x1r, y1r in bands:
        clip = fitz.Rect(
            page_w * x0r,
            page_h * y0r,
            page_w * x1r,
            page_h * y1r,
        )
        blocks = _merge_blocks(blocks, _ocr_region(page, clip, page_w, page_h, zoom))

    if use_vision_fallback and llm_config and len(blocks) < VISION_OCR_MIN_BLOCKS:
        vision_blocks = _blocks_from_vision_llm(image_b64, page_w, page_h, llm_config)
        blocks = _merge_blocks(blocks, vision_blocks)

    return blocks


def _merge_blocks(
    primary: List[Dict[str, Any]],
    extra: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if not extra:
        return list(primary)
    if not primary:
        return list(extra)
    return _dedupe_blocks(primary + extra)


def _dedupe_blocks(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    kept: List[Dict[str, Any]] = []
    seen: List[tuple] = []
    for b in blocks:
        text = (b.get("text") or "").strip()
        if len(text) < MIN_BLOCK_CHARS:
            continue
        cy = float(b["y"]) + float(b["height"]) / 2
        cx = float(b["x"]) + float(b["width"]) / 2
        key = (round(cx, 0), round(cy, 0), text[:48].lower())
        if key in seen:
            continue
        seen.append(key)
        kept.append(b)
    kept.sort(key=lambda b: (round(float(b["y"]), 1), float(b["x"])))
    return kept


def ensure_page_ocr_positions(
    app,
    page_num: int,
    llm_config: Optional["LLMConfig"] = None,
    *,
    force: bool = False,
    text_layer_paragraphs: int = 0,
) -> List[Dict[str, Any]]:
    """识别页内文字块并缓存到 app.ocr_text_positions。全模态时走视觉识图，否则走本地 OCR。"""
    if not getattr(app, "ocr_text_positions", None):
        app.ocr_text_positions = {}
    if not getattr(app, "ocr_text_sources", None):
        app.ocr_text_sources = {}

    use_vision = vision_native_for_inline(llm_config)
    source_tag = "vision" if use_vision else "ocr"

    if not force and page_num in app.ocr_text_positions:
        if app.ocr_text_sources.get(page_num) == source_tag:
            cached = app.ocr_text_positions.get(page_num)
            if cached is not None:
                return cached
        clear_page_ocr_cache(app, page_num)

    if not app.pdf_doc or page_num < 0 or page_num >= app.total_pages:
        app.ocr_text_positions[page_num] = []
        app.ocr_text_sources[page_num] = source_tag
        return []

    page = app.pdf_doc[page_num]
    if use_vision and llm_config:
        if hasattr(app, "update_status"):
            app.update_status(
                f"第 {page_num + 1} 页：正在用全模态模型识别页面文字（含图表）..."
            )
        blocks = extract_page_vision_blocks(page, llm_config)
    else:
        if hasattr(app, "update_status"):
            app.update_status(
                f"第 {page_num + 1} 页：正在 OCR 识别图表/图片中的文字..."
            )
        blocks = extract_page_ocr_blocks(
            page,
            pdf_doc=app.pdf_doc,
            page_num=page_num,
            llm_config=llm_config,
            use_vision_fallback=bool(llm_config),
        )

    app.ocr_text_positions[page_num] = blocks
    app.ocr_text_sources[page_num] = source_tag
    if hasattr(app, "update_status"):
        if blocks:
            if use_vision:
                app.update_status(
                    f"第 {page_num + 1} 页视觉识图完成，识别 {len(blocks)} 处文字"
                )
            else:
                app.update_status(
                    f"第 {page_num + 1} 页图内 OCR 完成，识别 {len(blocks)} 处文字"
                )
        elif text_layer_paragraphs >= TEXT_PARAGRAPHS_SKIP_IMAGE_OCR:
            pass
        else:
            app.update_status(
                f"第 {page_num + 1} 页："
                + _ocr_empty_status_hint(
                    llm_config, text_layer_paragraphs=text_layer_paragraphs
                )
            )
    return blocks


def clear_page_ocr_cache(app, page_num: Optional[int] = None) -> None:
    if not getattr(app, "ocr_text_positions", None):
        app.ocr_text_positions = {}
    if not getattr(app, "ocr_text_sources", None):
        app.ocr_text_sources = {}
    if page_num is None:
        app.ocr_text_positions.clear()
        app.ocr_text_sources.clear()
    else:
        app.ocr_text_positions.pop(page_num, None)
        app.ocr_text_sources.pop(page_num, None)
