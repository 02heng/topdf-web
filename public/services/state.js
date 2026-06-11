/**
 * 应用全局状态管理
 * 对齐 Python App 类中的所有状态变量
 */
const AppState = (() => {
  const state = {
    selectedFiles: [],
    currentFileIndex: -1,

    pdfDoc: null,
    currentPage: 0,
    totalPages: 0,
    zoomLevel: 1.0,

    annotationsByPage: {},
    selectedMarkerIndex: null,
    selectedMarkerPage: null,

    inkByPage: {},
    canvasTool: null,
    inkColor: '#ef4444',
    currentInkStroke: null,

    addingAnnotation: false,
    annotating: false,

    settings: {
      llm: {
        provider: 'deepseek',
        openai: { api_key: '', model: 'gpt-4o', temperature: 0.3, max_tokens: 4096 },
        ollama: { base_url: 'http://localhost:11434', model: 'llama3:70b', temperature: 0.3 },
        deepseek: { api_key: '', model: 'deepseek-v4-pro', temperature: 0.3, max_tokens: 4096, base_url: 'https://api.deepseek.com' },
        xiaomi: { api_key: '', model: 'mimo-v2.5', temperature: 0.3, max_tokens: 4096, api_mode: 'token_plan', base_url: 'https://token-plan-cn.xiaomimimo.com/v1' },
        agnes: { api_key: '', model: 'agnes-2.0-flash', temperature: 0.3, max_tokens: 4096, base_url: 'https://apihub.agnes-ai.com/v1' },
      },
      annotation: { mode: 'overlay', detail_level: 'detailed', style: { font_family: '', font_size: 12, color: '#333333', background: '#FFFFCC' } },
      app: { language: 'zh-CN', theme: 'system', recent_files_limit: 10, auto_save: true },
    },
  };

  const listeners = new Map();

  function on(event, cb) {
    if (!listeners.has(event)) listeners.set(event, []);
    listeners.get(event).push(cb);
  }

  function emit(event, data) {
    (listeners.get(event) || []).forEach((cb) => cb(data));
  }

  function get(key) { return state[key]; }

  function set(key, value) {
    state[key] = value;
    emit(`change:${key}`, value);
    emit('change', { key, value });
  }

  function getPageAnnotations(page = null) {
    const p = page ?? state.currentPage;
    return state.annotationsByPage[String(p)] || [];
  }

  function setPageAnnotations(page, markers) {
    state.annotationsByPage[String(page)] = markers;
    emit('annotations:changed', { page });
  }

  function isInkToolActive() {
    const tool = state.canvasTool;
    return tool === 'pen' || tool === 'highlighter' || tool === 'eraser';
  }

  return { state, on, emit, get, set, getPageAnnotations, setPageAnnotations, isInkToolActive };
})();
