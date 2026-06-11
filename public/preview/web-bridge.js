/**
 * 放映模式 API 桥接 — 从 localStorage 读取主应用写入的预览会话
 */
(function () {
  const KEY = 'topdf_preview_session';
  let bridge = null;

  function loadBridge() {
    if (bridge) return bridge;
    try {
      bridge = JSON.parse(localStorage.getItem(KEY) || '{}');
    } catch (_) {
      bridge = {};
    }
    return bridge;
  }

  function base64ToArrayBuffer(b64) {
    const binary = atob(b64);
    const len = binary.length;
    const bytes = new Uint8Array(len);
    for (let i = 0; i < len; i += 1) bytes[i] = binary.charCodeAt(i);
    return bytes.buffer;
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
      return jsonResponse(b.state || {});
    }

    if (url.includes('/api/pdf')) {
      if (!b.pdfBase64) {
        return new Response('PDF not available', { status: 404 });
      }
      return new Response(base64ToArrayBuffer(b.pdfBase64), {
        status: 200,
        headers: { 'Content-Type': 'application/pdf' },
      });
    }

    if (url.includes('/api/ink') && (!init.method || init.method === 'GET')) {
      const fk = b.state?.pdf_token?.split(':')?.[1] || '';
      const ink = (b.inkByFile && fk && b.inkByFile[fk]) || b.state?.ink_pages || {};
      return jsonResponse({ pages: ink });
    }

    if (url.includes('/api/ink') && init.method === 'PUT') {
      try {
        const body = JSON.parse(init.body || '{}');
        const fk = b.state?.pdf_token?.split(':')?.[1] || 'preview';
        if (!b.inkByFile) b.inkByFile = {};
        b.inkByFile[fk] = body.pages || {};
        if (b.state) b.state.ink_pages = body.pages || {};
        localStorage.setItem(KEY, JSON.stringify(b));
      } catch (_) {}
      return jsonResponse({ ok: true });
    }

    if (url.includes('/api/navigate')) {
      try {
        const body = JSON.parse(init.body || '{}');
        if (b.state) b.state.current_page = body.page;
        localStorage.setItem(KEY, JSON.stringify(b));
      } catch (_) {}
      return jsonResponse({ ok: true });
    }

    if (url.includes('/api/ink/save')) {
      return jsonResponse({ ok: true, message: 'Web 预览模式：墨迹保存在本地' });
    }

    return originalFetch(input, init);
  };
})();
