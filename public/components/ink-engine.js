/**
 * 墨迹引擎 — 对齐 src/ui/canvas_ink.py + App 中画布绘图逻辑
 * 笔 / 荧光笔 / 橡皮擦 / 颜色
 */
const InkEngine = (() => {
  const HIGHLIGHTER_OPACITY = 0.18;
  const INK_COLORS = [
    '#ffffff', '#000000', '#7f1d1d', '#ef4444', '#f97316', '#eab308',
    '#84cc16', '#16a34a', '#22d3ee', '#2563eb', '#1e3a8a', '#7c3aed',
  ];
  const ERASER_HIT_RADIUS = 0.025;

  let currentStroke = null;
  let inkCanvas = null;
  let inkCtx = null;
  let _color = '#ef4444';

  function init() {
    inkCanvas = document.getElementById('ink-canvas');
    inkCtx = inkCanvas.getContext('2d');

    document.getElementById('btn-clear-ink')?.addEventListener('click', async () => {
      const ok = await Dialogs.askYesNo('清除墨迹', '确定清除当前页所有笔迹与荧光笔？');
      if (!ok) return;
      clearPageInk();
    });
  }

  function setTool(tool) {
    AppState.set('canvasTool', tool);
    currentStroke = null;

    const inkC = document.getElementById('ink-canvas');
    if (inkC) inkC.classList.toggle('interactive', tool === 'pen' || tool === 'highlighter' || tool === 'eraser');
  }

  function setColor(color) {
    _color = color;
    AppState.set('inkColor', color);
  }

  function strokeWidth(tool) {
    const { width } = Preview.getPageDimensions();
    if (tool === 'highlighter') return Math.max(14, width * 0.018);
    if (tool === 'eraser') return Math.max(18, width * 0.022);
    return Math.max(3, width * 0.004);
  }

  function toNorm(cx, cy) {
    const { width, height } = Preview.getPageDimensions();
    return { x: cx / (width || 1), y: cy / (height || 1) };
  }

  function fromNorm(nx, ny) {
    const { width, height } = Preview.getPageDimensions();
    return { x: nx * width, y: ny * height };
  }

  function startStroke(tool, cx, cy) {
    const norm = toNorm(cx, cy);
    const { width } = Preview.getPageDimensions();
    currentStroke = {
      tool,
      color: _color || AppState.get('inkColor'),
      width: strokeWidth(tool),
      width_norm: strokeWidth(tool) / (width || 1),
      points: [{ x: norm.x, y: norm.y }],
    };
  }

  function extendStroke(cx, cy) {
    if (!currentStroke) return;
    const norm = toNorm(cx, cy);
    const pts = currentStroke.points;
    const last = pts[pts.length - 1];
    const dist = Math.hypot(norm.x - last.x, norm.y - last.y);
    if (dist < 0.002) return;
    pts.push({ x: norm.x, y: norm.y });
    redrawLive();
  }

  function finishStroke() {
    if (!currentStroke || currentStroke.points.length < 2) {
      currentStroke = null;
      return;
    }

    const page = String(AppState.get('currentPage'));
    const ink = AppState.state.inkByPage;
    if (!ink[page]) ink[page] = [];
    ink[page].push(currentStroke);
    currentStroke = null;

    redraw();
    syncInk();
    StatusBar.setMessage('笔迹已保存（已同步预览）');
  }

  function eraseAt(cx, cy) {
    const norm = toNorm(cx, cy);
    const page = String(AppState.get('currentPage'));
    const strokes = AppState.state.inkByPage[page] || [];
    const kept = strokes.filter((s) => {
      if (s.tool !== 'pen' && s.tool !== 'highlighter') return true;
      return !s.points.some((p) => Math.hypot(p.x - norm.x, p.y - norm.y) < ERASER_HIT_RADIUS);
    });
    if (kept.length !== strokes.length) {
      AppState.state.inkByPage[page] = kept;
      redraw();
      syncInk();
    }
  }

  function clearPageInk() {
    const page = String(AppState.get('currentPage'));
    AppState.state.inkByPage[page] = [];
    redraw();
    syncInk();
    StatusBar.setMessage('已清除本页墨迹');
  }

  function redraw() {
    if (!inkCtx) return;
    const { width, height } = Preview.getPageDimensions();
    inkCtx.clearRect(0, 0, width, height);
    const page = String(AppState.get('currentPage'));
    const strokes = AppState.state.inkByPage[page] || [];
    strokes.forEach((s) => drawStroke(inkCtx, s, width, height));
  }

  function redrawLive() {
    redraw();
    if (currentStroke) {
      const { width, height } = Preview.getPageDimensions();
      drawStroke(inkCtx, currentStroke, width, height);
    }
  }

  function drawStroke(ctx, stroke, pw, ph) {
    const pts = stroke.points;
    if (!pts || pts.length < 2) return;

    ctx.save();
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.strokeStyle = stroke.color;

    const isHi = stroke.tool === 'highlighter';
    ctx.globalAlpha = isHi ? HIGHLIGHTER_OPACITY : 1;

    let w = stroke.width || 2;
    if (stroke.width_norm != null && pw > 0) w = Math.max(0.8, stroke.width_norm * pw);
    ctx.lineWidth = w;

    ctx.beginPath();
    const p0 = fromNorm(pts[0].x, pts[0].y);
    ctx.moveTo(p0.x, p0.y);

    for (let i = 1; i < pts.length - 1; i++) {
      const curr = fromNorm(pts[i].x, pts[i].y);
      const next = fromNorm(pts[i + 1].x, pts[i + 1].y);
      const xc = (curr.x + next.x) * 0.5;
      const yc = (curr.y + next.y) * 0.5;
      ctx.quadraticCurveTo(curr.x, curr.y, xc, yc);
    }

    const last = fromNorm(pts[pts.length - 1].x, pts[pts.length - 1].y);
    if (pts.length >= 2) {
      const prev = fromNorm(pts[pts.length - 2].x, pts[pts.length - 2].y);
      ctx.quadraticCurveTo(prev.x, prev.y, last.x, last.y);
    }

    ctx.stroke();
    ctx.restore();
  }

  function syncInk() {
    const pages = {};
    for (const [key, strokes] of Object.entries(AppState.state.inkByPage)) {
      const kept = (strokes || []).filter((s) => s.tool === 'pen' || s.tool === 'highlighter');
      if (kept.length) pages[key] = kept;
    }
    ApiClient.putInk(pages).catch(() => {});
  }

  return { init, setTool, setColor, startStroke, extendStroke, finishStroke, eraseAt, redraw, INK_COLORS };
})();
