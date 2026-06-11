/**

 * 批注标记系统 — 对齐 App._show_annotations / _draw_inline_annotation / web viewer.js

 * 坐标：marker.x/y 为 PDF 点，显示时用 displayScale（= zoomLevel）换算，与预览一致

 */

const Annotations = (() => {

  const MARKER_SIZE = 22;

  const GENERATED_INLINE_FONT_PT = 10;

  const RESIZE_DIRS = ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w'];

  let inlineEditor = null;

  let resizeSession = null;



  function init() {}



  function displayScale() {

    return Preview.getDisplayScale();

  }



  function inlineFontPt(item) {

    if ((item.original_text || '').trim()) return GENERATED_INLINE_FONT_PT;

    return item.font_size || 12;

  }



  function refresh() {

    const layer = document.getElementById('annotation-layer');

    layer.innerHTML = '';



    const page = AppState.get('currentPage');

    const items = AppState.getPageAnnotations(page);

    const scale = displayScale();

    const selectedPage = AppState.get('selectedMarkerPage');

    const selectedIdx = AppState.get('selectedMarkerIndex');

    const layerW = layer.offsetWidth || 800;



    items.forEach((item, idx) => {

      if (item.display_mode === 'inline') {

        renderInline(layer, item, idx, scale, layerW, selectedPage === page && selectedIdx === idx);

      } else {

        renderMarker(layer, item, idx, scale, selectedPage === page && selectedIdx === idx);

      }

    });

  }



  function bindAnnotationDrag(el, page, idx) {
    el.addEventListener('mousedown', (e) => {
      if (AppState.isInkToolActive()) return;
      if (e.button !== 0) return;
      if (e.target.closest('.annot-popup')) return;
      if (e.target.classList.contains('annot-resize-handle')) return;
      e.stopPropagation();
      Preview.beginAnnotationDrag(e, page, idx);
    });
  }

  function moveElement(page, index, x, y) {
    const layer = document.getElementById('annotation-layer');
    if (!layer || page !== AppState.get('currentPage')) return;
    const el = layer.querySelector(`[data-index="${index}"]`);
    if (!el) return;
    const scale = displayScale();
    el.style.left = `${x * scale}px`;
    el.style.top = `${y * scale}px`;
  }

  function renderMarker(layer, item, idx, scale, isSelected) {

    const marker = document.createElement('div');

    marker.className = `annot-marker${isSelected ? ' active' : ''}`;

    marker.style.left = `${item.x * scale}px`;

    marker.style.top = `${item.y * scale}px`;

    marker.style.borderColor = item.color || '#7C3AED';

    marker.textContent = idx + 1;

    marker.dataset.index = idx;

    bindAnnotationDrag(marker, AppState.get('currentPage'), idx);

    const popup = document.createElement('div');

    popup.className = 'annot-popup';

    popup.style.borderColor = item.color || '#7C3AED';

    popup.innerHTML = `

      <div class="annot-popup__header">

        <span class="annot-popup__title" style="color:${item.color || '#7C3AED'}">批注 ${idx + 1}</span>

        <button class="annot-popup__close">✕</button>

      </div>

      <div class="annot-popup__body">${escapeHtml(item.text || '')}</div>

    `;



    popup.querySelector('.annot-popup__close').addEventListener('click', (e) => {

      e.stopPropagation();

      marker.classList.remove('active');

      Sidebar.deselectMarker();

    });



    marker.addEventListener('click', (e) => {

      e.stopPropagation();

      if (AppState.isInkToolActive()) return;

      if (Preview.wasDragging()) return;

      closeAllPopups();

      marker.classList.toggle('active');

      if (marker.classList.contains('active')) {

        const page = AppState.get('currentPage');

        Sidebar.selectMarker(page, idx);

        layoutPopup(marker, popup, item, scale);

      } else {

        Sidebar.deselectMarker();

      }

    });



    marker.appendChild(popup);



    if (isSelected) {

      setTimeout(() => layoutPopup(marker, popup, item, scale), 0);

    }



    layer.appendChild(marker);

  }



  function renderInline(layer, item, idx, scale, layerW, isSelected) {

    const el = document.createElement('div');

    el.className = `annot-inline${isSelected ? ' selected' : ''}`;

    el.style.color = item.color || '#7C2D12';

    el.style.fontSize = `${inlineFontPt(item) * scale}px`;

    el.style.fontFamily = item.font_family || 'inherit';

    el.style.fontWeight = '600';

    el.style.left = `${item.x * scale}px`;

    el.style.top = `${item.y * scale}px`;

    el.textContent = item.text || '';

    el.dataset.index = idx;

    if (item.box_width && item.box_width > 0) {
      el.style.width = `${item.box_width * scale}px`;
      el.style.maxWidth = `${item.box_width * scale}px`;
    } else {
      const placement = item.placement || 'right';
      if (placement === 'right') {
        el.style.maxWidth = `${Math.max(120, layerW - item.x * scale)}px`;
      }
    }

    if (item.box_height && item.box_height > 0) {
      el.style.minHeight = `${item.box_height * scale}px`;
    }

    const placement = item.placement || 'right';

    if (placement === 'above') {
      el.style.transform = 'translate(-2px, -100%)';
      el.style.transformOrigin = 'left bottom';
    } else if (placement === 'right') {
      el.style.transformOrigin = 'left center';
    } else {
      el.style.transformOrigin = 'left top';
    }

    if (item.text_orientation === 'vertical') {
      el.classList.add('vertical');
      el.style.writingMode = 'vertical-rl';
      el.style.textOrientation = 'upright';
    }

    bindAnnotationDrag(el, AppState.get('currentPage'), idx);

    el.addEventListener('click', (e) => {
      if (e.target.classList.contains('annot-resize-handle')) return;
      e.stopPropagation();
      if (AppState.isInkToolActive()) return;
      if (Preview.wasDragging()) return;
      Sidebar.selectMarker(AppState.get('currentPage'), idx);
    });

    el.addEventListener('dblclick', (e) => {
      e.stopPropagation();
      if (AppState.isInkToolActive()) return;
      beginInlineEdit({ ...item, page: AppState.get('currentPage'), index: idx });
    });

    if (isSelected) {
      addResizeHandles(el, item, idx, scale);
    }

    layer.appendChild(el);
  }

  function addResizeHandles(el, item, idx, scale) {
    RESIZE_DIRS.forEach((dir) => {
      const h = document.createElement('div');
      h.className = `annot-resize-handle annot-resize-handle--${dir}`;
      h.addEventListener('mousedown', (e) => {
        e.stopPropagation();
        e.preventDefault();
        beginResize(e, item, idx, dir, scale);
      });
      el.appendChild(h);
    });
  }

  function beginResize(e, item, idx, dir, scale) {
    const page = AppState.get('currentPage');
    const layer = document.getElementById('annotation-layer');
    const el = layer.querySelector(`[data-index="${idx}"]`);
    if (!el) return;

    const startX = e.clientX;
    const startY = e.clientY;
    const startW = el.offsetWidth;
    const startH = el.offsetHeight;
    const startLeft = item.x * scale;
    const startTop = item.y * scale;

    resizeSession = { page, idx, dir, startX, startY, startW, startH, startLeft, startTop, scale, item: { ...item } };

    document.addEventListener('mousemove', onResizeDrag);
    document.addEventListener('mouseup', onResizeEnd);
  }

  function onResizeDrag(e) {
    if (!resizeSession) return;
    const { dir, startX, startY, startW, startH, startLeft, startTop, scale, idx } = resizeSession;
    const dx = e.clientX - startX;
    const dy = e.clientY - startY;
    const MIN_W = 30;
    const MIN_H = 16;

    let newW = startW;
    let newH = startH;
    let newLeft = startLeft;
    let newTop = startTop;

    if (dir.includes('e')) newW = Math.max(MIN_W, startW + dx);
    if (dir.includes('w')) { newW = Math.max(MIN_W, startW - dx); newLeft = startLeft + dx; if (newW <= MIN_W) newLeft = startLeft + (startW - MIN_W); }
    if (dir.includes('s')) newH = Math.max(MIN_H, startH + dy);
    if (dir.includes('n')) { newH = Math.max(MIN_H, startH - dy); newTop = startTop + dy; if (newH <= MIN_H) newTop = startTop + (startH - MIN_H); }

    const layer = document.getElementById('annotation-layer');
    const el = layer?.querySelector(`[data-index="${idx}"]`);
    if (!el) return;

    el.style.width = `${newW}px`;
    el.style.maxWidth = `${newW}px`;
    el.style.minHeight = `${newH}px`;
    el.style.left = `${newLeft}px`;
    el.style.top = `${newTop}px`;

    resizeSession._newW = newW;
    resizeSession._newH = newH;
    resizeSession._newLeft = newLeft;
    resizeSession._newTop = newTop;
  }

  async function onResizeEnd() {
    document.removeEventListener('mousemove', onResizeDrag);
    document.removeEventListener('mouseup', onResizeEnd);
    if (!resizeSession) return;

    const { page, idx, scale, _newW, _newH, _newLeft, _newTop } = resizeSession;
    resizeSession = null;

    if (_newW == null) return;

    const pdfW = Math.round(_newW / scale);
    const pdfH = Math.round(_newH / scale);
    const pdfX = Math.round(_newLeft / scale);
    const pdfY = Math.round(_newTop / scale);

    const items = AppState.getPageAnnotations(page);
    const item = items[idx];
    if (!item) return;

    item.box_width = pdfW;
    item.box_height = pdfH;
    item.x = pdfX;
    item.y = pdfY;
    AppState.setPageAnnotations(page, items);

    try {
      await ApiClient.updateAnnotation(page, idx, {
        box_width: pdfW,
        box_height: pdfH,
        x: pdfX,
        y: pdfY,
      });
      StatusBar.setMessage('文本框大小已更新');
    } catch (err) {
      StatusBar.setMessage(`保存大小失败: ${err.message}`);
    }

    refresh();
    Sidebar.refreshList();
    window.electronAPI?.refreshPreview?.();
  }



  function layoutPopup(marker, popup, item, scale) {

    const layerEl = document.getElementById('annotation-layer');

    const layerW = layerEl.offsetWidth || 800;

    const mx = item.x * scale;



    popup.style.display = 'block';

    const pw = popup.offsetWidth || 280;



    let px = 30;

    if (mx + MARKER_SIZE + 30 + pw > layerW) {

      px = -(pw + 8);

    }

    popup.style.left = `${px}px`;

    popup.style.display = '';

  }



  function findMarkerAt(displayX, displayY) {

    const page = AppState.get('currentPage');

    const items = AppState.getPageAnnotations(page);

    const layer = document.getElementById('annotation-layer');

    if (!layer) return null;

    const layerRect = layer.getBoundingClientRect();

    const pad = 6;



    for (let i = items.length - 1; i >= 0; i--) {

      const el = layer.querySelector(`[data-index="${i}"]`);

      if (el) {

        const r = el.getBoundingClientRect();

        const left = r.left - layerRect.left - pad;

        const top = r.top - layerRect.top - pad;

        const right = r.right - layerRect.left + pad;

        const bottom = r.bottom - layerRect.top + pad;

        if (displayX >= left && displayX <= right && displayY >= top && displayY <= bottom) {

          return { ...items[i], page, index: i };

        }

        continue;

      }



      const item = items[i];

      const scale = displayScale();

      const mx = item.x * scale;

      const my = item.y * scale;



      if (item.display_mode === 'inline') {

        const fontPx = inlineFontPt(item) * scale;

        const approxW = Math.min((item.text || '').length * fontPx * 0.65, layer.offsetWidth - mx);

        const approxH = item.text_orientation === 'vertical'

          ? (item.text || '').length * fontPx * 1.1

          : fontPx * 1.5;

        if (

          displayX >= mx - pad && displayX <= mx + approxW + pad

          && displayY >= my - approxH - pad && displayY <= my + pad

        ) {

          return { ...item, page, index: i };

        }

      } else if (

        displayX >= mx && displayX <= mx + MARKER_SIZE

        && displayY >= my && displayY <= my + MARKER_SIZE

      ) {

        return { ...item, page, index: i };

      }

    }

    return null;

  }



  function closeAllPopups() {

    document.querySelectorAll('.annot-marker.active').forEach((m) => m.classList.remove('active'));

  }



  function togglePopup(marker) {

    const el = document.querySelector(`.annot-marker[data-index="${marker.index}"]`);

    if (el) {

      closeAllPopups();

      el.classList.add('active');

      Sidebar.selectMarker(marker.page, marker.index);

    }

  }



  function beginInlineEdit(marker) {

    destroyInlineEditor();



    const layer = document.getElementById('annotation-layer');

    const scale = displayScale();



    inlineEditor = document.createElement('div');

    inlineEditor.className = 'inline-editor';

    inlineEditor.style.left = `${marker.x * scale}px`;

    inlineEditor.style.top = `${marker.y * scale}px`;

    inlineEditor.style.borderColor = marker.color || '#7C3AED';

    inlineEditor.style.minWidth = '160px';

    inlineEditor.style.maxWidth = '420px';



    const toolbar = document.createElement('div');

    toolbar.className = 'inline-editor__toolbar';



    const textarea = document.createElement('textarea');

    textarea.className = 'inline-editor__textarea';

    textarea.value = marker.text || '';

    textarea.style.color = marker.color || '#7C3AED';

    textarea.style.fontSize = `${inlineFontPt(marker) * scale}px`;

    textarea.style.minHeight = '40px';



    const doneBtn = document.createElement('button');

    doneBtn.className = 'btn btn--primary btn--xs';

    doneBtn.textContent = '完成';

    doneBtn.addEventListener('click', () => commitInlineEdit(marker, textarea.value));

    toolbar.appendChild(doneBtn);



    inlineEditor.appendChild(toolbar);

    inlineEditor.appendChild(textarea);

    layer.appendChild(inlineEditor);



    textarea.focus();

    textarea.addEventListener('keydown', (e) => {

      if (e.key === 'Escape') { destroyInlineEditor(); refresh(); }

      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); commitInlineEdit(marker, textarea.value); }

    });

  }



  async function commitInlineEdit(marker, text) {

    if (text.trim()) {

      const items = AppState.getPageAnnotations(marker.page);

      if (items[marker.index]) {

        items[marker.index].text = text.trim();

        AppState.setPageAnnotations(marker.page, items);

        try {

          await ApiClient.updateAnnotation(marker.page, marker.index, { text: text.trim() });

        } catch (e) {

          console.warn('updateAnnotation failed', e);

        }

      }

    }

    destroyInlineEditor();

    refresh();

    Sidebar.refreshList();

    StatusBar.setMessage('译文已更新');

  }



  function destroyInlineEditor() {

    if (inlineEditor && inlineEditor.parentNode) {

      inlineEditor.parentNode.removeChild(inlineEditor);

    }

    inlineEditor = null;

  }



  function escapeHtml(text) {

    const div = document.createElement('div');

    div.textContent = text;

    return div.innerHTML.replace(/\n/g, '<br>');

  }



  return { init, refresh, findMarkerAt, closeAllPopups, togglePopup, beginInlineEdit, moveElement };

})();


