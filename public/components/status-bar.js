/**
 * 状态栏 — 对齐 src/ui/status_bar.py StatusBar
 */
const StatusBar = (() => {
  function init() {}

  function setMessage(message) {
    document.getElementById('status-message').textContent = message;
  }

  function setProgress(current, total, status) {
    const fill = document.getElementById('progress-fill');
    const label = document.getElementById('progress-label');

    if (total > 0) {
      const pct = Math.min(Math.max(current / total, 0), 1) * 100;
      fill.style.width = `${pct}%`;
      label.textContent = `${current}/${total}`;
    } else {
      fill.style.width = '0%';
      label.textContent = '';
    }

    if (status) {
      document.getElementById('status-message').textContent = status;
    }
  }

  return { init, setMessage, setProgress };
})();
