/**
 * 放映模式 API 桥接 — 元数据走 localStorage，PDF 走 IndexedDB（避免 5MB 配额）
 */
(function () {
  const KEY = 'topdf_preview_session';

  function loadBridge() {
    try {
      return JSON.parse(localStorage.getItem(KEY) || '{}');
    } catch (_) {
      return {};
    }
  }

  function saveBridgeData(data) {
    try {
      localStorage.setItem(KEY, JSON.stringify(data));
    } catch (e) {
      console.warn('[preview-bridge] save failed', e);
    }
  }

  function resolvePdfFileId(b) {
    if (b.pdfFileId) return b.pdfFileId;
    const urlId = new URLSearchParams(window.location.search).get('fileId');
    if (urlId) return urlId;
    const token = b.state?.pdf_token || '';
    const parts = token.split(':');
    if (parts.length >= 2 && parts[1]) return parts[1];
    try {
      if (window.opener && !window.opener.closed && window.opener._topdfPreviewPdfId) {
        return window.opener._topdfPreviewPdfId;
      }
    } catch (_) {}
    return null;
  }

  function base64ToArrayBuffer(b64) {
    const binary = atob(b64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    return bytes.buffer;
  }

  const PREVIEW_SLOT_ID = '__topdf_preview__';

  function getStore() {
    return window.FileStore || (typeof FileStore !== 'undefined' ? FileStore : null);
  }

  async function readPreviewPdf(store) {
    if (!store) return null;
    try {
      if (typeof store.getPreviewPdfArrayBuffer === 'function') {
        return await store.getPreviewPdfArrayBuffer();
      }
      if (typeof store.getPdfArrayBuffer === 'function') {
        return await store.getPdfArrayBuffer(PREVIEW_SLOT_ID);
      }
    } catch (e) {
      console.warn('[preview-bridge] preview slot read failed', e);
    }
    return null;
  }

  async function readPdfFromStore(fileId, store) {
    if (!store || !fileId) return null;
    try {
      return await store.getPdfArrayBuffer(fileId);
    } catch (e) {
      console.warn('[preview-bridge] read PDF failed', fileId, e);
      return null;
    }
  }

  async function loadPdfBytes(b) {
    const store = getStore();
    const stores = store ? [store] : [];

    for (const s of stores) {
      const previewBytes = await readPreviewPdf(s);
      if (previewBytes) return previewBytes;
    }

    const fileId = resolvePdfFileId(b);
    if (fileId) {
      for (const s of stores) {
        const bytes = await readPdfFromStore(fileId, s);
        if (bytes) return bytes;
      }
    }

    if (b.pdfBase64) {
      return base64ToArrayBuffer(b.pdfBase64);
    }
    return null;
  }

  function ensureState(b) {
    const state = { ...(b.state || {}) };
    const fileId = resolvePdfFileId(b);
    if (fileId && !state.pdf_available) {
      state.pdf_available = true;
      state.pdf_token = state.pdf_token || `0:${fileId}:preview`;
      state.total_pages = state.total_pages || 0;
    }
    return state;
  }

  function jsonResponse(data, status = 200) {
    return new Response(JSON.stringify(data), {
      status,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  const originalFetch = window.fetch.bind(window);
  window.fetch = async (input, init = {}) => {
    const url = typeof input === 'string' ? input : input.url;
    const b = loadBridge();

    if (url.includes('/api/state')) {
      return jsonResponse(ensureState(b));
    }

    if (url.includes('/api/pdf')) {
      const pdfBytes = await loadPdfBytes(b);
      if (!pdfBytes) {
        return new Response('PDF not available — 请关闭此页，回到主窗口重新点击「放映」', { status: 404 });
      }
      return new Response(pdfBytes, {
        status: 200,
        headers: { 'Content-Type': 'application/pdf' },
      });
    }

    if (url.includes('/api/ink') && (!init.method || init.method === 'GET')) {
      const fk = resolvePdfFileId(b) || '';
      const ink = (b.inkByFile && fk && b.inkByFile[fk]) || b.state?.ink_pages || {};
      return jsonResponse({ pages: ink });
    }

    if (url.includes('/api/ink') && init.method === 'PUT') {
      try {
        const body = JSON.parse(init.body || '{}');
        const fk = resolvePdfFileId(b) || 'preview';
        const next = { ...b };
        if (!next.inkByFile) next.inkByFile = {};
        next.inkByFile[fk] = body.pages || {};
        if (next.state) next.state.ink_pages = body.pages || {};
        saveBridgeData(next);
      } catch (_) {}
      return jsonResponse({ ok: true });
    }

    if (url.includes('/api/navigate')) {
      try {
        const body = JSON.parse(init.body || '{}');
        const next = { ...b };
        if (next.state) next.state.current_page = body.page;
        saveBridgeData(next);
      } catch (_) {}
      return jsonResponse({ ok: true });
    }

    if (url.includes('/api/ink/save')) {
      return jsonResponse({ ok: true, message: 'Web 预览模式：墨迹保存在本地' });
    }

    return originalFetch(input, init);
  };
})();
