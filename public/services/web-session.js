/**
 * 浏览器端会话状态 — 对齐 electron_backend HeadlessApp 的 build_state 结构
 */
const WebSession = (() => {
  const STORAGE_KEY = 'topdf_web_session_v1';

  const session = {
    files: [],
    currentFileIndex: -1,
    currentPage: 0,
    totalPages: 0,
    zoomLevel: 1.0,
    annotationsByFile: {},
    inkByFile: {},
    settings: null,
  };

  function fileKey(fileMeta) {
    return fileMeta?.id || fileMeta?.name || '';
  }

  function currentFile() {
    const idx = session.currentFileIndex;
    if (idx < 0 || idx >= session.files.length) return null;
    return session.files[idx];
  }

  function getAnnotationsForCurrentFile() {
    const f = currentFile();
    if (!f) return {};
    return session.annotationsByFile[fileKey(f)] || {};
  }

  function setAnnotationsForCurrentFile(pages) {
    const f = currentFile();
    if (!f) return;
    session.annotationsByFile[fileKey(f)] = pages;
    persist();
  }

  function getInkForCurrentFile() {
    const f = currentFile();
    if (!f) return {};
    return session.inkByFile[fileKey(f)] || {};
  }

  function setInkForCurrentFile(pages) {
    const f = currentFile();
    if (!f) return;
    session.inkByFile[fileKey(f)] = pages;
    persist();
  }

  function buildState() {
    const f = currentFile();
    const fk = f ? fileKey(f) : '';
    const ann = fk ? (session.annotationsByFile[fk] || {}) : {};
    const ink = fk ? (session.inkByFile[fk] || {}) : {};
    const annPages = {};
    Object.keys(ann).forEach((p) => {
      annPages[String(p)] = ann[p];
    });
    const inkPages = {};
    Object.keys(ink).forEach((p) => {
      inkPages[String(p)] = ink[p];
    });

    return {
      files: session.files.map((x) => x.name),
      fileIds: session.files.map((x) => x.id),
      current_file_index: session.currentFileIndex,
      pdf_available: !!f,
      pdf_token: f ? `${session.currentFileIndex}:${f.id}:${f.name}` : '',
      current_page: session.currentPage,
      total_pages: session.totalPages,
      zoom_level: session.zoomLevel,
      annotations: annPages,
      ink_pages: inkPages,
    };
  }

  function persist() {
    try {
      const payload = {
        files: session.files,
        currentFileIndex: session.currentFileIndex,
        currentPage: session.currentPage,
        totalPages: session.totalPages,
        zoomLevel: session.zoomLevel,
        annotationsByFile: session.annotationsByFile,
        inkByFile: session.inkByFile,
      };
      localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
    } catch (e) {
      console.warn('[WebSession] persist failed', e);
    }
  }

  function load() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      const data = JSON.parse(raw);
      session.files = data.files || [];
      session.currentFileIndex = data.currentFileIndex ?? -1;
      session.currentPage = data.currentPage ?? 0;
      session.totalPages = data.totalPages ?? 0;
      session.zoomLevel = data.zoomLevel ?? 1.0;
      session.annotationsByFile = data.annotationsByFile || {};
      session.inkByFile = data.inkByFile || {};
    } catch (e) {
      console.warn('[WebSession] load failed', e);
    }
  }

  function addFile(meta) {
    const isFirst = session.files.length === 0;
    session.files.push(meta);
    if (session.currentFileIndex < 0) {
      session.currentFileIndex = 0;
      session.currentPage = 0;
    }
    if (isFirst || session.currentFileIndex === session.files.length - 1) {
      session.totalPages = meta.totalPages || 0;
    }
    persist();
  }

  function removeFileAt(index) {
    if (index < 0 || index >= session.files.length) return;
    const removed = session.files[index];
    const fk = fileKey(removed);
    session.files.splice(index, 1);
    delete session.annotationsByFile[fk];
    delete session.inkByFile[fk];
    FileStore.remove(removed.id).catch(() => {});

    if (session.files.length === 0) {
      session.currentFileIndex = -1;
      session.totalPages = 0;
      session.currentPage = 0;
    } else if (index === session.currentFileIndex) {
      session.currentFileIndex = Math.min(index, session.files.length - 1);
    } else if (index < session.currentFileIndex) {
      session.currentFileIndex -= 1;
    }
    persist();
  }

  function selectFile(index, page = null) {
    if (index < 0 || index >= session.files.length) throw new Error('文件索引越界');
    session.currentFileIndex = index;
    const f = session.files[index];
    session.totalPages = f.totalPages || 0;
    session.currentPage = page != null
      ? Math.max(0, Math.min(page, session.totalPages - 1))
      : 0;
    persist();
  }

  function exportProjectBlob() {
    const project = {
      version: 1,
      files: session.files,
      currentFileIndex: session.currentFileIndex,
      currentPage: session.currentPage,
      annotationsByFile: session.annotationsByFile,
      inkByFile: session.inkByFile,
      settings: AppState.state.settings,
      exportedAt: new Date().toISOString(),
    };
    return new Blob([JSON.stringify(project, null, 2)], { type: 'application/json' });
  }

  async function importProjectBlob(blob) {
    const text = await blob.text();
    const project = JSON.parse(text);
    session.files = project.files || [];
    session.currentFileIndex = project.currentFileIndex ?? (session.files.length ? 0 : -1);
    session.currentPage = project.currentPage ?? 0;
    session.annotationsByFile = project.annotationsByFile || {};
    session.inkByFile = project.inkByFile || {};
    if (project.settings) AppState.set('settings', project.settings);
    const f = currentFile();
    session.totalPages = f?.totalPages || 0;
    persist();
    return project;
  }

  function savePreviewBridge() {
    const f = currentFile();
    if (!f) return Promise.resolve(false);
    return FileStore.getPdfBase64(f.id).then((pdfBase64) => {
      const bridge = {
        state: buildState(),
        pdfBase64,
        inkByFile: session.inkByFile,
        annotationsByFile: session.annotationsByFile,
        savedAt: Date.now(),
      };
      localStorage.setItem('topdf_preview_session', JSON.stringify(bridge));
      return true;
    });
  }

  return {
    session,
    load,
    persist,
    buildState,
    currentFile,
    fileKey,
    addFile,
    removeFileAt,
    selectFile,
    getAnnotationsForCurrentFile,
    setAnnotationsForCurrentFile,
    getInkForCurrentFile,
    setInkForCurrentFile,
    exportProjectBlob,
    importProjectBlob,
    savePreviewBridge,
  };
})();
