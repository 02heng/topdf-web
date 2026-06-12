/**
 * Web API 通信层 — 无状态服务端 + 浏览器端会话
 */
const ApiClient = (() => {
  const baseUrl = '';

  async function fetchJSON(path, options = {}) {
    const res = await fetch(`${baseUrl}${path}`, {
      headers: { 'Content-Type': 'application/json', ...options.headers },
      ...options,
    });
    if (!res.ok) {
      let detail = '';
      try {
        const body = await res.json();
        detail = body.error ? `: ${body.error}` : '';
      } catch (_) {}
      throw new Error(`API ${path}: ${res.status}${detail}`);
    }
    return res.json();
  }

  async function init() {
    await checkHealth();
    return null;
  }

  async function checkHealth() {
    try {
      return await fetchJSON('/api/health');
    } catch (_) {
      return null;
    }
  }

  async function getState() {
    return WebSession.buildState();
  }

  async function getAnnotations() {
    const state = await getState();
    return {
      pages: state.annotations,
      current_page: state.current_page,
      zoom_level: state.zoom_level,
    };
  }

  async function getPdfArrayBuffer(pdfToken) {
    const f = WebSession.currentFile();
    if (!f) throw new Error('PDF not available');
    return FileStore.getPdfArrayBuffer(f.id);
  }

  async function getInk() {
    return { pages: WebSession.getInkForCurrentFile() };
  }

  async function putInk(pages) {
    WebSession.setInkForCurrentFile(pages);
    return { ok: true };
  }

  async function saveInkToDocument() {
    return { ok: true, message: '墨迹已保存在本地会话中' };
  }

  async function uploadFiles(fileList) {
    const form = new FormData();
    Array.from(fileList).forEach((file) => form.append('files', file));
    let res;
    try {
      res = await fetch('/api/upload', { method: 'POST', body: form });
    } catch (_) {
      throw new Error('无法连接后端，请确认已运行 npm run dev 并通过 http://127.0.0.1:3000 访问');
    }
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.error || `上传失败 (${res.status})`);
    }
    return res.json();
  }

  async function importFiles(files) {
    if (files?.length && files[0] instanceof File) {
      const result = await uploadFiles(files);
      for (const item of result.files || []) {
        const rec = await FileStore.put({
          id: item.id,
          name: item.name,
          mime: item.mime,
          originalBytes: null,
          pdfBytes: (() => {
            const binary = atob(item.pdf_base64);
            const bytes = new Uint8Array(binary.length);
            for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
            return bytes.buffer;
          })(),
          totalPages: item.total_pages,
          createdAt: Date.now(),
        });
        WebSession.addFile({
          id: rec.id,
          name: rec.name,
          totalPages: rec.totalPages,
        });
      }
      if (WebSession.session.currentFileIndex >= 0) {
        const f = WebSession.currentFile();
        WebSession.session.totalPages = f?.totalPages || 0;
        WebSession.persist();
      }
      return { ok: true, added: result.files?.length || 0, files: WebSession.session.files.map((x) => x.name) };
    }
    throw new Error('请使用文件选择器导入');
  }

  async function annotateSingle(pageNum) {
    const f = WebSession.currentFile();
    if (!f) throw new Error('请先导入文件');
    const pdfBase64 = await FileStore.getPdfBase64(f.id);
    return fetchJSON('/api/annotate/page', {
      method: 'POST',
      body: JSON.stringify({
        pdf_base64: pdfBase64,
        page: pageNum,
        settings: AppState.state.settings,
        source_name: f.name,
      }),
    }).then(async (result) => {
      if (result.annotations) {
        const pages = { ...WebSession.getAnnotationsForCurrentFile(), ...result.annotations };
        WebSession.setAnnotationsForCurrentFile(pages);
      }
      return result;
    });
  }

  async function annotatePages(startPage, endPage) {
    return { ok: true, started: true, total: endPage - startPage + 1, client_loop: true };
  }

  async function getAnnotateProgress() {
    return { status: 'idle' };
  }

  async function exportPdf() {
    const f = WebSession.currentFile();
    if (!f) throw new Error('没有可导出的文件');
    const pdfBase64 = await FileStore.getPdfBase64(f.id);
    const fk = WebSession.fileKey(f);
    const res = await fetch('/api/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        pdf_base64: pdfBase64,
        annotations: WebSession.session.annotationsByFile[fk] || {},
        ink_pages: WebSession.session.inkByFile[fk] || {},
        settings: AppState.state.settings,
      }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.error || '导出失败');
    }
    return res.blob();
  }

  async function saveProject() {
    return { ok: true };
  }

  async function openProject() {
    return { ok: true };
  }

  async function getSettings() {
    const stored = localStorage.getItem('topdf_web_settings');
    if (stored) {
      try {
        return JSON.parse(stored);
      } catch (_) {}
    }
    return AppState.state.settings;
  }

  async function saveSettings(settings) {
    localStorage.setItem('topdf_web_settings', JSON.stringify(settings));
    return { ok: true };
  }

  async function selectFile(index, page = null) {
    WebSession.selectFile(index, page);
    return { ok: true };
  }

  async function navigatePage(page) {
    WebSession.session.currentPage = page;
    WebSession.persist();
    return { ok: true, page };
  }

  async function updateAnnotation(pageNum, markerIndex, data) {
    const pages = WebSession.getAnnotationsForCurrentFile();
    const key = String(pageNum);
    const list = pages[key] || [];
    if (markerIndex < 0 || markerIndex >= list.length) throw new Error('批注索引越界');
    list[markerIndex] = { ...list[markerIndex], ...data };
    pages[key] = list;
    WebSession.setAnnotationsForCurrentFile(pages);
    return { ok: true };
  }

  async function addAnnotation(pageNum, data) {
    const pages = WebSession.getAnnotationsForCurrentFile();
    const key = String(pageNum);
    if (!pages[key]) pages[key] = [];
    pages[key].push(data);
    WebSession.setAnnotationsForCurrentFile(pages);
    return { ok: true, index: pages[key].length - 1 };
  }

  async function deleteAnnotation(pageNum, markerIndex) {
    const pages = WebSession.getAnnotationsForCurrentFile();
    const key = String(pageNum);
    const list = pages[key] || [];
    list.splice(markerIndex, 1);
    if (!list.length) delete pages[key];
    else pages[key] = list;
    WebSession.setAnnotationsForCurrentFile(pages);
    return { ok: true };
  }

  async function deleteAllAnnotations(pageNum) {
    const pages = WebSession.getAnnotationsForCurrentFile();
    const key = String(pageNum);
    const count = (pages[key] || []).length;
    delete pages[key];
    WebSession.setAnnotationsForCurrentFile(pages);
    return { ok: true, deleted: count };
  }

  async function undo() {
    return { ok: false, message: 'Web 版撤销请使用 Ctrl+Z（前端栈）' };
  }

  async function removeFile(index) {
    WebSession.removeFileAt(index);
    return { ok: true };
  }

  return {
    init, checkHealth, getState, getAnnotations, getPdfArrayBuffer, getInk, putInk,
    saveInkToDocument, importFiles, annotatePages, getAnnotateProgress, annotateSingle,
    exportPdf, saveProject, openProject, getSettings, saveSettings,
    selectFile, navigatePage, updateAnnotation, addAnnotation,
    deleteAnnotation, deleteAllAnnotations, undo, removeFile, uploadFiles,
  };
})();
