/**
 * PDF 预览画布 — 对齐 App._render_page / _ensure_preview_shell / 缩放 / 翻页
 * 使用 pdf.js 渲染
 */
const Preview = (() => {
  let pdfDoc = null;
  let renderTask = null;
  let zoomLevel = 1.0;
  let currentPage = 0;
  let totalPages = 0;
  let pageWidth = 0;
  let pageHeight = 0;
  const RENDER_SCALE = 2;

  const canvas = document.getElementById('pdf-canvas');
  const ctx = canvas.getContext('2d');
  const inkCanvas = document.getElementById('ink-canvas');
  const viewer = document.getElementById('preview-viewer');
  const placeholder = document.getElementById('preview-placeholder');
  const navBar = document.getElementById('nav-bar');
  const inkToolbar = document.getElementById('ink-toolbar');
  const canvasWrap = document.getElementById('canvas-wrap');

  function init() {
    document.getElementById('btn-zoom-in').addEventListener('click', zoomIn);
    document.getElementById('btn-zoom-out').addEventListener('click', zoomOut);
    document.getElementById('btn-prev-page').addEventListener('click', prevPage);
    document.getElementById('btn-next-page').addEventListener('click', nextPage);

    canvasWrap.addEventListener('wheel', onScroll, { passive: false });
    canvasWrap.addEventListener('mousedown', onCanvasPress);
    canvasWrap.addEventListener('mousemove', onCanvasDrag);
    canvasWrap.addEventListener('mouseup', onCanvasRelease);
    canvasWrap.addEventListener('dblclick', onCanvasDoubleClick);
  }

  function showPlaceholder() {
    viewer.style.display = 'none';
    navBar.style.display = 'none';
    inkToolbar.style.display = 'none';
    placeholder.style.display = 'flex';
    pdfDoc = null;
    AppState.set('pdfDoc', null);
  }

  function showViewer() {
    placeholder.style.display = 'none';
    viewer.style.display = 'flex';
    navBar.style.display = 'flex';
    inkToolbar.style.display = 'flex';
  }

  async function loadFromState(state) {
    try {
      if (state.pdf_available) {
        const data = await ApiClient.getPdfArrayBuffer(state.pdf_token);
        const pdfjsLib = await getPdfjs();
        pdfDoc = await pdfjsLib.getDocument({ data }).promise;
        totalPages = pdfDoc.numPages;
        currentPage = state.current_page || 0;
        zoomLevel = state.zoom_level || 1.0;
        AppState.set('pdfDoc', pdfDoc);
        AppState.set('totalPages', totalPages);
        AppState.set('currentPage', currentPage);
        AppState.set('zoomLevel', zoomLevel);

        if (state.annotations) {
          AppState.state.annotationsByPage = state.annotations;
        }
        if (state.ink_pages) {
          AppState.state.inkByPage = state.ink_pages;
        }

        showViewer();
        await renderPage(currentPage);
      }
    } catch (e) {
      console.error('loadFromState failed:', e);
      StatusBar.setMessage(`加载失败: ${e.message}`);
    }
  }

  async function getPdfjs() {
    if (window.pdfjsLib) return window.pdfjsLib;
    let base = '/vendor/pdfjs';
    if (window.electronAPI?.getPdfBasePath) {
      const packagedBase = await window.electronAPI.getPdfBasePath();
      if (packagedBase) base = packagedBase;
    }
    return new Promise((resolve) => {
      const script = document.createElement('script');
      script.src = `${base}/pdf.min.js`.replace(/\\/g, '/');
      script.onload = () => {
        window.pdfjsLib.GlobalWorkerOptions.workerSrc = `${base}/pdf.worker.min.js`.replace(/\\/g, '/');
        resolve(window.pdfjsLib);
      };
      document.head.appendChild(script);
    });
  }

  async function renderPage(pageNum) {
    if (!pdfDoc) return;

    if (renderTask) {
      try { await renderTask.cancel(); } catch (_) {}
    }

    currentPage = Math.max(0, Math.min(pageNum, totalPages - 1));
    AppState.set('currentPage', currentPage);

    const page = await pdfDoc.getPage(currentPage + 1);
    const scale = zoomLevel * RENDER_SCALE;
    const viewport = page.getViewport({ scale });

    canvas.width = viewport.width;
    canvas.height = viewport.height;
    canvas.style.width = `${viewport.width / RENDER_SCALE}px`;
    canvas.style.height = `${viewport.height / RENDER_SCALE}px`;

    pageWidth = viewport.width;
    pageHeight = viewport.height;

    inkCanvas.width = viewport.width;
    inkCanvas.height = viewport.height;
    inkCanvas.style.width = canvas.style.width;
    inkCanvas.style.height = canvas.style.height;

    const annotLayer = document.getElementById('annotation-layer');
    annotLayer.style.width = canvas.style.width;
    annotLayer.style.height = canvas.style.height;

    ctx.imageSmoothingEnabled = true;
    if ('imageSmoothingQuality' in ctx) ctx.imageSmoothingQuality = 'high';

    renderTask = page.render({ canvasContext: ctx, viewport });
    await renderTask.promise;

    updateLabels();
    Annotations.refresh();
    InkEngine.redraw();

    ApiClient.navigatePage(currentPage).catch(() => {});
  }

  function updateLabels() {
    document.getElementById('page-label').textContent = `${currentPage + 1} / ${totalPages}`;
    document.getElementById('zoom-label').textContent = `${Math.round(zoomLevel * 100)}%`;
  }

  function zoomIn() {
    if (zoomLevel < 3.0) {
      zoomLevel = Math.min(3.0, zoomLevel + 0.1);
      AppState.set('zoomLevel', zoomLevel);
      renderPage(currentPage);
    }
  }

  function zoomOut() {
    if (zoomLevel > 0.5) {
      zoomLevel = Math.max(0.5, zoomLevel - 0.1);
      AppState.set('zoomLevel', zoomLevel);
      renderPage(currentPage);
    }
  }

  function zoomReset() {
    zoomLevel = 1.0;
    AppState.set('zoomLevel', zoomLevel);
    renderPage(currentPage);
  }

  async function prevPage() {
    if (currentPage > 0) {
      await renderPage(currentPage - 1);
      Sidebar.refreshList();
    }
  }

  async function nextPage() {
    if (currentPage < totalPages - 1) {
      await renderPage(currentPage + 1);
      Sidebar.refreshList();
    }
  }

  function onScroll(e) {
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault();
      if (e.deltaY < 0) zoomIn();
      else zoomOut();
    }
  }

  // ── Canvas interaction (annotation dragging) ──
  let pressing = false;
  let pressPos = null;
  let didDrag = false;
  let dragMarker = null;
  let dragOffset = null;
  let suppressClickUntil = 0;

  function startPointerSession() {
    pressing = true;
    document.addEventListener('mousemove', onDocumentDrag);
    document.addEventListener('mouseup', onDocumentRelease);
  }

  function endPointerSession() {
    document.removeEventListener('mousemove', onDocumentDrag);
    document.removeEventListener('mouseup', onDocumentRelease);
    pressing = false;
  }

  function onDocumentDrag(e) {
    onCanvasDrag(e);
  }

  async function onDocumentRelease(e) {
    endPointerSession();
    await onCanvasRelease(e);
  }

  function wasDragging() {
    return didDrag || Date.now() < suppressClickUntil;
  }

  function beginAnnotationDrag(e, page, index) {
    if (AppState.isInkToolActive()) return;
    if (e.button !== 0) return;
    e.preventDefault();

    const items = AppState.getPageAnnotations(page);
    const marker = items[index];
    if (!marker) return;

    const coords = canvasCoords(e);
    const display = toDisplayCoords(coords.x, coords.y);
    const pdf = pdfCoords(coords.x, coords.y);

    dragMarker = { ...marker, page, index };
    dragOffset = { x: pdf.x - marker.x, y: pdf.y - marker.y };
    pressPos = display;
    didDrag = false;

    Sidebar.selectMarker(page, index);
    startPointerSession();
  }

  function canvasCoords(e) {
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    return {
      x: (e.clientX - rect.left) * scaleX,
      y: (e.clientY - rect.top) * scaleY,
    };
  }

  function pdfCoords(cx, cy) {
    const scale = zoomLevel * RENDER_SCALE;
    return { x: cx / scale, y: cy / scale };
  }

  function onCanvasPress(e) {
    if (e.target.closest('.annot-popup') || e.target.closest('.annot-popup__close')) return;

    const tool = AppState.get('canvasTool');
    const coords = canvasCoords(e);
    const display = toDisplayCoords(coords.x, coords.y);
    pressPos = display;
    didDrag = false;

    if (tool === 'eraser') {
      InkEngine.eraseAt(coords.x, coords.y);
      startPointerSession();
      return;
    }

    if (tool === 'pen' || tool === 'highlighter') {
      InkEngine.startStroke(tool, coords.x, coords.y);
      startPointerSession();
      return;
    }

    const marker = Annotations.findMarkerAt(display.x, display.y);
    if (marker !== null) {
      beginAnnotationDrag(e, marker.page, marker.index);
      return;
    } else {
      Sidebar.deselectMarker();
      Annotations.closeAllPopups();

      if (AppState.get('addingAnnotation')) {
        const pdf = pdfCoords(coords.x, coords.y);
        Sidebar.createAnnotationAt(pdf.x, pdf.y);
        return;
      }
    }
  }

  function onCanvasDrag(e) {
    if (!pressing) return;
    const coords = canvasCoords(e);
    const display = toDisplayCoords(coords.x, coords.y);
    const tool = AppState.get('canvasTool');

    if (tool === 'eraser') {
      InkEngine.eraseAt(coords.x, coords.y);
      return;
    }

    if (tool === 'pen' || tool === 'highlighter') {
      InkEngine.extendStroke(coords.x, coords.y);
      return;
    }

    if (dragMarker && dragOffset && pressPos) {
      const dx = Math.abs(display.x - pressPos.x);
      const dy = Math.abs(display.y - pressPos.y);
      if (dx > 3 || dy > 3) didDrag = true;

      if (didDrag) {
        const pdf = pdfCoords(coords.x, coords.y);
        const clamped = clampPdfPoint(pdf.x - dragOffset.x, pdf.y - dragOffset.y, dragMarker);
        const items = AppState.getPageAnnotations(dragMarker.page);
        const item = items[dragMarker.index];
        if (item) {
          item.x = clamped.x;
          item.y = clamped.y;
          AppState.setPageAnnotations(dragMarker.page, items);
          Annotations.moveElement(dragMarker.page, dragMarker.index, clamped.x, clamped.y);
        }
      }
    }
  }

  async function onCanvasRelease(e) {
    const tool = AppState.get('canvasTool');

    if (tool === 'pen' || tool === 'highlighter') {
      InkEngine.finishStroke();
    }

    if (didDrag && dragMarker) {
      suppressClickUntil = Date.now() + 250;
      const items = AppState.getPageAnnotations(dragMarker.page);
      const item = items[dragMarker.index];
      if (item) {
        try {
          await ApiClient.updateAnnotation(dragMarker.page, dragMarker.index, {
            x: item.x,
            y: item.y,
          });
          StatusBar.setMessage(
            item.display_mode === 'inline' ? '译文位置已更新' : '批注位置已更新',
          );
        } catch (err) {
          StatusBar.setMessage(`保存位置失败: ${err.message}`);
        }
      }
      Annotations.refresh();
    }

    pressing = false;
    pressPos = null;
    dragMarker = null;
    dragOffset = null;
    didDrag = false;
  }

  function onCanvasDoubleClick(e) {
    const coords = canvasCoords(e);
    const display = toDisplayCoords(coords.x, coords.y);
    const marker = Annotations.findMarkerAt(display.x, display.y);
    if (!marker) return;

    if (marker.display_mode === 'inline') {
      Annotations.beginInlineEdit(marker);
    } else {
      Annotations.togglePopup(marker);
    }
  }

  function getPageDimensions() { return { width: pageWidth, height: pageHeight }; }
  /** PDF 点 → 画布内部像素（与 pdf.js 渲染一致） */
  function getScale() { return zoomLevel * RENDER_SCALE; }
  /** PDF 点 → 批注层 CSS 像素（与 canvas.style 显示尺寸一致，对齐 web viewer） */
  function getDisplayScale() { return zoomLevel; }
  function getCanvas() { return canvas; }

  function toDisplayCoords(internalX, internalY) {
    return { x: internalX / RENDER_SCALE, y: internalY / RENDER_SCALE };
  }

  function clampPdfPoint(x, y, marker) {
    const scale = getScale();
    const pw = pageWidth / scale;
    const ph = pageHeight / scale;
    if ((marker.display_mode || 'marker') === 'inline') {
      return {
        x: Math.max(0, Math.min(Math.round(x), pw - 1)),
        y: Math.max(0, Math.min(Math.round(y), ph - 1)),
      };
    }
    const size = 22;
    return {
      x: Math.max(0, Math.min(Math.round(x), pw - size)),
      y: Math.max(0, Math.min(Math.round(y), ph - size)),
    };
  }

  return {
    init, showPlaceholder, showViewer, loadFromState, renderPage,
    zoomIn, zoomOut, zoomReset, prevPage, nextPage,
    getPageDimensions, getScale, getDisplayScale, getCanvas,
    canvasCoords, pdfCoords, toDisplayCoords,
    beginAnnotationDrag, wasDragging,
  };
})();
