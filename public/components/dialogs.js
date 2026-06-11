/**
 * 对话框系统 — 对齐 src/ui/message_dialog.py
 * ThemedDialog / PageRangeDialog / show_warning / ask_yes_no / show_info
 */
const Dialogs = (() => {

  function showMessage(title, message, kind = 'ok') {
    return new Promise((resolve) => {
      const overlay = document.getElementById('message-overlay');
      const dialog = document.getElementById('message-dialog');

      dialog.innerHTML = `
        <div class="message-content">
          <div class="message-icon">!</div>
          <div class="message-text">${escapeHtml(message)}</div>
        </div>
        <div class="dialog__footer">
          ${kind === 'yesno' ? `
            <button class="btn btn--primary" id="msg-yes">是</button>
            <button class="btn btn--secondary" id="msg-no">否</button>
          ` : `
            <button class="btn btn--primary" id="msg-ok">确定</button>
          `}
        </div>
      `;

      overlay.style.display = 'flex';

      const cleanup = (result) => {
        overlay.style.display = 'none';
        overlay.onclick = null;
        document.removeEventListener('keydown', keyHandler);
        resolve(result);
      };

      function keyHandler(e) {
        if (e.key === 'Escape') cleanup(kind === 'yesno' ? false : true);
        if (e.key === 'Enter' && kind === 'yesno') cleanup(true);
        if (e.key === 'Enter' && kind !== 'yesno') cleanup(true);
      }

      if (kind === 'yesno') {
        dialog.querySelector('#msg-yes').onclick = () => cleanup(true);
        dialog.querySelector('#msg-no').onclick = () => cleanup(false);
      } else {
        dialog.querySelector('#msg-ok').onclick = () => cleanup(true);
      }

      overlay.onclick = (e) => {
        if (e.target === overlay) cleanup(kind === 'yesno' ? false : true);
      };

      document.addEventListener('keydown', keyHandler);
    });
  }

  function showWarning(title, message) { return showMessage(title, message, 'ok'); }
  function showInfo(title, message) { return showMessage(title, message, 'ok'); }
  function askYesNo(title, message) { return showMessage(title, message, 'yesno'); }

  function askPageRange(totalPages) {
    return new Promise((resolve) => {
      const overlay = document.getElementById('page-range-overlay');
      const dialog = document.getElementById('page-range-dialog');

      dialog.innerHTML = `
        <div class="dialog__header">
          <span class="dialog__title">选择批注范围</span>
        </div>
        <div class="dialog__body">
          <p style="margin-bottom:12px;font-size:14px">当前文档共 ${totalPages} 页，请选择要生成 AI 批注的页码范围：</p>
          <div class="page-range-row">
            <span>从第</span>
            <input type="number" class="page-range-input" id="range-start" value="1" min="1" max="${totalPages}" />
            <span>页  到第</span>
            <input type="number" class="page-range-input" id="range-end" value="${totalPages}" min="1" max="${totalPages}" />
            <span>页</span>
          </div>
          <div class="page-range-hint" id="range-hint"></div>
        </div>
        <div class="dialog__footer">
          <button class="btn btn--primary" id="range-ok">下一步</button>
          <button class="btn btn--secondary" id="range-cancel">取消</button>
        </div>
      `;

      overlay.style.display = 'flex';

      const cleanup = (result) => {
        overlay.style.display = 'none';
        overlay.onclick = null;
        resolve(result);
      };

      dialog.querySelector('#range-ok').onclick = () => {
        const start = parseInt(dialog.querySelector('#range-start').value);
        const end = parseInt(dialog.querySelector('#range-end').value);
        const hint = dialog.querySelector('#range-hint');

        if (isNaN(start) || isNaN(end)) { hint.textContent = '请输入有效的页码数字'; return; }
        if (start < 1 || end < 1) { hint.textContent = '页码不能小于 1'; return; }
        if (start > totalPages || end > totalPages) { hint.textContent = `页码不能超过 ${totalPages}`; return; }
        if (start > end) { hint.textContent = '起始页不能大于结束页'; return; }

        cleanup([start, end]);
      };

      dialog.querySelector('#range-cancel').onclick = () => cleanup(null);
      overlay.onclick = (e) => { if (e.target === overlay) cleanup(null); };
    });
  }

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML.replace(/\n/g, '<br>');
  }

  return { showWarning, showInfo, askYesNo, askPageRange };
})();
