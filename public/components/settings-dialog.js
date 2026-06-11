/**
 * 设置对话框 — 对齐 src/ui/settings_dialog.py SettingsDialog
 * LLM 设置 / 批注设置 / 应用设置
 */
const SettingsDialog = (() => {

  function show() {
    const overlay = document.getElementById('settings-overlay');
    const dialog = document.getElementById('settings-dialog');
    const settings = JSON.parse(JSON.stringify(AppState.state.settings));

    dialog.innerHTML = buildHTML(settings);
    overlay.style.display = 'flex';

    initTabs(dialog);
    initProviderToggle(dialog, settings);

    dialog.querySelector('#settings-save').addEventListener('click', () => save(dialog, overlay));
    dialog.querySelector('#settings-cancel').addEventListener('click', () => { overlay.style.display = 'none'; });
    overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.style.display = 'none'; });
  }

  function buildHTML(s) {
    return `
      <div class="dialog__header">
        <span class="dialog__title">系统 API 设置</span>
        <button class="dialog__close" id="settings-close-x">✕</button>
      </div>
      <div class="dialog__body">
        <div class="tabs">
          <button class="tab-btn active" data-tab="llm">LLM 设置</button>
          <button class="tab-btn" data-tab="annotation">批注设置</button>
          <button class="tab-btn" data-tab="app">应用设置</button>
        </div>

        <!-- LLM 设置 -->
        <div class="tab-content active" id="tab-llm">
          <div class="form-group">
            <label class="form-label">LLM 提供商:</label>
            <div class="segmented" id="provider-segment">
              <button class="segmented__btn${s.llm.provider === 'openai' ? ' active' : ''}" data-value="openai">OpenAI</button>
              <button class="segmented__btn${s.llm.provider === 'ollama' ? ' active' : ''}" data-value="ollama">Ollama</button>
              <button class="segmented__btn${s.llm.provider === 'deepseek' ? ' active' : ''}" data-value="deepseek">DeepSeek</button>
              <button class="segmented__btn${s.llm.provider === 'xiaomi' ? ' active' : ''}" data-value="xiaomi">小米 MiMo</button>
              <button class="segmented__btn${s.llm.provider === 'agnes' ? ' active' : ''}" data-value="agnes">Agnes</button>
            </div>
          </div>

          <div class="form-card provider-card" id="card-openai" ${s.llm.provider !== 'openai' ? 'style="display:none"' : ''}>
            <div class="form-group"><label class="form-label">API Key:</label><input class="form-input" type="password" id="s-openai-key" value="${esc(s.llm.openai.api_key)}" /></div>
            <div class="form-group"><label class="form-label">模型:</label><input class="form-input" id="s-openai-model" value="${esc(s.llm.openai.model)}" /></div>
          </div>

          <div class="form-card provider-card" id="card-ollama" ${s.llm.provider !== 'ollama' ? 'style="display:none"' : ''}>
            <div class="form-group"><label class="form-label">Base URL:</label><input class="form-input" id="s-ollama-url" value="${esc(s.llm.ollama.base_url)}" /></div>
            <div class="form-group"><label class="form-label">模型:</label><input class="form-input" id="s-ollama-model" value="${esc(s.llm.ollama.model)}" /></div>
          </div>

          <div class="form-card provider-card" id="card-deepseek" ${s.llm.provider !== 'deepseek' ? 'style="display:none"' : ''}>
            <div class="form-group"><label class="form-label">API Key:</label><input class="form-input" type="password" id="s-ds-key" value="${esc(s.llm.deepseek.api_key)}" /></div>
            <div class="form-group"><label class="form-label">模型:</label><input class="form-input" id="s-ds-model" value="${esc(s.llm.deepseek.model)}" /></div>
            <div class="form-group"><label class="form-label">Base URL:</label><input class="form-input" id="s-ds-url" value="${esc(s.llm.deepseek.base_url)}" /></div>
          </div>

          <div class="form-card provider-card" id="card-xiaomi" ${s.llm.provider !== 'xiaomi' ? 'style="display:none"' : ''}>
            <div class="form-group">
              <label class="form-label">计费方式:</label>
              <div class="segmented" id="xiaomi-mode-segment">
                <button class="segmented__btn${(s.llm.xiaomi.api_mode || 'token_plan') === 'token_plan' ? ' active' : ''}" data-value="token_plan">Token Plan 订阅</button>
                <button class="segmented__btn${s.llm.xiaomi.api_mode === 'payg' ? ' active' : ''}" data-value="payg">按量付费 API</button>
              </div>
            </div>
            <p class="form-hint">Token Plan：在「订阅管理」复制 tp- 开头的 Key 与 Base URL</p>
            <div class="form-group"><label class="form-label">API Key:</label><input class="form-input" type="password" id="s-xm-key" value="${esc(s.llm.xiaomi.api_key)}" /></div>
            <div class="form-group"><label class="form-label">模型:</label><input class="form-input" id="s-xm-model" value="${esc(s.llm.xiaomi.model)}" /></div>
            <div class="form-group"><label class="form-label">Base URL:</label><input class="form-input" id="s-xm-url" value="${esc(s.llm.xiaomi.base_url)}" /></div>
            <p class="form-hint">请填 mimo-v2.5（全模态）。原位翻译会识整页图。</p>
          </div>

          <div class="form-card provider-card" id="card-agnes" ${s.llm.provider !== 'agnes' ? 'style="display:none"' : ''}>
            <p class="form-hint">在 Agnes 控制台获取 API Key：https://www.agnes-ai.com</p>
            <div class="form-group"><label class="form-label">API Key:</label><input class="form-input" type="password" id="s-ag-key" value="${esc(s.llm.agnes.api_key)}" /></div>
            <div class="form-group"><label class="form-label">模型:</label><input class="form-input" id="s-ag-model" value="${esc(s.llm.agnes.model)}" /></div>
            <div class="form-group"><label class="form-label">Base URL:</label><input class="form-input" id="s-ag-url" value="${esc(s.llm.agnes.base_url)}" /></div>
            <p class="form-hint">模型名请使用 agnes-2.0-flash；支持全模态识图。</p>
          </div>
        </div>

        <!-- 批注设置 -->
        <div class="tab-content" id="tab-annotation">
          <div class="form-group">
            <label class="form-label">批注模式:</label>
            <div class="segmented" id="mode-segment">
              <button class="segmented__btn${s.annotation.mode === 'overlay' ? ' active' : ''}" data-value="overlay">overlay</button>
              <button class="segmented__btn${s.annotation.mode === 'sidebar' ? ' active' : ''}" data-value="sidebar">sidebar</button>
            </div>
            <p class="form-hint">覆盖：在原文旁直接显示中文翻译；侧边栏：数字标记 + 长文批注</p>
          </div>
          <div class="form-group">
            <label class="form-label">详细程度:</label>
            <div class="segmented" id="detail-segment">
              <button class="segmented__btn${s.annotation.detail_level === 'summary' ? ' active' : ''}" data-value="summary">summary</button>
              <button class="segmented__btn${s.annotation.detail_level === 'detailed' ? ' active' : ''}" data-value="detailed">detailed</button>
              <button class="segmented__btn${s.annotation.detail_level === 'custom' ? ' active' : ''}" data-value="custom">custom</button>
            </div>
          </div>
          <div class="form-card">
            <div class="form-group"><label class="form-label">字体大小:</label><input class="form-input" id="s-ann-fontsize" value="${s.annotation.style.font_size}" /></div>
          </div>
        </div>

        <!-- 应用设置 -->
        <div class="tab-content" id="tab-app">
          <div class="form-group">
            <label class="form-label">主题:</label>
            <div class="segmented" id="theme-segment">
              <button class="segmented__btn${s.app.theme === 'light' ? ' active' : ''}" data-value="light">light</button>
              <button class="segmented__btn${s.app.theme === 'dark' ? ' active' : ''}" data-value="dark">dark</button>
              <button class="segmented__btn${s.app.theme === 'system' ? ' active' : ''}" data-value="system">system</button>
            </div>
          </div>
          <div class="form-group">
            <label class="form-label">语言:</label>
            <div class="segmented" id="language-segment">
              <button class="segmented__btn${s.app.language === 'zh-CN' ? ' active' : ''}" data-value="zh-CN">zh-CN</button>
              <button class="segmented__btn${s.app.language === 'en-US' ? ' active' : ''}" data-value="en-US">en-US</button>
            </div>
          </div>
        </div>
      </div>
      <div class="dialog__footer">
        <button class="btn btn--primary" id="settings-save">保存</button>
        <button class="btn btn--secondary" id="settings-cancel">取消</button>
      </div>
    `;
  }

  function initTabs(dialog) {
    dialog.querySelectorAll('.tab-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        dialog.querySelectorAll('.tab-btn').forEach((b) => b.classList.remove('active'));
        dialog.querySelectorAll('.tab-content').forEach((c) => c.classList.remove('active'));
        btn.classList.add('active');
        dialog.querySelector(`#tab-${btn.dataset.tab}`).classList.add('active');
      });
    });

    dialog.querySelector('#settings-close-x').addEventListener('click', () => {
      document.getElementById('settings-overlay').style.display = 'none';
    });

    initSegmented(dialog);
  }

  function initSegmented(dialog) {
    dialog.querySelectorAll('.segmented').forEach((seg) => {
      seg.querySelectorAll('.segmented__btn').forEach((btn) => {
        btn.addEventListener('click', () => {
          seg.querySelectorAll('.segmented__btn').forEach((b) => b.classList.remove('active'));
          btn.classList.add('active');
        });
      });
    });
  }

  function initProviderToggle(dialog, settings) {
    dialog.querySelectorAll('#provider-segment .segmented__btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        dialog.querySelectorAll('.provider-card').forEach((c) => c.style.display = 'none');
        const card = dialog.querySelector(`#card-${btn.dataset.value}`);
        if (card) card.style.display = '';
      });
    });
  }

  function getSegmentedValue(dialog, id) {
    const active = dialog.querySelector(`#${id} .segmented__btn.active`);
    return active ? active.dataset.value : '';
  }

  function save(dialog, overlay) {
    const s = AppState.state.settings;

    s.llm.provider = getSegmentedValue(dialog, 'provider-segment');
    s.llm.openai.api_key = dialog.querySelector('#s-openai-key').value;
    s.llm.openai.model = dialog.querySelector('#s-openai-model').value;
    s.llm.ollama.base_url = dialog.querySelector('#s-ollama-url').value;
    s.llm.ollama.model = dialog.querySelector('#s-ollama-model').value;
    s.llm.deepseek.api_key = dialog.querySelector('#s-ds-key').value;
    s.llm.deepseek.model = dialog.querySelector('#s-ds-model').value;
    s.llm.deepseek.base_url = dialog.querySelector('#s-ds-url').value;
    s.llm.xiaomi.api_mode = getSegmentedValue(dialog, 'xiaomi-mode-segment');
    s.llm.xiaomi.api_key = dialog.querySelector('#s-xm-key').value;
    s.llm.xiaomi.model = dialog.querySelector('#s-xm-model').value;
    s.llm.xiaomi.base_url = dialog.querySelector('#s-xm-url').value;
    s.llm.agnes.api_key = dialog.querySelector('#s-ag-key').value;
    s.llm.agnes.model = dialog.querySelector('#s-ag-model').value;
    s.llm.agnes.base_url = dialog.querySelector('#s-ag-url').value;

    s.annotation.mode = getSegmentedValue(dialog, 'mode-segment');
    s.annotation.detail_level = getSegmentedValue(dialog, 'detail-segment');
    s.annotation.style.font_size = parseInt(dialog.querySelector('#s-ann-fontsize').value) || 12;

    s.app.theme = getSegmentedValue(dialog, 'theme-segment');
    s.app.language = getSegmentedValue(dialog, 'language-segment');

    ApiClient.saveSettings(s).then(() => {
      StatusBar.setMessage('设置已保存并持久化到文件');
      Dialogs.showInfo('成功', '设置已保存，API Key已持久化');
    }).catch((e) => {
      StatusBar.setMessage(`设置保存失败: ${e.message}`);
    });

    overlay.style.display = 'none';
  }

  function esc(s) {
    return (s || '').replace(/"/g, '&quot;').replace(/</g, '&lt;');
  }

  return { show };
})();
