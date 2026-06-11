/**
 * 文件列表面板 — 对齐 App._create_file_list / update_file_list / _on_file_select / _remove_file
 */
const FilePanel = (() => {
  function init() {
    refresh();
  }

  function refresh() {
    const container = document.getElementById('file-list');
    const hint = document.getElementById('file-hint');
    const files = AppState.get('selectedFiles') || [];
    const currentIndex = AppState.get('currentFileIndex');

    container.innerHTML = '';

    if (files.length === 0) {
      hint.textContent = '点击顶部「导入」添加 PDF / PPT';
      hint.style.display = '';
      return;
    }

    hint.style.display = 'none';

    files.forEach((filePath, idx) => {
      const fileName = filePath.split(/[\\/]/).pop();
      const lower = fileName.toLowerCase();
      let icon = '📁';
      if (lower.endsWith('.pdf')) icon = '📄';
      else if (lower.endsWith('.ppt') || lower.endsWith('.pptx')) icon = '📊';

      const isCurrent = idx === currentIndex;
      const displayName = truncateFilename(fileName, 32);

      const row = document.createElement('div');
      row.className = `file-item${isCurrent ? ' active' : ''}`;
      row.title = fileName;
      row.innerHTML = `
        <span class="file-item__name">${icon} ${escapeHtml(displayName)}</span>
        <button class="file-item__remove" title="移除">删</button>
      `;

      row.addEventListener('click', (e) => {
        if (e.target.closest('.file-item__remove')) return;
        selectFile(idx);
      });

      row.querySelector('.file-item__remove').addEventListener('click', (e) => {
        e.stopPropagation();
        removeFile(idx);
      });

      container.appendChild(row);
    });
  }

  async function selectFile(index) {
    try {
      await ApiClient.selectFile(index);
      AppState.set('currentFileIndex', index);
      const state = await ApiClient.getState();
      AppState.state.annotationsByPage = state.annotations || {};
      await Preview.loadFromState(state);
      Annotations.refresh();
      Sidebar.refreshList();
      refresh();

      const files = AppState.get('selectedFiles');
      const name = files[index]?.split(/[\\/]/).pop() || '';
      StatusBar.setMessage(`已选择: ${name}`);
      window.electronAPI?.refreshPreview?.();
    } catch (e) {
      StatusBar.setMessage(`选择文件失败: ${e.message}`);
    }
  }

  async function removeFile(index) {
    const files = AppState.get('selectedFiles');
    const name = files[index]?.split(/[\\/]/).pop() || '';

    const confirmed = await Dialogs.askYesNo('确认移除', `确定从列表中移除「${name}」吗？\n该文件的批注也会一并删除（不会删除磁盘上的原文件）。`);
    if (!confirmed) return;

    try {
      await ApiClient.removeFile(index);
      const state = await ApiClient.getState();
      AppState.set('selectedFiles', state.files || []);
      AppState.set('currentFileIndex', state.current_file_index ?? -1);
      FilePanel.refresh();

      if ((state.files || []).length > 0) {
        await Preview.loadFromState(state);
      } else {
        Preview.showPlaceholder();
      }

      StatusBar.setMessage(`已移除: ${name}`);
    } catch (e) {
      StatusBar.setMessage(`移除失败: ${e.message}`);
    }
  }

  function truncateFilename(name, maxChars) {
    if (name.length <= maxChars) return name;
    return name.substring(0, maxChars - 1) + '…';
  }

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  return { init, refresh };
})();
