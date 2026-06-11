/**
 * 绘图工具栏 — 对齐 App._create_ink_toolbar / _set_canvas_tool
 * 笔 / 荧光笔 / 橡皮 / 颜色选择
 */
const InkToolbar = (() => {
  const INK_COLORS = ['#FF0000', '#0000FF', '#009900', '#FF9900', '#9900CC', '#000000'];
  let currentTool = null;

  function init() {
    renderColorSwatches();
    bindButtons();
  }

  function renderColorSwatches() {
    const container = document.getElementById('ink-colors');
    if (!container) return;
    container.innerHTML = '';

    INK_COLORS.forEach((color) => {
      const btn = document.createElement('button');
      btn.className = 'ink-color-swatch';
      btn.style.background = color;
      btn.dataset.color = color;
      btn.addEventListener('click', () => selectColor(color));
      container.appendChild(btn);
    });

    selectColor(INK_COLORS[0]);
  }

  function selectColor(color) {
    AppState.set('inkColor', color);
    document.querySelectorAll('.ink-color-swatch').forEach((s) =>
      s.classList.toggle('active', s.dataset.color === color)
    );
    InkEngine.setColor(color);
  }

  function bindButtons() {
    document.getElementById('ink-pen')?.addEventListener('click', () => setTool('pen'));
    document.getElementById('ink-highlighter')?.addEventListener('click', () => setTool('highlighter'));
    document.getElementById('ink-eraser')?.addEventListener('click', () => setTool('eraser'));
    document.getElementById('ink-close')?.addEventListener('click', () => closeTool());
  }

  function setTool(tool) {
    currentTool = tool;
    document.querySelectorAll('.ink-tool-btn').forEach((b) => b.classList.remove('active'));
    const btn = document.getElementById(`ink-${tool}`);
    if (btn) btn.classList.add('active');

    InkEngine.setTool(tool);

    const wrap = document.getElementById('canvas-wrap');
    wrap.classList.remove('mode-pen', 'mode-highlighter', 'mode-eraser');
    wrap.classList.add(`mode-${tool}`);

    AppState.set('canvasTool', tool);
    StatusBar.setMessage(`绘图工具: ${tool === 'pen' ? '笔' : tool === 'highlighter' ? '荧光笔' : '橡皮擦'}`);
  }

  function closeTool() {
    currentTool = null;
    document.querySelectorAll('.ink-tool-btn').forEach((b) => b.classList.remove('active'));
    const wrap = document.getElementById('canvas-wrap');
    wrap.classList.remove('mode-pen', 'mode-highlighter', 'mode-eraser');
    AppState.set('canvasTool', null);
    InkEngine.setTool(null);
    StatusBar.setMessage('已退出绘图模式');
  }

  function toggle() {
    const bar = document.getElementById('ink-toolbar');
    if (!bar) return;
    const isVisible = bar.style.display !== 'none';
    if (isVisible) {
      bar.style.display = 'none';
      closeTool();
    } else {
      bar.style.display = 'flex';
      setTool('pen');
    }
  }

  return { init, toggle, setTool, closeTool };
})();
