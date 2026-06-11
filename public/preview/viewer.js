/* PDF.js 批注预览 + 演示工具（聚焦 / 激光笔 / 墨迹，参考 PPT 放映与 pdf-annotate overlay 思路） */
if (typeof pdfjsLib === "undefined") {
  document.addEventListener("DOMContentLoaded", () => {
    document.body.innerHTML =
      '<div style="padding:32px;font-family:system-ui,Microsoft YaHei,sans-serif;color:#5b21b6">' +
      '<h2>预览组件加载失败</h2>' +
      '<p>未能加载本地 PDF.js（pdf.min.js）。请重新安装或确认安装目录中的 web 资源完整。</p>' +
      '</div>';
  });
  throw new Error("pdfjsLib is not loaded (pdf.min.js missing)");
}
pdfjsLib.GlobalWorkerOptions.workerSrc = "pdf.worker.min.js";

const canvas = document.getElementById("pdf-canvas");
const ctx = canvas.getContext("2d");
const inkCanvas = document.getElementById("ink-canvas");
const inkCtx = inkCanvas.getContext("2d");
const laserCanvas = document.getElementById("laser-canvas");
const laserCtx = laserCanvas.getContext("2d");
const focusLayer = document.getElementById("focus-layer");
const layer = document.getElementById("annotation-layer");
const pageViewport = document.getElementById("page-viewport");
const pageContainer = document.getElementById("page-container");
const viewerWrap = document.getElementById("viewer-wrap");
const pageLabel = document.getElementById("page-label");
const statusEl = document.getElementById("status");
const toolsPanel = document.getElementById("tools-panel");

const INK_COLORS = [
  "#ffffff",
  "#000000",
  "#7f1d1d",
  "#ef4444",
  "#f97316",
  "#eab308",
  "#84cc16",
  "#16a34a",
  "#22d3ee",
  "#2563eb",
  "#1e3a8a",
  "#7c3aed",
];

let pdfDoc = null;
let currentPage = 0;
let totalPages = 0;
let renderTask = null;
const BASE_VIEWPORT_SCALE = 1.5;
const VIEW_ZOOM_MIN = BASE_VIEWPORT_SCALE * 0.5;
const VIEW_ZOOM_MAX = BASE_VIEWPORT_SCALE * 3;
const VIEW_ZOOM_STEP = 1.2;
let viewportScale = BASE_VIEWPORT_SCALE;
let basePageWidth = 0;
let basePageHeight = 0;
let pageWidth = 0;
let pageHeight = 0;
let annotationsByPage = {};
let activeMarker = null;
let activeMarkerIndex = null;
let lastPdfToken = "";
let lastFileIndex = null;
let lastStateFingerprint = "";
let lastAnnotationsFingerprint = "";
let lastInkFingerprint = "";
let lastServerPage = null;

/* —— 演示工具 —— */
let currentTool = "pointer";
let currentColor = "#ef4444";
let inkByPage = {};
const inkUndoStack = [];
const INK_UNDO_MAX = 50;
let isDrawing = false;
let currentStroke = null;
let lastInkPointer = null;
let inkDrawAnimId = null;
const INK_SAMPLE_PX = 2.5;
/** 与 src/utils/ink_style.py HIGHLIGHTER_OPACITY 保持一致 */
const HIGHLIGHTER_OPACITY = 0.18;
let laserTrail = [];
let laserAnimId = null;
let lastLaserPos = null;
const LASER_MAX_AGE = 680;
const LASER_SAMPLE_STEP = 2.5;
const LASER_TRAIL_MAX_POINTS = 200;
let magnifyActive = false;
let magnifyAnimating = false;
/** 按下时的聚焦锚点（页面归一化坐标 + 屏幕坐标，缩小全程不变） */
let magnifyOrigin = {
  nx: 0.5,
  ny: 0.5,
  px: 0,
  py: 0,
  clientX: 0,
  clientY: 0,
};
const MAGNIFY_FACTOR = 2;
/** 按住放大：CSS 缓动时长（须与 viewer.css 中 transition 一致）；缩小仍为立即还原 */
const MAGNIFY_ZOOM_IN_MS = 220;
const MAGNIFY_ZOOM_OUT_MS = 0;
let magnifyHiResReady = false;
let magnifyTransitionHandler = null;
let magnifyEndInProgress = false;
/** 高清渲染完成但 CSS 放大未结束时，暂存平移参数 */
let pendingMagnifyPan = null;
let inkSyncTimer = null;
const INK_SYNC_DELAY_MS = 450;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function magnifyContentSize() {
  return {
    w: pageWidth || basePageWidth || 1,
    h: pageHeight || basePageHeight || 1,
  };
}

/** 以按下点像素为 transform-origin，避免百分比在容器尺寸变化时偏移 */
function setMagnifyOrigin(nx, ny, contentW = null, contentH = null) {
  const { w, h } = magnifyContentSize();
  const bw = contentW ?? w;
  const bh = contentH ?? h;
  const ox = (nx ?? magnifyOrigin.nx) * bw;
  const oy = (ny ?? magnifyOrigin.ny) * bh;
  pageContainer.style.transformOrigin = `${ox}px ${oy}px`;
}

/** 缩小还原后，让按下点在屏幕上的位置尽量与按下时一致 */
function preserveMagnifyAnchorOnScreen() {
  if (!viewerWrap || !pageViewport || !basePageWidth) return;
  const pr = pageViewport.getBoundingClientRect();
  if (!pr.width || !pr.height) return;
  const sx = magnifyOrigin.nx * pr.width;
  const sy = magnifyOrigin.ny * pr.height;
  const dx = magnifyOrigin.clientX - (pr.left + sx);
  const dy = magnifyOrigin.clientY - (pr.top + sy);
  if (Math.abs(dx) > 0.5) {
    viewerWrap.scrollLeft = Math.max(0, viewerWrap.scrollLeft + dx);
  }
  if (Math.abs(dy) > 0.5) {
    viewerWrap.scrollTop = Math.max(0, viewerWrap.scrollTop + dy);
  }
  const maxLeft = Math.max(0, viewerWrap.scrollWidth - viewerWrap.clientWidth);
  const maxTop = Math.max(0, viewerWrap.scrollHeight - viewerWrap.clientHeight);
  viewerWrap.scrollLeft = Math.min(viewerWrap.scrollLeft, maxLeft);
  viewerWrap.scrollTop = Math.min(viewerWrap.scrollTop, maxTop);
}

function applyMagnifyPan(nx, ny, currentW, currentH) {
  if (!basePageWidth || !basePageHeight) return;
  const tx = -(nx * currentW - nx * basePageWidth);
  const ty = -(ny * currentH - ny * basePageHeight);
  pageContainer.style.transform = `translate(${tx}px, ${ty}px)`;
}

function applyMagnifySharpFinish() {
  clearMagnifyTransitionListener();
  pageContainer.classList.remove("page-magnify-smooth");
  pageContainer.classList.add("page-magnify-sharp");
  if (pendingMagnifyPan) {
    const { nx, ny, w, h } = pendingMagnifyPan;
    applyMagnifyPan(nx, ny, w, h);
    setMagnifyOrigin(nx, ny, w, h);
    pendingMagnifyPan = null;
  }
  pageContainer.style.transform = "scale(1)";
}

function resetMagnifyLayout() {
  clearMagnifyTransitionListener();
  pageContainer.style.transform = "";
  pageContainer.style.transformOrigin = "";
  pageContainer.classList.remove("page-magnify-smooth", "page-magnify-sharp");
  magnifyHiResReady = false;
  pendingMagnifyPan = null;
  if (basePageWidth && basePageHeight) {
    pageViewport.style.width = `${basePageWidth}px`;
    pageViewport.style.height = `${basePageHeight}px`;
  }
}

function clearMagnifyTransitionListener() {
  if (magnifyTransitionHandler) {
    pageContainer.removeEventListener("transitionend", magnifyTransitionHandler);
    magnifyTransitionHandler = null;
  }
}

function waitTransformTransition(ms) {
  return new Promise((resolve) => {
    clearMagnifyTransitionListener();
    const done = (e) => {
      if (e.target !== pageContainer || e.propertyName !== "transform") return;
      clearMagnifyTransitionListener();
      resolve();
    };
    magnifyTransitionHandler = done;
    pageContainer.addEventListener("transitionend", done);
    setTimeout(() => {
      clearMagnifyTransitionListener();
      resolve();
    }, ms + 60);
  });
}

function getHiResPanTranslate() {
  if (!basePageWidth || !basePageHeight) return { tx: 0, ty: 0 };
  const tx = -(magnifyOrigin.nx * pageWidth - magnifyOrigin.nx * basePageWidth);
  const ty = -(magnifyOrigin.ny * pageHeight - magnifyOrigin.ny * basePageHeight);
  return { tx, ty };
}

/** 基准分辨率上 CSS 缩放（放大前半段 / 仅 CSS 放大后的缩小） */
async function runCssMagnify(targetScale) {
  const zoomIn = targetScale > 1;
  const fromScale = zoomIn ? 1 : MAGNIFY_FACTOR;
  const { w, h } = magnifyContentSize();
  pageContainer.classList.remove("page-magnify-sharp");
  pageContainer.classList.add("page-magnify-smooth");
  setMagnifyOrigin(magnifyOrigin.nx, magnifyOrigin.ny, w, h);
  pageContainer.style.transform = `scale(${fromScale})`;
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  pageContainer.style.transform = `scale(${targetScale})`;
  await waitTransformTransition(zoomIn ? MAGNIFY_ZOOM_IN_MS : MAGNIFY_ZOOM_OUT_MS);
}

/** 松开立即还原到基准清晰度（无缩小动画） */
async function restoreMagnifyInstant() {
  clearMagnifyTransitionListener();
  magnifyHiResReady = false;
  magnifyAnimating = false;
  resetMagnifyLayout();
  await renderPage(currentPage, {
    clearActive: false,
    scale: BASE_VIEWPORT_SCALE,
    panOrigin: magnifyOrigin,
  });
  preserveMagnifyAnchorOnScreen();
}

/** 将屏幕坐标映射到与 canvas 像素一致的页面坐标（修复 CSS 缩放导致的笔触偏移） */
function getPageCoords(clientX, clientY) {
  const el = pageWidth > 0 ? inkCanvas : canvas;
  const rect = el.getBoundingClientRect();
  const w = el.width || pageWidth || 1;
  const h = el.height || pageHeight || 1;
  if (!rect.width || !rect.height) {
    return { px: 0, py: 0, nx: 0, ny: 0 };
  }
  const px = ((clientX - rect.left) * w) / rect.width;
  const py = ((clientY - rect.top) * h) / rect.height;
  return {
    px: Math.max(0, Math.min(px, w)),
    py: Math.max(0, Math.min(py, h)),
    nx: px / w,
    ny: py / h,
  };
}

function normPoint(clientX, clientY) {
  const { nx, ny } = getPageCoords(clientX, clientY);
  return { x: nx, y: ny };
}

function inkStorageKey() {
  return `topdf-preview-ink:${lastPdfToken || "default"}`;
}

function loadInkStore() {
  try {
    const raw = sessionStorage.getItem(inkStorageKey());
    inkByPage = raw ? JSON.parse(raw) : {};
  } catch (_) {
    inkByPage = {};
  }
}

async function loadInkFromServer() {
  try {
    const res = await fetch("/api/ink");
    if (!res.ok) return false;
    const data = await res.json();
    if (data.pages && typeof data.pages === "object") {
      inkByPage = data.pages;
      saveInkStore();
      return true;
    }
  } catch (_) {}
  return false;
}

function saveInkStore() {
  try {
    sessionStorage.setItem(inkStorageKey(), JSON.stringify(inkByPage));
  } catch (_) {}
}

function inkPagesPayload() {
  const pages = {};
  for (const [key, strokes] of Object.entries(inkByPage)) {
    const kept = (strokes || [])
      .filter((s) => s.tool === "pen" || s.tool === "highlighter")
      .map((s) => {
        const pw = pageWidth || basePageWidth || 1;
        return {
          tool: s.tool,
          color: s.color,
          width: s.width,
          width_norm: s.width_norm ?? s.width / pw,
          points: s.points,
        };
      });
    if (kept.length) pages[key] = kept;
  }
  return pages;
}

function scheduleInkSync() {
  clearTimeout(inkSyncTimer);
  inkSyncTimer = setTimeout(() => {
    void pushInkToServer();
  }, INK_SYNC_DELAY_MS);
}

async function pushInkToServer() {
  try {
    await fetch("/api/ink", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pages: inkPagesPayload() }),
    });
  } catch (_) {}
}

async function saveInkToDocument() {
  await pushInkToServer();
  const pages = inkPagesPayload();
  const strokeCount = Object.values(pages).reduce((n, arr) => n + arr.length, 0);
  if (strokeCount < 1) {
    statusEl.textContent = "没有可保存的笔记，请先用笔或荧光笔绘制";
    return;
  }
  let overwrite = false;
  try {
    overwrite = window.confirm(
      "确定保存笔记？\n\n· 选「确定」：覆盖原 PDF 文件（仅原生 PDF）\n· 选「取消」：在同目录另存为新 PDF\n\n笔迹与现有中文批注将一并写入。激光笔不会保存。",
    );
  } catch (_) {
    overwrite = false;
  }
  statusEl.textContent = "正在保存笔记到 PDF...";
  try {
    const res = await fetch("/api/ink/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pages, overwrite }),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || "保存失败");
    }
    statusEl.textContent = `笔记已保存：${data.path || "完成"}`;
    if (data.path) {
      lastPdfToken = "";
      await refresh(true);
    }
  } catch (err) {
    statusEl.textContent = `保存失败: ${err.message}`;
  }
}

function getPageStrokes(pageIndex) {
  const key = String(pageIndex);
  if (!inkByPage[key]) inkByPage[key] = [];
  return inkByPage[key];
}

function denormPoint(p) {
  const nx = p.nx ?? p.x ?? 0;
  const ny = p.ny ?? p.y ?? 0;
  return { x: nx * pageWidth, y: ny * pageHeight };
}

function setTool(tool) {
  currentTool = tool;
  document.querySelectorAll(".tool-item[data-tool]").forEach((btn) => {
    const t = btn.dataset.tool;
    btn.classList.toggle("active", t === tool && t !== "clear");
  });
  viewerWrap.className = "";
  inkCanvas.classList.remove("interactive");
  if (tool === "laser") viewerWrap.classList.add("mode-laser");
  if (tool === "pen") viewerWrap.classList.add("mode-pen");
  if (tool === "highlighter") viewerWrap.classList.add("mode-highlighter");
  if (tool === "eraser") viewerWrap.classList.add("mode-eraser");
  if (tool === "pen" || tool === "highlighter" || tool === "eraser") {
    inkCanvas.classList.add("interactive");
  }
  const hints = {
    pointer: "指针：点击查看批注；可用工具栏 +/− 或 Ctrl+滚轮缩放",
    laser: "激光笔：柔和渐变拖尾，松开后较快淡出",
    pen: "笔：在页面上手绘，墨迹会保留",
    highlighter: "荧光笔：平滑宽笔触（自动补点）",
    eraser: "橡皮擦：拖动擦除墨迹",
  };
  statusEl.textContent = hints[tool] || statusEl.textContent;
}

async function startMagnify(clientX, clientY) {
  if (magnifyAnimating || !pdfDoc) return;
  magnifyAnimating = true;
  const coords = getPageCoords(clientX, clientY);
  magnifyOrigin = {
    nx: coords.nx,
    ny: coords.ny,
    px: coords.px,
    py: coords.py,
    clientX,
    clientY,
  };
  magnifyActive = true;
  magnifyHiResReady = false;

  if (Math.abs(viewportScale - BASE_VIEWPORT_SCALE) > 0.02) {
    await renderPage(currentPage, { clearActive: false, scale: BASE_VIEWPORT_SCALE });
    updateZoomLabel();
  }

  setMagnifyOrigin(magnifyOrigin.nx, magnifyOrigin.ny, basePageWidth, basePageHeight);
  pendingMagnifyPan = null;

  const hiResScale = BASE_VIEWPORT_SCALE * MAGNIFY_FACTOR;
  const hiResPromise = renderPage(currentPage, {
    clearActive: false,
    scale: hiResScale,
    panOrigin: magnifyOrigin,
    deferPan: true,
  });
  const cssPromise =
    MAGNIFY_ZOOM_IN_MS > 0 ? runCssMagnify(MAGNIFY_FACTOR) : Promise.resolve();

  await Promise.all([cssPromise, hiResPromise]);

  if (!magnifyActive) {
    magnifyAnimating = false;
    resetMagnifyLayout();
    return;
  }

  applyMagnifySharpFinish();
  magnifyHiResReady = true;
  magnifyAnimating = false;
}

async function endMagnify() {
  if (!magnifyActive && !magnifyAnimating && !magnifyHiResReady) return;
  if (magnifyEndInProgress) return;
  magnifyEndInProgress = true;
  magnifyActive = false;

  try {
    await restoreMagnifyInstant();
  } finally {
    magnifyEndInProgress = false;
  }
}

function pushInkPoint(stroke, nx, ny) {
  const pts = stroke.points;
  const last = pts[pts.length - 1];
  if (!last) {
    pts.push({ x: nx, y: ny });
    return;
  }
  const dx = nx - last.x;
  const dy = ny - last.y;
  const distPx = Math.hypot(dx * pageWidth, dy * pageHeight);
  if (distPx < 0.4) return;
  if (distPx > INK_SAMPLE_PX) {
    const n = Math.ceil(distPx / INK_SAMPLE_PX);
    for (let i = 1; i <= n; i++) {
      const t = i / n;
      pts.push({ x: last.x + dx * t, y: last.y + dy * t });
    }
  } else {
    pts.push({ x: nx, y: ny });
  }
}

function drawSmoothStroke(stroke, context) {
  const pts = stroke.points;
  if (!pts || pts.length < 2) return;
  const c = context || inkCtx;
  const pixelPts = pts.map((p) => denormPoint(p));

  c.save();
  c.lineCap = "round";
  c.lineJoin = "round";
  c.strokeStyle = stroke.color;
  const isHi = stroke.tool === "highlighter";
  c.globalAlpha = isHi ? HIGHLIGHTER_OPACITY : 1;
  c.lineWidth = stroke.width;

  if (pixelPts.length === 2) {
    c.beginPath();
    c.moveTo(pixelPts[0].x, pixelPts[0].y);
    c.lineTo(pixelPts[1].x, pixelPts[1].y);
    c.stroke();
    c.restore();
    return;
  }

  c.beginPath();
  c.moveTo(pixelPts[0].x, pixelPts[0].y);
  for (let i = 1; i < pixelPts.length - 1; i++) {
    const xc = (pixelPts[i].x + pixelPts[i + 1].x) * 0.5;
    const yc = (pixelPts[i].y + pixelPts[i + 1].y) * 0.5;
    c.quadraticCurveTo(pixelPts[i].x, pixelPts[i].y, xc, yc);
  }
  const end = pixelPts[pixelPts.length - 1];
  const prev = pixelPts[pixelPts.length - 2];
  c.quadraticCurveTo(prev.x, prev.y, end.x, end.y);
  c.stroke();
  c.restore();
}

function redrawInk() {
  inkCtx.clearRect(0, 0, pageWidth, pageHeight);
  getPageStrokes(currentPage).forEach((s) => drawSmoothStroke(s, inkCtx));
}

function stopInkDrawLoop() {
  if (inkDrawAnimId) {
    cancelAnimationFrame(inkDrawAnimId);
    inkDrawAnimId = null;
  }
  lastInkPointer = null;
}

function startInkDrawLoop() {
  if (inkDrawAnimId) return;
  const tick = () => {
    if (!isDrawing || !currentStroke) {
      stopInkDrawLoop();
      return;
    }
    if (lastInkPointer) {
      pushInkPoint(currentStroke, lastInkPointer.nx, lastInkPointer.ny);
    }
    redrawInk();
    drawSmoothStroke(currentStroke, inkCtx);
    inkDrawAnimId = requestAnimationFrame(tick);
  };
  inkDrawAnimId = requestAnimationFrame(tick);
}

function strokeWidthForTool(tool) {
  if (tool === "highlighter") return Math.max(14, pageWidth * 0.018);
  if (tool === "eraser") return Math.max(18, pageWidth * 0.022);
  return Math.max(3, pageWidth * 0.004);
}

function eraseAt(nx, ny) {
  const radius = 0.025;
  const strokes = getPageStrokes(currentPage);
  for (let i = strokes.length - 1; i >= 0; i--) {
    const stroke = strokes[i];
    const hit = stroke.points.some(
      (p) => Math.hypot(p.x - nx, p.y - ny) < radius
    );
    if (hit) strokes.splice(i, 1);
  }
  saveInkStore();
  scheduleInkSync();
  redrawInk();
}

function cloneInkByPage() {
  return JSON.parse(JSON.stringify(inkByPage));
}

function pushInkUndo() {
  inkUndoStack.push(cloneInkByPage());
  if (inkUndoStack.length > INK_UNDO_MAX) {
    inkUndoStack.shift();
  }
}

function undoInkAction() {
  if (!inkUndoStack.length) {
    statusEl.textContent = "没有可撤销的笔迹操作";
    return;
  }
  inkByPage = inkUndoStack.pop();
  saveInkStore();
  scheduleInkSync();
  redrawInk();
  statusEl.textContent = "已撤销笔迹（Ctrl+Z）";
}

function clearPageInk() {
  pushInkUndo();
  inkByPage[String(currentPage)] = [];
  saveInkStore();
  scheduleInkSync();
  redrawInk();
}

function pushLaserPoint(x, y) {
  const now = Date.now();
  const last = laserTrail[laserTrail.length - 1];
  if (last) {
    const dx = x - last.x;
    const dy = y - last.y;
    const dist = Math.hypot(dx, dy);
    if (dist < 0.5) return;
    if (dist > LASER_SAMPLE_STEP) {
      const n = Math.ceil(dist / LASER_SAMPLE_STEP);
      for (let i = 1; i <= n; i++) {
        const t = i / n;
        laserTrail.push({
          x: last.x + dx * t,
          y: last.y + dy * t,
          t: now,
        });
      }
    } else {
      laserTrail.push({ x, y, t: now });
    }
  } else {
    laserTrail.push({ x, y, t: now });
  }
  laserTrail = laserTrail.filter((p) => now - p.t < LASER_MAX_AGE);
  if (laserTrail.length > LASER_TRAIL_MAX_POINTS) {
    laserTrail = laserTrail.slice(-LASER_TRAIL_MAX_POINTS);
  }
}

/** 0=最旧 … 1=最新，平滑缓动避免色带 */
function laserFadeT(t) {
  const x = Math.max(0, Math.min(1, t));
  return x * x * (3 - 2 * x);
}

/** 按点龄淡出：略陡于 laserFadeT，收尾尾迹更快消失 */
function laserAgeFade(remaining) {
  return Math.pow(laserFadeT(remaining), 1.45);
}

function drawLaserSmoothPath(ctx, points) {
  if (points.length < 2) return;
  ctx.beginPath();
  ctx.moveTo(points[0].x, points[0].y);
  for (let i = 1; i < points.length - 1; i++) {
    const xc = (points[i].x + points[i + 1].x) * 0.5;
    const yc = (points[i].y + points[i + 1].y) * 0.5;
    ctx.quadraticCurveTo(points[i].x, points[i].y, xc, yc);
  }
  const end = points[points.length - 1];
  const prev = points[points.length - 2];
  ctx.quadraticCurveTo(prev.x, prev.y, end.x, end.y);
  ctx.stroke();
}

/** 按时间与位置连续插值透明度、线宽（无分层色带） */
function drawLaserGradientTrail(ctx, points, now) {
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  const n = points.length;
  const tail = points[0];
  const head = points[n - 1];

  for (let i = 1; i < n; i++) {
    const a = points[i - 1];
    const b = points[i];
    const dist = Math.hypot(b.x - a.x, b.y - a.y);
    const sub = Math.max(1, Math.ceil(dist / 2));
    for (let j = 1; j <= sub; j++) {
      const u1 = j / sub;
      const u0 = (j - 1) / sub;
      const x0 = a.x + (b.x - a.x) * u0;
      const y0 = a.y + (b.y - a.y) * u0;
      const x1 = a.x + (b.x - a.x) * u1;
      const y1 = a.y + (b.y - a.y) * u1;
      const timeAt = a.t + (b.t - a.t) * u1;
      const ageFade = laserAgeFade(1 - (now - timeAt) / LASER_MAX_AGE);
      const posT = (i - 1 + u1) / Math.max(1, n - 1);
      const posFade = laserFadeT(posT);
      const fade = ageFade * 0.55 + posFade * 0.45;
      if (fade < 0.012) continue;
      const alpha = 0.04 + fade * 0.46;
      const w = 0.5 + fade * 4.5;
      ctx.beginPath();
      ctx.moveTo(x0, y0);
      ctx.lineTo(x1, y1);
      ctx.strokeStyle = `rgba(239, 68, 68, ${alpha})`;
      ctx.lineWidth = w;
      ctx.stroke();
    }
  }

  if (n >= 2) {
    const headFade = laserAgeFade(1 - (now - head.t) / LASER_MAX_AGE);
    const g = ctx.createRadialGradient(
      head.x,
      head.y,
      0,
      head.x,
      head.y,
      10,
    );
    g.addColorStop(0, `rgba(239, 68, 68, ${0.35 + headFade * 0.45})`);
    g.addColorStop(0.35, `rgba(239, 68, 68, ${0.12 + headFade * 0.2})`);
    g.addColorStop(1, "rgba(239, 68, 68, 0)");
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(head.x, head.y, 10, 0, Math.PI * 2);
    ctx.fill();
  }

  void tail;
}

function drawLaserFrame() {
  if (currentTool !== "laser") {
    stopLaserAnim();
    return;
  }
  if (lastLaserPos) {
    pushLaserPoint(lastLaserPos.px, lastLaserPos.py);
  }

  laserCtx.clearRect(0, 0, pageWidth, pageHeight);
  const now = Date.now();
  laserTrail = laserTrail.filter((p) => now - p.t < LASER_MAX_AGE);
  if (laserTrail.length > LASER_TRAIL_MAX_POINTS) {
    laserTrail = laserTrail.slice(-LASER_TRAIL_MAX_POINTS);
  }

  if (laserTrail.length < 2) {
    if (laserTrail.length === 1) {
      const p = laserTrail[0];
      const g = laserCtx.createRadialGradient(p.x, p.y, 0, p.x, p.y, 8);
      g.addColorStop(0, "rgba(239, 68, 68, 0.85)");
      g.addColorStop(1, "rgba(239, 68, 68, 0)");
      laserCtx.fillStyle = g;
      laserCtx.beginPath();
      laserCtx.arc(p.x, p.y, 8, 0, Math.PI * 2);
      laserCtx.fill();
    }
    laserAnimId = requestAnimationFrame(drawLaserFrame);
    return;
  }

  laserCtx.save();
  laserCtx.globalCompositeOperation = "lighter";
  laserCtx.shadowColor = "rgba(239, 68, 68, 0.35)";
  laserCtx.shadowBlur = 10;
  laserCtx.strokeStyle = "rgba(239, 68, 68, 0.1)";
  laserCtx.lineWidth = 9;
  drawLaserSmoothPath(laserCtx, laserTrail);
  laserCtx.shadowBlur = 0;
  drawLaserGradientTrail(laserCtx, laserTrail, now);
  laserCtx.restore();

  laserAnimId = requestAnimationFrame(drawLaserFrame);
}

function stopLaserAnim() {
  if (laserAnimId) {
    cancelAnimationFrame(laserAnimId);
    laserAnimId = null;
  }
  laserCtx.clearRect(0, 0, pageWidth, pageHeight);
  laserTrail = [];
  lastLaserPos = null;
}

function resizeOverlayLayers(w, h) {
  pageWidth = w;
  pageHeight = h;
  canvas.style.width = `${w}px`;
  canvas.style.height = `${h}px`;
  [inkCanvas, laserCanvas].forEach((c) => {
    c.width = w;
    c.height = h;
    c.style.width = `${w}px`;
    c.style.height = `${h}px`;
  });
  focusLayer.style.width = `${w}px`;
  focusLayer.style.height = `${h}px`;
  layer.style.width = `${w}px`;
  layer.style.height = `${h}px`;
}

function initToolsUi() {
  const palette = document.getElementById("color-palette");
  INK_COLORS.forEach((color) => {
    const sw = document.createElement("button");
    sw.type = "button";
    sw.className = "color-swatch";
    sw.dataset.color = color;
    sw.style.background = color;
    sw.title = color;
    if (color === currentColor) sw.classList.add("selected");
    sw.addEventListener("click", () => {
      currentColor = color;
      palette.querySelectorAll(".color-swatch").forEach((el) => {
        el.classList.toggle("selected", el.dataset.color === color);
      });
    });
    palette.appendChild(sw);
  });

  document.getElementById("btn-tools").addEventListener("click", () => {
    toolsPanel.classList.toggle("hidden");
    document.getElementById("btn-tools").classList.toggle("active");
  });

  const bindSaveInk = (id) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener("click", () => void saveInkToDocument());
  };
  bindSaveInk("btn-save-ink");
  bindSaveInk("btn-save-ink-panel");

  document.getElementById("btn-zoom-in")?.addEventListener("click", () => void zoomIn());
  document.getElementById("btn-zoom-out")?.addEventListener("click", () => void zoomOut());
  document.getElementById("btn-zoom-reset")?.addEventListener("click", () => void zoomReset());

  viewerWrap.addEventListener(
    "wheel",
    (e) => {
      if (!pdfDoc) return;
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      if (e.deltaY < 0) void zoomIn();
      else void zoomOut();
    },
    { passive: false },
  );

  document.querySelectorAll(".tool-item[data-tool]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const tool = btn.dataset.tool;
      if (tool === "clear") {
        if (confirm("清除当前页所有手绘墨迹？")) clearPageInk();
        return;
      }
      setTool(tool);
      if (tool === "laser") {
        if (!laserAnimId) drawLaserFrame();
      } else {
        stopLaserAnim();
      }
    });
  });

  pageContainer.addEventListener("pointermove", (e) => {
    if (currentTool !== "laser") return;
    lastLaserPos = getPageCoords(e.clientX, e.clientY);
  });

  pageContainer.addEventListener("pointerleave", () => {
    if (currentTool === "laser") lastLaserPos = null;
  });

  inkCanvas.addEventListener("pointerdown", (e) => {
    if (currentTool !== "pen" && currentTool !== "highlighter" && currentTool !== "eraser") {
      return;
    }
    e.preventDefault();
    inkCanvas.setPointerCapture(e.pointerId);
    const coords = getPageCoords(e.clientX, e.clientY);
    if (currentTool === "eraser") {
      pushInkUndo();
      isDrawing = true;
      eraseAt(coords.nx, coords.ny);
      return;
    }
    pushInkUndo();
    isDrawing = true;
    currentStroke = {
      tool: currentTool,
      color: currentColor,
      width: strokeWidthForTool(currentTool),
      points: [{ x: coords.nx, y: coords.ny }],
    };
    lastInkPointer = coords;
    startInkDrawLoop();
  });

  inkCanvas.addEventListener("pointermove", (e) => {
    if (!isDrawing) return;
    const coords = getPageCoords(e.clientX, e.clientY);
    if (currentTool === "eraser") {
      eraseAt(coords.nx, coords.ny);
      return;
    }
    if (!currentStroke) return;
    lastInkPointer = coords;
  });

  const endStroke = (e) => {
    if (isDrawing && currentStroke && e) {
      const coords = getPageCoords(e.clientX, e.clientY);
      pushInkPoint(currentStroke, coords.nx, coords.ny);
    }
    stopInkDrawLoop();
    if (!isDrawing) return;
    isDrawing = false;
    if (currentStroke && currentStroke.points.length > 1) {
      const pw = pageWidth || basePageWidth || 1;
      currentStroke.width_norm = currentStroke.width / pw;
      getPageStrokes(currentPage).push(currentStroke);
      saveInkStore();
      scheduleInkSync();
    }
    currentStroke = null;
    redrawInk();
  };

  inkCanvas.addEventListener("pointerup", endStroke);
  inkCanvas.addEventListener("pointercancel", endStroke);

  setTool("pointer");
}

async function fetchState() {
  const res = await fetch("/api/state");
  return res.json();
}

async function loadPdf(pdfToken) {
  const q = pdfToken
    ? `?v=${encodeURIComponent(pdfToken)}`
    : `?t=${Date.now()}`;
  const res = await fetch(`/api/pdf${q}`, { cache: "no-store" });
  if (!res.ok) throw new Error("PDF 不可用");
  const data = await res.arrayBuffer();
  pdfDoc = await pdfjsLib.getDocument({ data }).promise;
  totalPages = pdfDoc.numPages;
}

function stateFingerprint(state) {
  return JSON.stringify({
    pdf_token: state.pdf_token || "",
    current_file_index: state.current_file_index ?? -1,
    current_page: state.current_page || 0,
    total_pages: state.total_pages || 0,
    annotations: state.annotations || {},
    ink_pages: state.ink_pages || {},
  });
}

function annotationsFingerprint(state) {
  return JSON.stringify(state.annotations || {});
}

function inkFingerprint(state) {
  return JSON.stringify(state.ink_pages || {});
}

function applyServerInkPages(inkPages) {
  if (!inkPages || typeof inkPages !== "object") return;
  inkByPage = inkPages;
  saveInkStore();
  if (pdfDoc) redrawInk();
}

function clearLayer() {
  layer.innerHTML = "";
  activeMarker = null;
}

const ANNOT_MARKER_SIZE = 24;
const ANNOT_POPUP_GAP = 30;
const ANNOT_POPUP_EDGE = 4;

/** 批注弹层在页面坐标内翻转/钳位，避免靠边时被 viewport 裁切 */
function layoutAnnotPopup(markerEl, popupEl, item) {
  const pageW = pageWidth || basePageWidth || 1;
  const pageH = pageHeight || basePageHeight || 1;
  const mx = Number(item.x) * viewportScale;
  const my = Number(item.y) * viewportScale;

  const prevDisplay = popupEl.style.display;
  popupEl.style.visibility = "hidden";
  popupEl.style.display = "block";
  const pw = popupEl.offsetWidth || 280;
  const ph = popupEl.offsetHeight || 120;
  popupEl.style.display = prevDisplay || "";
  popupEl.style.visibility = "";

  let px = mx + ANNOT_MARKER_SIZE + ANNOT_POPUP_GAP;
  if (px + pw > pageW - ANNOT_POPUP_EDGE) {
    px = mx - ANNOT_POPUP_GAP - pw;
  }
  px = Math.max(
    ANNOT_POPUP_EDGE,
    Math.min(px, pageW - pw - ANNOT_POPUP_EDGE),
  );

  let py = my;
  if (py + ph > pageH - ANNOT_POPUP_EDGE) {
    py = pageH - ph - ANNOT_POPUP_EDGE;
  }
  py = Math.max(
    ANNOT_POPUP_EDGE,
    Math.min(py, pageH - ph - ANNOT_POPUP_EDGE),
  );

  popupEl.style.left = `${px - mx}px`;
  popupEl.style.top = `${py - my}px`;
  popupEl.style.right = "auto";
  popupEl.style.bottom = "auto";
}

function scheduleAnnotPopupLayout(markerEl, popupEl, item) {
  requestAnimationFrame(() => {
    if (!markerEl.isConnected || !markerEl.classList.contains("active")) return;
    layoutAnnotPopup(markerEl, popupEl, item);
  });
}

const visibleAreaGuide = document.getElementById("visible-area-guide");

/** 预览窗口内当前可见区域（需滚动才能看到的在虚线外） */
function updateVisibleAreaGuide() {
  if (!visibleAreaGuide || !viewerWrap || !pageViewport) return;
  const wr = viewerWrap.getBoundingClientRect();
  const pr = pageViewport.getBoundingClientRect();
  const left = Math.max(wr.left, pr.left);
  const top = Math.max(wr.top, pr.top);
  const right = Math.min(wr.right, pr.right);
  const bottom = Math.min(wr.bottom, pr.bottom);
  const w = right - left;
  const h = bottom - top;
  const pageW = pageWidth || pr.width;
  const pageH = pageHeight || pr.height;
  const needsGuide =
    w > 0 &&
    h > 0 &&
    (w < pageW - 3 || h < pageH - 3 || viewerWrap.scrollWidth > viewerWrap.clientWidth + 2);
  if (!needsGuide) {
    visibleAreaGuide.hidden = true;
    return;
  }
  visibleAreaGuide.hidden = false;
  visibleAreaGuide.style.left = `${left - pr.left}px`;
  visibleAreaGuide.style.top = `${top - pr.top}px`;
  visibleAreaGuide.style.width = `${w}px`;
  visibleAreaGuide.style.height = `${h}px`;
}

function renderMarkers(pageIndex, restoreIndex = null) {
  const keepIndex = restoreIndex ?? activeMarkerIndex;
  clearLayer();

  const items = annotationsByPage[String(pageIndex)] || [];
  items.forEach((item) => {
    if (item.display_mode === "inline") {
      const inline = document.createElement("div");
      inline.className = "annot-inline";
      inline.dataset.index = String(item.index);
      inline.style.color = item.color || "#7c2d12";
      const inlineFontPt = (item.original_text || "").trim() ? 10 : (item.font_size || 12);
      inline.style.fontSize = `${inlineFontPt * viewportScale}px`;
      inline.style.fontFamily = item.font_family || "inherit";
      inline.style.fontWeight = "600";
      inline.style.left = `${item.x * viewportScale}px`;
      inline.style.top = `${item.y * viewportScale}px`;

      if (item.box_width && item.box_width > 0) {
        inline.style.width = `${item.box_width * viewportScale}px`;
        inline.style.maxWidth = `${item.box_width * viewportScale}px`;
      } else {
        const layerW = layer.clientWidth || 800;
        if (item.placement === "below" && item.box_width) {
          inline.style.maxWidth = `${item.box_width * viewportScale}px`;
        } else if (item.placement === "right") {
          inline.style.maxWidth = `${Math.max(120, layerW - item.x * viewportScale)}px`;
        }
      }

      if (item.box_height && item.box_height > 0) {
        inline.style.minHeight = `${item.box_height * viewportScale}px`;
      }

      if (item.placement === "above") {
        inline.style.transform = "translate(-2px, -100%)";
        inline.style.transformOrigin = "left bottom";
      } else if (item.placement === "right") {
        inline.style.transformOrigin = "left center";
      } else {
        inline.style.transformOrigin = "left top";
      }

      inline.textContent = item.text || "";
      if (item.text_orientation === "vertical") {
        inline.classList.add("vertical");
        inline.style.writingMode = "vertical-rl";
        inline.style.textOrientation = "upright";
      }
      layer.appendChild(inline);
      return;
    }

    const marker = document.createElement("div");
    marker.className = "annot-marker";
    marker.dataset.index = String(item.index);
    marker.style.borderColor = item.color || "#7c3aed";
    marker.style.left = `${item.x * viewportScale}px`;
    marker.style.top = `${item.y * viewportScale}px`;
    marker.textContent = item.index;

    const popup = document.createElement("div");
    popup.className = "annot-popup";
    popup.style.borderColor = item.color || "#7c3aed";

    const title = document.createElement("div");
    title.className = "annot-popup-title";
    title.textContent = `批注 ${item.index}`;

    const body = document.createElement("div");
    body.textContent = item.text || "";

    popup.appendChild(title);
    popup.appendChild(body);
    marker.appendChild(popup);

    marker.addEventListener("click", (e) => {
      e.stopPropagation();
      if (currentTool !== "pointer") return;
      if (activeMarker && activeMarker !== marker) {
        activeMarker.classList.remove("active");
      }
      marker.classList.toggle("active");
      if (marker.classList.contains("active")) {
        activeMarker = marker;
        activeMarkerIndex = item.index;
        scheduleAnnotPopupLayout(marker, popup, item);
      } else {
        activeMarker = null;
        activeMarkerIndex = null;
      }
    });

    if (keepIndex === item.index) {
      marker.classList.add("active");
      activeMarker = marker;
      activeMarkerIndex = item.index;
      scheduleAnnotPopupLayout(marker, popup, item);
    }

    layer.appendChild(marker);
  });

  if (keepIndex != null && !items.some((item) => item.index === keepIndex)) {
    activeMarkerIndex = null;
    activeMarker = null;
  }
}

function resetViewerScroll() {
  if (!viewerWrap) return;
  viewerWrap.scrollTop = 0;
  viewerWrap.scrollLeft = 0;
}

function clampViewerScale(scale) {
  return Math.max(VIEW_ZOOM_MIN, Math.min(VIEW_ZOOM_MAX, scale));
}

function zoomPercentLabel(scale = viewportScale) {
  return `${Math.round((scale / BASE_VIEWPORT_SCALE) * 100)}%`;
}

function updateZoomLabel() {
  const el = document.getElementById("zoom-label");
  if (el) el.textContent = zoomPercentLabel();
}

async function applyViewerZoom(targetScale, { keepScrollAnchor = true } = {}) {
  if (!pdfDoc) return;
  const next = clampViewerScale(targetScale);
  if (Math.abs(next - viewportScale) < 0.001) return;

  if (magnifyActive || magnifyAnimating || magnifyHiResReady) {
    magnifyActive = false;
    resetMagnifyLayout();
  }

  let ratioX = 0.5;
  let ratioY = 0.5;
  if (keepScrollAnchor && viewerWrap && basePageWidth) {
    const maxLeft = Math.max(1, viewerWrap.scrollWidth - viewerWrap.clientWidth);
    const maxTop = Math.max(1, viewerWrap.scrollHeight - viewerWrap.clientHeight);
    ratioX = viewerWrap.scrollLeft / maxLeft;
    ratioY = viewerWrap.scrollTop / maxTop;
  }

  viewportScale = next;
  await renderPage(currentPage, { clearActive: false, scale: next });
  updateZoomLabel();

  if (keepScrollAnchor && viewerWrap) {
    const maxLeft = Math.max(0, viewerWrap.scrollWidth - viewerWrap.clientWidth);
    const maxTop = Math.max(0, viewerWrap.scrollHeight - viewerWrap.clientHeight);
    viewerWrap.scrollLeft = maxLeft * ratioX;
    viewerWrap.scrollTop = maxTop * ratioY;
  }
  requestAnimationFrame(updateVisibleAreaGuide);
}

async function zoomIn() {
  await applyViewerZoom(viewportScale * VIEW_ZOOM_STEP);
}

async function zoomOut() {
  await applyViewerZoom(viewportScale / VIEW_ZOOM_STEP);
}

async function zoomReset() {
  await applyViewerZoom(BASE_VIEWPORT_SCALE, { keepScrollAnchor: false });
  resetViewerScroll();
}

async function renderPage(
  pageNum,
  { clearActive = true, scale = null, panOrigin = null, deferPan = false } = {},
) {
  if (!pdfDoc) return;
  const prevPage = currentPage;
  if (renderTask) {
    try {
      await renderTask.cancel();
    } catch (_) {}
  }

  const pageChanged = pageNum !== prevPage;
  if (clearActive && pageChanged) {
    activeMarkerIndex = null;
    magnifyActive = false;
    resetMagnifyLayout();
    resetViewerScroll();
  }

  currentPage = pageNum;
  const effectiveScale = scale != null ? scale : viewportScale;
  viewportScale = effectiveScale;

  const page = await pdfDoc.getPage(pageNum + 1);
  const viewport = page.getViewport({ scale: effectiveScale });

  canvas.width = viewport.width;
  canvas.height = viewport.height;
  resizeOverlayLayers(viewport.width, viewport.height);

  ctx.imageSmoothingEnabled = true;
  if ("imageSmoothingQuality" in ctx) {
    ctx.imageSmoothingQuality = "high";
  }

  renderTask = page.render({ canvasContext: ctx, viewport });
  await renderTask.promise;

  if (effectiveScale === BASE_VIEWPORT_SCALE) {
    basePageWidth = viewport.width;
    basePageHeight = viewport.height;
    pageWidth = viewport.width;
    pageHeight = viewport.height;
    pageViewport.style.width = `${basePageWidth}px`;
    pageViewport.style.height = `${basePageHeight}px`;
    if (panOrigin) {
      applyMagnifyPan(panOrigin.nx, panOrigin.ny, viewport.width, viewport.height);
    } else {
      pageContainer.style.transform = "";
    }
  } else if (panOrigin) {
    pageViewport.style.width = `${basePageWidth}px`;
    pageViewport.style.height = `${basePageHeight}px`;
    pageWidth = viewport.width;
    pageHeight = viewport.height;
    if (deferPan) {
      pendingMagnifyPan = {
        nx: panOrigin.nx,
        ny: panOrigin.ny,
        w: viewport.width,
        h: viewport.height,
      };
    } else {
      applyMagnifyPan(panOrigin.nx, panOrigin.ny, viewport.width, viewport.height);
      setMagnifyOrigin(panOrigin.nx, panOrigin.ny, viewport.width, viewport.height);
    }
  } else {
    pageWidth = viewport.width;
    pageHeight = viewport.height;
    pageViewport.style.width = `${viewport.width}px`;
    pageViewport.style.height = `${viewport.height}px`;
    pageContainer.style.transform = "";
    pageContainer.classList.remove("page-magnify-smooth", "page-magnify-sharp");
  }

  renderMarkers(pageNum, clearActive ? null : activeMarkerIndex);
  redrawInk();
  pageLabel.textContent = `${pageNum + 1} / ${totalPages}`;
  updateZoomLabel();
  requestAnimationFrame(updateVisibleAreaGuide);
}

async function updateMarkersOnly() {
  if (!pdfDoc) return;
  renderMarkers(currentPage, activeMarkerIndex);
}

async function syncPageToServer(pageNum) {
  try {
    await fetch("/api/navigate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ page: pageNum }),
    });
  } catch (_) {
    /* 预览内翻页同步失败时不打断浏览 */
  }
}

async function refresh(force = false) {
  try {
    const state = await fetchState();
    const inkFp = inkFingerprint(state);
    const inkChanged = force || inkFp !== lastInkFingerprint;
    if (inkChanged) {
      lastInkFingerprint = inkFp;
      applyServerInkPages(state.ink_pages);
    }

    const annFp = annotationsFingerprint(state);
    const annChanged = force || annFp !== lastAnnotationsFingerprint;
    if (annChanged) {
      lastAnnotationsFingerprint = annFp;
      annotationsByPage = state.annotations || {};
      if (pdfDoc) {
        await updateMarkersOnly();
      }
    }

    const fingerprint = stateFingerprint(state);

    if (!force && fingerprint === lastStateFingerprint) {
      return;
    }

    const prevFingerprint = lastStateFingerprint;
    lastStateFingerprint = fingerprint;

    const newAnnotations = state.annotations || {};
    const serverPage = state.current_page || 0;
    totalPages = state.total_pages || 0;

    const newToken = state.pdf_token || "";
    const serverFileIndex = state.current_file_index ?? -1;
    const pdfTokenChanged = Boolean(newToken) && newToken !== lastPdfToken;
    const fileIndexChanged = lastFileIndex !== null && serverFileIndex !== lastFileIndex;
    if (pdfTokenChanged || fileIndexChanged) {
      pdfDoc = null;
      activeMarkerIndex = null;
      lastPdfToken = newToken;
      lastFileIndex = serverFileIndex;
      const fromServer = await loadInkFromServer();
      if (!fromServer) loadInkStore();
    } else if (newToken) {
      lastPdfToken = newToken;
      lastFileIndex = serverFileIndex;
    } else {
      lastFileIndex = serverFileIndex;
    }

    if (!pdfDoc && state.pdf_available) {
      await loadPdf(newToken);
      totalPages = pdfDoc.numPages;
      if (pdfTokenChanged || fileIndexChanged) {
        const fromServer = await loadInkFromServer();
        if (!fromServer) loadInkStore();
      } else if (newToken) {
        loadInkStore();
      }
    } else if (pdfTokenChanged || fileIndexChanged) {
      lastInkFingerprint = inkFingerprint(state);
      applyServerInkPages(state.ink_pages);
    }

    if (!pdfDoc) {
      statusEl.textContent = "请先在桌面应用中导入 PDF";
      return;
    }

    annotationsByPage = newAnnotations;

    // 实时同步时保持预览当前页，仅在首次加载 / 换 PDF / 强制刷新 / 桌面端主动翻页时跟随 serverPage
    let targetPage;
    if (force || pdfTokenChanged || fileIndexChanged || !prevFingerprint) {
      targetPage = Math.max(0, Math.min(serverPage, pdfDoc.numPages - 1));
    } else if (lastServerPage !== null && serverPage !== lastServerPage) {
      targetPage = Math.max(0, Math.min(serverPage, pdfDoc.numPages - 1));
    } else {
      targetPage = Math.max(0, Math.min(currentPage, pdfDoc.numPages - 1));
    }
    lastServerPage = serverPage;

    const pageChanged = targetPage !== currentPage;

    if (pdfTokenChanged || fileIndexChanged || !prevFingerprint || pageChanged) {
      if (pageChanged) {
        activeMarkerIndex = null;
      }
      await renderPage(targetPage, { clearActive: pageChanged });
    } else {
      await updateMarkersOnly();
    }

    if (currentTool === "pointer") {
      statusEl.textContent = "指针：点击查看批注；工具栏 +/− 或 Ctrl+滚轮缩放；可切换激光笔/绘图";
    }
  } catch (err) {
    statusEl.textContent = `加载失败: ${err.message}`;
  }
}

document.getElementById("btn-prev").addEventListener("click", async () => {
  if (!pdfDoc || currentPage <= 0) return;
  activeMarkerIndex = null;
  const next = currentPage - 1;
  await renderPage(next);
  syncPageToServer(next);
});

document.getElementById("btn-next").addEventListener("click", async () => {
  if (!pdfDoc || currentPage >= totalPages - 1) return;
  activeMarkerIndex = null;
  const next = currentPage + 1;
  await renderPage(next);
  syncPageToServer(next);
});

document.getElementById("btn-refresh").addEventListener("click", () => refresh(true));

function closeActiveMarker() {
  if (activeMarker) {
    activeMarker.classList.remove("active");
    activeMarker = null;
  }
  activeMarkerIndex = null;
}

viewerWrap.addEventListener("click", (e) => {
  if (e.target.closest(".annot-marker")) return;
  if (e.target.closest("#tools-panel")) return;
  closeActiveMarker();
});

if (viewerWrap) {
  viewerWrap.addEventListener("scroll", () => requestAnimationFrame(updateVisibleAreaGuide), {
    passive: true,
  });
}
window.addEventListener("resize", () => requestAnimationFrame(updateVisibleAreaGuide));

document.addEventListener("keydown", (e) => {
  const tag = (e.target && e.target.tagName) || "";
  if (tag === "INPUT" || tag === "TEXTAREA") return;
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z" && !e.shiftKey) {
    e.preventDefault();
    undoInkAction();
  }
});

initToolsUi();
updateZoomLabel();
refresh(true);
setInterval(() => refresh(false), 1000);
