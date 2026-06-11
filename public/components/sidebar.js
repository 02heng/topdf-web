/**
 * 批注侧边栏 — 对齐 App._create_sidebar / _update_annotation_list / _select_marker
 * 批注列表 + 编辑区 + 样式面板 + 添加/删除（修改自动保存并同步后端预览）
 */
const Sidebar = (() => {
  const ANNOTATION_COLORS = [
    '#7C3AED', '#8B5CF6', '#EC4899', '#06B6D4', '#10B981',
    '#F59E0B', '#000000', '#FFFFFF', '#78350F', '#2563EB',
  ];

  const PRESETS = {
    inline: { display_mode: 'inline', color: '#7C2D12', font_size: 12, placement: 'right', label: '原位译文' },
    marker: { display_mode: 'marker', color: '#7C3AED', font_size: 11, placement: 'right', label: '标记批注' },
    term: { display_mode: 'inline', color: '#0369A1', font_size: 10, placement: 'right', label: '术语注释' },
    emphasis: { display_mode: 'inline', color: '#DC2626', font_size: 15, placement: 'above', label: '重点提示' },
    note: { display_mode: 'inline', color: '#059669', font_size: 11, placement: 'below', label: '补充说明' },
    custom: { display_mode: 'inline', color: '#333333', font_size: 12, placement: 'right', label: '当前样式' },
  };

  let autoSaveTimer = null;
  let suppressAutoSave = false;

  function init() {
    initColorSwatches();
    initEventListeners();
    populateFontSelect();
  }

  function initColorSwatches() {
    const container = document.getElementById('color-swatches');
    ANNOTATION_COLORS.forEach((color) => {
      const btn = document.createElement('button');
      btn.className = 'color-swatch';
      btn.style.background = color;
      btn.dataset.color = color;
      if (color === '#FFFFFF') btn.style.boxShadow = 'inset 0 0 0 1px var(--border)';
      btn.addEventListener('click', () => setColor(color));
      container.appendChild(btn);
    });
  }

  function initEventListeners() {
    document.getElementById('btn-add-annotation').addEventListener('click', enterAddMode);
    document.getElementById('btn-delete-annotation').addEventListener('click', deleteAnnotation);
    document.getElementById('btn-delete-all').addEventListener('click', deleteAllAnnotations);
    document.getElementById('btn-color-picker').addEventListener('click', pickColor);

    document.getElementById('annotation-editor').addEventListener('input', scheduleAutoSave);
    document.getElementById('font-size-input').addEventListener('input', applyStyleLive);
    document.getElementById('font-size-input').addEventListener('change', applyStyleLive);
    document.getElementById('font-family-select').addEventListener('change', applyStyleLive);

    document.querySelectorAll('#orientation-segment .segmented__btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('#orientation-segment .segmented__btn').forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
        applyStyleLive();
      });
    });

    document.getElementById('preset-select').addEventListener('change', (e) => {
      const preset = PRESETS[e.target.value];
      if (preset && e.target.value !== 'custom') {
        applyPresetToSidebar(preset);
      }
    });
  }

  function populateFontSelect() {
    const select = document.getElementById('font-family-select');
    const fonts = [
      'Microsoft YaHei', 'Microsoft YaHei UI', 'SimSun', 'SimHei', 'KaiTi',
      'FangSong', 'PingFang SC', 'Noto Sans CJK SC', 'Arial', 'Times New Roman',
      'Courier New', 'Georgia', 'Verdana',
    ];
    fonts.forEach((f) => {
      const opt = document.createElement('option');
      opt.value = f;
      opt.textContent = f;
      select.appendChild(opt);
    });
    select.value = 'Microsoft YaHei';
  }

  function applyPresetToSidebar(preset) {
    setColor(preset.color, { skipPersist: true });
    document.getElementById('font-size-input').value = preset.font_size;
  }

  async function syncFromBackend() {
    const state = await ApiClient.getState();
    if (state?.annotations) {
      AppState.state.annotationsByPage = state.annotations;
    }
    window.electronAPI?.refreshPreview?.();
    return state;
  }

  function scheduleAutoSave() {
    if (suppressAutoSave) return;
    clearTimeout(autoSaveTimer);
    autoSaveTimer = setTimeout(() => {
      persistSelectedAnnotation({ silent: true }).catch((e) => {
        StatusBar.setMessage(`保存失败: ${e.message}`);
      });
    }, 400);
  }

  async function flushPendingSave() {
    clearTimeout(autoSaveTimer);
    autoSaveTimer = null;
    await persistSelectedAnnotation({ silent: true });
  }

  function readEditorFields() {
    return {
      text: document.getElementById('annotation-editor').value.trim(),
      color: AppState.state.annotationColor || '#7C3AED',
      font_size: parseInt(document.getElementById('font-size-input').value, 10) || 12,
      font_family: document.getElementById('font-family-select').value || '',
      text_orientation: getOrientation(),
    };
  }

  async function persistSelectedAnnotation({ silent = false } = {}) {
    const page = AppState.get('selectedMarkerPage');
    const idx = AppState.get('selectedMarkerIndex');
    if (page == null || idx == null) return;

    const items = AppState.getPageAnnotations(page);
    const item = items[idx];
    if (!item) return;

    const fields = readEditorFields();
    if (!fields.text) return;

    Object.assign(item, fields);
    AppState.setPageAnnotations(page, items);
    Annotations.refresh();
    refreshList();

    await ApiClient.updateAnnotation(page, idx, fields);
    if (!silent) StatusBar.setMessage('批注已保存');
  }

  function setColor(color, { skipPersist = false } = {}) {
    document.querySelectorAll('.color-swatch').forEach((s) =>
      s.classList.toggle('active', s.dataset.color === color)
    );
    AppState.state.annotationColor = color;

    const page = AppState.get('selectedMarkerPage');
    const idx = AppState.get('selectedMarkerIndex');
    if (page != null && idx != null) {
      const items = AppState.getPageAnnotations(page);
      if (items[idx]) {
        items[idx].color = color;
        AppState.setPageAnnotations(page, items);
        Annotations.refresh();
        if (!skipPersist) scheduleAutoSave();
      }
    }
  }

  function pickColor() {
    const input = document.createElement('input');
    input.type = 'color';
    input.value = AppState.state.annotationColor || '#7C3AED';
    input.addEventListener('input', () => setColor(input.value));
    input.click();
  }

  function refreshList() {
    const container = document.getElementById('annotation-list');
    container.innerHTML = '';

    const page = AppState.get('currentPage');
    const items = AppState.getPageAnnotations(page);
    const selectedPage = AppState.get('selectedMarkerPage');
    const selectedIdx = AppState.get('selectedMarkerIndex');

    items.forEach((item, idx) => {
      const isSelected = selectedPage === page && selectedIdx === idx;
      const kindLabel = getKindLabel(item);
      const preview = truncateText(item.text || '', 40);

      const row = document.createElement('div');
      row.className = `annotation-row${isSelected ? ' selected' : ''}`;
      row.innerHTML = `
        <span class="annotation-row__color" style="color:${item.color || '#7C3AED'}">●</span>
        <span class="annotation-row__text">${kindLabel ? `[${kindLabel}] ` : ''}${escapeHtml(preview)}</span>
        <button class="annotation-row__delete">✕</button>
      `;

      row.addEventListener('click', (e) => {
        if (e.target.closest('.annotation-row__delete')) return;
        selectMarker(page, idx);
      });

      row.querySelector('.annotation-row__delete').addEventListener('click', (e) => {
        e.stopPropagation();
        deleteMarkerAt(page, idx);
      });

      container.appendChild(row);
    });
  }

  function selectMarker(page, idx) {
    suppressAutoSave = true;
    AppState.set('selectedMarkerPage', page);
    AppState.set('selectedMarkerIndex', idx);

    const items = AppState.getPageAnnotations(page);
    const item = items[idx];
    if (!item) {
      suppressAutoSave = false;
      return;
    }

    document.getElementById('annotation-editor').value = item.text || '';
    document.getElementById('font-size-input').value = item.font_size || 12;

    const fontSelect = document.getElementById('font-family-select');
    if (item.font_family) fontSelect.value = item.font_family;

    setColor(item.color || '#7C3AED', { skipPersist: true });

    const orientBtns = document.querySelectorAll('#orientation-segment .segmented__btn');
    orientBtns.forEach((b) => b.classList.toggle('active', b.dataset.value === (item.text_orientation || 'horizontal')));

    refreshList();
    Annotations.refresh();
    suppressAutoSave = false;
  }

  function deselectMarker() {
    suppressAutoSave = true;
    AppState.set('selectedMarkerPage', null);
    AppState.set('selectedMarkerIndex', null);
    document.getElementById('annotation-editor').value = '';
    refreshList();
    Annotations.refresh();
    suppressAutoSave = false;
  }

  function enterAddMode() {
    const presetId = document.getElementById('preset-select').value;
    const preset = PRESETS[presetId] || PRESETS.inline;
    deselectMarker();
    applyPresetToSidebar(preset);
    AppState.set('addingAnnotation', true);
    document.getElementById('mode-hint').textContent = `请在页面点击放置「${preset.label}」`;
  }

  async function createAnnotationAt(pdfX, pdfY) {
    const presetId = document.getElementById('preset-select').value;
    const preset = PRESETS[presetId] || PRESETS.inline;
    const fields = readEditorFields();

    const text = fields.text || (preset.display_mode === 'marker' ? '新批注' : '请输入译文');

    const newMarker = {
      x: Math.round(pdfX),
      y: Math.round(pdfY),
      text,
      color: fields.color || preset.color,
      display_mode: preset.display_mode,
      font_size: fields.font_size || preset.font_size,
      font_family: fields.font_family,
      text_orientation: fields.text_orientation,
      placement: preset.placement,
      style_kind: presetId,
    };

    const page = AppState.get('currentPage');
    AppState.set('addingAnnotation', false);

    try {
      const result = await ApiClient.addAnnotation(page, newMarker);
      await syncFromBackend();
      const idx = result.index ?? (AppState.getPageAnnotations(page).length - 1);
      selectMarker(page, idx);
      Annotations.refresh();
      refreshList();
      StatusBar.setMessage(`已添加「${preset.label}」批注`);
    } catch (e) {
      StatusBar.setMessage(`添加失败: ${e.message}`);
    }

    document.getElementById('mode-hint').textContent = '滚轮滚动 · ± 缩放 · 双击译文编辑 · 可拖动微调位置';
  }

  function deleteAnnotation() {
    const page = AppState.get('selectedMarkerPage');
    const idx = AppState.get('selectedMarkerIndex');
    if (page == null || idx == null) {
      Dialogs.showWarning('警告', '请先选择一个批注');
      return;
    }
    deleteMarkerAt(page, idx);
  }

  async function deleteMarkerAt(page, idx) {
    try {
      await ApiClient.deleteAnnotation(page, idx);
      await syncFromBackend();
      deselectMarker();
      Annotations.refresh();
      refreshList();
      StatusBar.setMessage('批注已删除');
    } catch (e) {
      StatusBar.setMessage(`删除失败: ${e.message}`);
    }
  }

  function deleteSelectedMarker() {
    const page = AppState.get('selectedMarkerPage');
    const idx = AppState.get('selectedMarkerIndex');
    if (page == null || idx == null) return;
    deleteMarkerAt(page, idx);
  }

  async function deleteAllAnnotations() {
    const page = AppState.get('currentPage');
    const items = AppState.getPageAnnotations(page);
    if (items.length === 0) {
      await Dialogs.showWarning('提示', '当前页没有批注');
      return;
    }

    const ok = await Dialogs.askYesNo('删除全部批注', `确定删除第 ${page + 1} 页的全部 ${items.length} 条批注吗？`);
    if (!ok) return;

    try {
      await ApiClient.deleteAllAnnotations(page);
      await syncFromBackend();
      deselectMarker();
      Annotations.refresh();
      refreshList();
      StatusBar.setMessage(`已删除第 ${page + 1} 页全部批注`);
    } catch (e) {
      StatusBar.setMessage(`删除失败: ${e.message}`);
    }
  }

  function applyStyleLive() {
    const page = AppState.get('selectedMarkerPage');
    const idx = AppState.get('selectedMarkerIndex');
    if (page == null || idx == null) return;

    const items = AppState.getPageAnnotations(page);
    const item = items[idx];
    if (!item) return;

    item.font_size = parseInt(document.getElementById('font-size-input').value, 10) || 12;
    item.font_family = document.getElementById('font-family-select').value;
    item.text_orientation = getOrientation();

    AppState.setPageAnnotations(page, items);
    Annotations.refresh();
    scheduleAutoSave();
  }

  function getOrientation() {
    const active = document.querySelector('#orientation-segment .segmented__btn.active');
    return active ? active.dataset.value : 'horizontal';
  }

  function getKindLabel(item) {
    if (item.style_kind && PRESETS[item.style_kind]) return PRESETS[item.style_kind].label;
    if (item.display_mode === 'inline') return '原位';
    return '标记';
  }

  function truncateText(text, max) {
    if (text.length <= max) return text;
    return text.substring(0, max - 1) + '…';
  }

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  return {
    init, refreshList, selectMarker, deselectMarker, createAnnotationAt, flushPendingSave,
    deleteSelectedMarker,
  };
})();
