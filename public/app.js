/**
 * Web 版主入口 — 初始化各模块并恢复本地会话
 */
(async function bootstrap() {
  'use strict';

  StatusBar.setMessage('正在初始化…');

  WebSession.load();

  try {
    const health = await ApiClient.checkHealth();
    if (health?.api_version >= 2) {
      StatusBar.setMessage('后端已就绪');
    } else if (health) {
      StatusBar.setMessage('后端已连接');
    } else {
      StatusBar.setMessage('离线模式：预览与编辑可用，AI 批注需连接后端');
    }
  } catch (err) {
    StatusBar.setMessage('后端连接失败: ' + err.message);
  }

  try {
    const settings = await ApiClient.getSettings();
    if (settings) AppState.set('settings', settings);
  } catch (e) {
    console.warn('[bootstrap] 无法加载设置, 使用默认值');
  }

  Toolbar.init();
  FilePanel.init();
  Preview.init();
  InkEngine.init();
  InkToolbar.init();
  Annotations.init();
  Sidebar.init();
  StatusBar.init();

  try {
    const state = await ApiClient.getState();
    AppState.set('selectedFiles', state.files || []);
    AppState.set('currentFileIndex', state.current_file_index ?? -1);
    FilePanel.refresh();
    if (state.files && state.files.length > 0 && state.pdf_available) {
      await Preview.loadFromState(state);
      Annotations.refresh();
      Sidebar.refreshList();
      StatusBar.setMessage(`已恢复 ${state.files.length} 个文件`);
    } else {
      Preview.showPlaceholder();
    }
  } catch (e) {
    console.warn('[bootstrap] 会话恢复失败', e);
    Preview.showPlaceholder();
  }

  document.addEventListener('keydown', (e) => {
    if (e.ctrlKey && e.key === 'z') {
      e.preventDefault();
      handleUndo();
    }
    if (e.ctrlKey && e.key === 'y') {
      e.preventDefault();
      handleRedo();
    }
    if (e.key === 'Escape') {
      if (AppState.get('addingAnnotation')) {
        AppState.set('addingAnnotation', false);
        document.getElementById('mode-hint').textContent = '滚轮滚动 · ± 缩放 · 双击译文编辑 · 可拖动微调位置';
      }
      if (AppState.isInkToolActive()) {
        InkToolbar.closeTool();
      }
    }
    if ((e.key === 'Delete' || e.key === 'Backspace') && !e.ctrlKey && !e.metaKey && !e.altKey) {
      if (isTextInputFocused()) return;
      const page = AppState.get('selectedMarkerPage');
      const idx = AppState.get('selectedMarkerIndex');
      if (page != null && idx != null) {
        e.preventDefault();
        Sidebar.deleteSelectedMarker();
      }
    }
    if ((e.key === '+' || e.key === '=') && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      Preview.zoomIn();
    }
    if (e.key === '-' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      Preview.zoomOut();
    }
  });

  function isTextInputFocused() {
    const el = document.activeElement;
    if (!el) return false;
    const tag = el.tagName;
    if (tag === 'TEXTAREA' || tag === 'INPUT' || tag === 'SELECT') return true;
    return el.isContentEditable;
  }

  AppState.on('change:currentPage', () => {
    Sidebar.refreshList();
    Sidebar.deselectMarker();
    window.refreshPreview?.();
  });

  AppState.on('annotations:changed', () => {
    window.refreshPreview?.();
  });

  AppState.on('change:currentFileIndex', () => {
    Sidebar.refreshList();
    Sidebar.deselectMarker();
  });

  const undoStack = [];
  const redoStack = [];

  function pushUndo(snapshot) {
    undoStack.push(snapshot);
    if (undoStack.length > 50) undoStack.shift();
    redoStack.length = 0;
  }

  function handleUndo() {
    if (undoStack.length === 0) return;
    const snapshot = undoStack.pop();
    redoStack.push(getCurrentSnapshot());
    restoreSnapshot(snapshot);
    StatusBar.setMessage('撤销');
  }

  function handleRedo() {
    if (redoStack.length === 0) return;
    const snapshot = redoStack.pop();
    undoStack.push(getCurrentSnapshot());
    restoreSnapshot(snapshot);
    StatusBar.setMessage('重做');
  }

  function getCurrentSnapshot() {
    const page = AppState.get('currentPage');
    return {
      page,
      annotations: JSON.parse(JSON.stringify(AppState.getPageAnnotations(page))),
    };
  }

  function restoreSnapshot(snap) {
    AppState.setPageAnnotations(snap.page, snap.annotations);
    WebSession.setAnnotationsForCurrentFile(AppState.state.annotationsByPage);
    Annotations.refresh();
    Sidebar.refreshList();
  }

  window._pushUndo = pushUndo;

  if (location.protocol === 'file:') {
    StatusBar.setMessage('请通过 http://127.0.0.1:3000 访问（直接打开 HTML 无法导入 PDF）');
  } else {
    const health = await ApiClient.checkHealth().catch(() => null);
    const isLocal = location.hostname === '127.0.0.1' || location.hostname === 'localhost';
    if (health?.ok) {
      StatusBar.setMessage('就绪 · 后端已连接');
    } else if (isLocal) {
      StatusBar.setMessage('就绪 · 后端未连接，请先运行 npm run dev 并访问 http://127.0.0.1:3000');
    } else {
      StatusBar.setMessage('就绪 · 后端 API 不可用，请稍后刷新或联系管理员');
    }
  }
  console.log('[bootstrap] Web 前端初始化完成');
})();
