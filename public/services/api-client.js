/**
 * Web API 通信层 — 无状态服务端 + 浏览器端会话
 */
const ApiClient = (() => {
  const baseUrl = '';
  const SERVER_UPLOAD_MAX = 4 * 1024 * 1024; // Vercel 请求体约 4.5MB，留余量

  function isLocalDev() {
    return location.hostname === '127.0.0.1' || location.hostname === 'localhost';
  }

  async function loadPdfjs() {
    if (window.pdfjsLib) return window.pdfjsLib;
    const base = '/vendor/pdfjs';
    return new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = `${base}/pdf.min.js`;
      script.onload = () => {
        window.pdfjsLib.GlobalWorkerOptions.workerSrc = `${base}/pdf.worker.min.js`;
        resolve(window.pdfjsLib);
      };
      script.onerror = () => reject(new Error('PDF.js 加载失败'));
      document.head.appendChild(script);
    });
  }

  async function countPdfPages(pdfBytes) {
    const pdfjsLib = await loadPdfjs();
    const doc = await pdfjsLib.getDocument({ data: pdfBytes }).promise;
    const total = doc.numPages;
    doc.destroy();
    return total;
  }

  async function importPdfLocally(file) {
    const pdfBytes = await file.arrayBuffer();
    const totalPages = await countPdfPages(pdfBytes);
    const rec = await FileStore.saveUploadedFile(file, pdfBytes, { totalPages });
    WebSession.addFile({
      id: rec.id,
      name: rec.name,
      totalPages: rec.totalPages,
    });
    return rec;
  }

  function ingestServerUploadItem(item) {
    const binary = atob(item.pdf_base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    const rec = {
      id: item.id,
      name: item.name,
      mime: item.mime,
      originalBytes: null,
      pdfBytes: bytes.buffer,
      totalPages: item.total_pages,
      createdAt: Date.now(),
    };
    return FileStore.put(rec).then(() => {
      WebSession.addFile({
        id: rec.id,
        name: rec.name,
        totalPages: rec.totalPages,
      });
      return rec;
    });
  }

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
    for (const file of fileList) {
      if (file.size > SERVER_UPLOAD_MAX) {
        throw new Error(
          `${file.name} 超过 4MB，Vercel 线上无法上传大文件。请先在本地转为 PDF 后再导入，或使用本地开发环境。`,
        );
      }
    }
    const form = new FormData();
    Array.from(fileList).forEach((file) => form.append('files', file));
    let res;
    try {
      res = await fetch('/api/upload', { method: 'POST', body: form });
    } catch (err) {
      if (isLocalDev()) {
        throw new Error('无法连接后端，请先运行 npm run dev 并访问 http://127.0.0.1:3000');
      }
      throw new Error('无法连接后端 API，请检查网络后重试');
    }
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.error || `上传失败 (${res.status})`);
    }
    return res.json();
  }

  async function importFiles(files) {
    if (!files?.length || !(files[0] instanceof File)) {
      throw new Error('请使用文件选择器导入');
    }

    const pdfFiles = [];
    const serverFiles = [];
    for (const file of files) {
      const lower = file.name.toLowerCase();
      if (lower.endsWith('.pdf')) pdfFiles.push(file);
      else if (lower.endsWith('.ppt') || lower.endsWith('.pptx')) serverFiles.push(file);
      else throw new Error(`不支持的文件类型: ${file.name}`);
    }

    for (const file of pdfFiles) {
      await importPdfLocally(file);
    }

    if (serverFiles.length) {
      const result = await uploadFiles(serverFiles);
      for (const item of result.files || []) {
        await ingestServerUploadItem(item);
      }
    }

    if (WebSession.session.currentFileIndex >= 0) {
      const f = WebSession.currentFile();
      WebSession.session.totalPages = f?.totalPages || 0;
      WebSession.persist();
    }
    return {
      ok: true,
      added: pdfFiles.length + serverFiles.length,
      files: WebSession.session.files.map((x) => x.name),
    };
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
