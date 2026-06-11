/**
 * 顶部工具栏 — 对齐 src/ui/toolbar.py
 * 导入 / 打开工程 / 保存工程 / 批注 / 全部批注 / 放映 / 设置
 */
const Toolbar = (() => {
  function init() {
    document.getElementById('btn-import').addEventListener('click', onImport);
    document.getElementById('btn-open-project').addEventListener('click', onOpenProject);
    document.getElementById('btn-save-project').addEventListener('click', onSaveProject);
    document.getElementById('btn-annotate').addEventListener('click', onAnnotate);
    document.getElementById('btn-annotate-all').addEventListener('click', onAnnotateAll);
    document.getElementById('btn-export').addEventListener('click', onExport);
    document.getElementById('btn-preview').addEventListener('click', onPreview);
    document.getElementById('btn-settings').addEventListener('click', onSettings);

    if (window.electronAPI) {
      window.electronAPI.onMenuImport(() => onImport());
      window.electronAPI.onMenuOpenProject(() => onOpenProject());
      window.electronAPI.onMenuSaveProject(() => onSaveProject());
      window.electronAPI.onMenuExport(() => onExport());
      window.electronAPI.onMenuSettings(() => onSettings());
      window.electronAPI.onMenuUndo(() => AppState.emit('undo'));
      window.electronAPI.onMenuZoomIn(() => Preview.zoomIn());
      window.electronAPI.onMenuZoomOut(() => Preview.zoomOut());
      window.electronAPI.onMenuZoomReset(() => Preview.zoomReset());
    }
  }

  async function onImport() {
    let files;
    if (window.electronAPI) {
      files = await window.electronAPI.openFiles();
    } else {
      const input = document.getElementById('file-input');
      files = await new Promise((resolve) => {
        const finish = (result) => {
          input.removeEventListener('change', onChange);
          input.removeEventListener('cancel', onCancel);
          resolve(result);
        };
        const onChange = () => finish(input.files);
        const onCancel = () => finish(null);
        input.addEventListener('change', onChange);
        input.addEventListener('cancel', onCancel);
        input.value = '';
        input.click();
      });
    }
    if (!files || files.length === 0) return;

    try {
      StatusBar.setMessage('正在上传并解析文件…');
      await ApiClient.importFiles(files);
      const state = await ApiClient.getState();
      AppState.set('selectedFiles', state.files || []);
      AppState.set('currentFileIndex', state.current_file_index ?? 0);
      FilePanel.refresh();
      await Preview.loadFromState(state);
      StatusBar.setMessage(`导入成功：${files.length} 个文件`);
    } catch (e) {
      const msg = String(e.message || e);
      const hint = msg.includes('Failed to fetch') || msg.includes('NetworkError')
        ? '（请确认已通过 http://127.0.0.1:3000 访问，且开发服务器正在运行）'
        : '';
      StatusBar.setMessage(`导入失败：${msg}${hint}`);
      console.error('[import]', e);
    }
  }

  async function onOpenProject() {
    if (window.electronAPI) {
      const path = await window.electronAPI.openProject();
      if (!path) return;
      try {
        await ApiClient.openProject(path);
        const state = await ApiClient.getState();
        AppState.set('selectedFiles', state.files || []);
        FilePanel.refresh();
        await Preview.loadFromState(state);
        StatusBar.setMessage(`已打开工程: ${path.split(/[\\/]/).pop()}`);
      } catch (e) {
        await Dialogs.showWarning('错误', `打开工程失败: ${e.message}`);
      }
      return;
    }

    const input = document.getElementById('project-input');
    const file = await new Promise((resolve) => {
      input.onchange = () => resolve(input.files?.[0] || null);
      input.click();
    });
    input.value = '';
    if (!file) return;

    try {
      await WebSession.importProjectBlob(file);
      const state = await ApiClient.getState();
      AppState.set('selectedFiles', state.files || []);
      AppState.set('currentFileIndex', state.current_file_index ?? 0);
      FilePanel.refresh();
      if (state.pdf_available) {
        await Preview.loadFromState(state);
      } else {
        Preview.showPlaceholder();
      }
      StatusBar.setMessage(`已打开工程: ${file.name}`);
    } catch (e) {
      await Dialogs.showWarning('错误', `打开工程失败: ${e.message}`);
    }
  }

  async function onSaveProject() {
    if (AppState.get('selectedFiles').length === 0) {
      StatusBar.setMessage('没有可保存的内容，请先导入 PDF');
      return;
    }

    if (window.electronAPI) {
      const path = await window.electronAPI.saveProject({ defaultPath: '我的批注工程.topdf' });
      if (!path) return;
      try {
        await ApiClient.saveProject(path);
        StatusBar.setMessage(`工程已保存: ${path.split(/[\\/]/).pop()}`);
      } catch (e) {
        await Dialogs.showWarning('错误', `保存工程失败: ${e.message}`);
      }
      return;
    }

    try {
      const blob = WebSession.exportProjectBlob();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = '我的批注工程.topdf';
      a.click();
      URL.revokeObjectURL(a.href);
      StatusBar.setMessage('工程已下载到本地');
    } catch (e) {
      await Dialogs.showWarning('错误', `保存工程失败: ${e.message}`);
    }
  }

  async function onAnnotate() {
    if (AppState.get('annotating')) return;
    if (!validateAnnotateReady()) return;

    AppState.set('annotating', true);
    setAnnotateButtonsState(false);
    StatusBar.setMessage(`正在将第 ${AppState.get('currentPage') + 1} 页转为图片并分析...`);

    try {
      const result = await ApiClient.annotateSingle(AppState.get('currentPage'));
      const state = await ApiClient.getState();
      AppState.state.annotationsByPage = state.annotations || {};
      Annotations.refresh();
      Sidebar.refreshList();
      StatusBar.setMessage(result.message || '批注完成');
    } catch (e) {
      StatusBar.setMessage(`批注失败: ${e.message}`);
    } finally {
      AppState.set('annotating', false);
      setAnnotateButtonsState(true);
    }
  }

  async function onAnnotateAll() {
    if (AppState.get('annotating')) return;
    if (!validateAnnotateReady()) return;

    const total = AppState.get('totalPages');
    if (total <= 0) { await Dialogs.showWarning('警告', '没有可批注的页面'); return; }

    const range = await Dialogs.askPageRange(total);
    if (!range) return;

    await new Promise((resolve) => requestAnimationFrame(() => setTimeout(resolve, 0)));

    const [startPage, endPage] = range;
    const jobTotal = endPage - startPage + 1;

    const confirmed = await Dialogs.askYesNo(
      '确认全部批注',
      `将对第 ${startPage} 页到第 ${endPage} 页（共 ${jobTotal} 页）生成 AI 批注。\n\n流程：渲染所选页 → 理解文档上下文 → 逐页批注；每完成一页会立即显示在界面上。\n\n确定要开始吗？`
    );
    if (!confirmed) return;

    AppState.set('annotating', true);
    setAnnotateButtonsState(false);
    StatusBar.setProgress(0, jobTotal, '准备中...');

    let lastSyncedPage = -1;

    try {
      if (window.electronAPI) {
        await ApiClient.annotatePages(startPage - 1, endPage - 1);
        while (true) {
          await sleep(300);
          const prog = await ApiClient.getAnnotateProgress();
          const current = prog.current || 0;
          const progTotal = prog.total || jobTotal;
          StatusBar.setProgress(current, progTotal, prog.message || '批注中...');

          if (typeof prog.last_page === 'number' && prog.last_page > lastSyncedPage) {
            lastSyncedPage = prog.last_page;
            const state = await ApiClient.getState();
            AppState.state.annotationsByPage = state.annotations || {};
            Annotations.refresh();
            Sidebar.refreshList();
            window.refreshPreview?.();
          }

          if (prog.status === 'done') {
            const state = await ApiClient.getState();
            AppState.state.annotationsByPage = state.annotations || {};
            Annotations.refresh();
            Sidebar.refreshList();
            window.refreshPreview?.();
            StatusBar.setProgress(jobTotal, jobTotal, '完成');
            StatusBar.setMessage(prog.message || `批注完成：第 ${startPage}–${endPage} 页`);
            break;
          }

          if (prog.status === 'error') {
            throw new Error(prog.error || prog.message || '批量批注失败');
          }

          if (prog.status === 'idle') {
            throw new Error('批注任务已中断，请重试');
          }
        }
      } else {
        for (let p = startPage - 1; p <= endPage - 1; p += 1) {
          const done = p - (startPage - 1) + 1;
          StatusBar.setProgress(done, jobTotal, `批注第 ${p + 1} 页（${done}/${jobTotal}）...`);
          const result = await ApiClient.annotateSingle(p);
          const state = await ApiClient.getState();
          AppState.state.annotationsByPage = state.annotations || {};
          Annotations.refresh();
          Sidebar.refreshList();
          if (p > lastSyncedPage) lastSyncedPage = p;
          if (result?.error) throw new Error(result.error);
        }
        StatusBar.setProgress(jobTotal, jobTotal, '完成');
        StatusBar.setMessage(`批注完成：第 ${startPage}–${endPage} 页`);
      }
    } catch (e) {
      StatusBar.setMessage(`批量批注失败: ${e.message}`);
    } finally {
      AppState.set('annotating', false);
      setAnnotateButtonsState(true);
    }
  }

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  async function onExport() {
    if (AppState.get('selectedFiles').length === 0) {
      await Dialogs.showWarning('警告', '没有可导出的文件，请先导入并批注文件');
      return;
    }

    const now = new Date();
    const ts = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}_${String(now.getHours()).padStart(2, '0')}${String(now.getMinutes()).padStart(2, '0')}${String(now.getSeconds()).padStart(2, '0')}`;
    const defaultName = `export_${ts}.pdf`;

    let path;
    if (window.electronAPI) {
      path = await window.electronAPI.saveFile({
        title: '导出PDF',
        defaultPath: defaultName,
        filters: [{ name: 'PDF 文件', extensions: ['pdf'] }],
      });
    } else {
      path = prompt('导出路径', defaultName);
    }
    if (!path) return;

    try {
      StatusBar.setMessage('正在生成 PDF…');
      const blob = await ApiClient.exportPdf();
      if (window.electronAPI) {
        await ApiClient.exportPdf(path);
        StatusBar.setMessage(`导出成功: ${path.split(/[\\/]/).pop()}`);
      } else {
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = defaultName;
        a.click();
        URL.revokeObjectURL(a.href);
        StatusBar.setMessage(`导出成功: ${defaultName}`);
      }
    } catch (e) {
      StatusBar.setMessage(`导出失败: ${e.message}`);
    }
  }

  async function onPreview() {
    if (!AppState.get('pdfDoc')) {
      StatusBar.setMessage('请先导入 PDF 文件');
      return;
    }
    try {
      await Sidebar.flushPendingSave();
      const idx = AppState.get('currentFileIndex');
      const page = AppState.get('currentPage') ?? 0;
      if (idx >= 0) {
        const state = await ApiClient.getState();
        if (state.current_file_index !== idx) {
          await ApiClient.selectFile(idx, page);
        } else {
          await ApiClient.navigatePage(page);
        }
      } else {
        await ApiClient.navigatePage(page);
      }
      if (window.electronAPI?.openPreview) {
        window.electronAPI.openPreview();
      } else {
        const f = WebSession.currentFile();
        if (!f?.id) throw new Error('当前文件无效，请重新导入 PDF');
        await WebSession.savePreviewBridge();
        window._topdfPreviewPdfId = f.id;
        const q = new URLSearchParams({ fileId: f.id, t: String(Date.now()) });
        window.open(`/preview/?${q}`, '_blank', 'noopener');
      }
      StatusBar.setMessage('上课模式已打开');
    } catch (e) {
      StatusBar.setMessage(`打开上课模式失败: ${e.message}`);
    }
  }

  function onSettings() {
    SettingsDialog.show();
  }

  function validateAnnotateReady() {
    const files = AppState.get('selectedFiles');
    if (!files || files.length === 0) {
      Dialogs.showWarning('警告', '请先导入文件');
      return false;
    }
    const settings = AppState.state.settings;
    const provider = settings.llm.provider;
    if (provider === 'openai' && !settings.llm.openai.api_key) {
      Dialogs.showWarning('警告', '请先在设置中配置 OpenAI API Key');
      return false;
    }
    if (provider === 'deepseek' && !settings.llm.deepseek.api_key) {
      Dialogs.showWarning('警告', '请先在设置中配置 DeepSeek API Key');
      return false;
    }
    if (provider === 'xiaomi' && !settings.llm.xiaomi.api_key) {
      Dialogs.showWarning('警告', '请先在设置中配置小米 MiMo API Key');
      return false;
    }
    if (provider === 'agnes' && !settings.llm.agnes.api_key) {
      Dialogs.showWarning('警告', '请先在设置中配置 Agnes API Key');
      return false;
    }
    return true;
  }

  function setAnnotateButtonsState(enabled) {
    const state = enabled ? false : true;
    document.getElementById('btn-annotate').disabled = state;
    document.getElementById('btn-annotate-all').disabled = state;
  }

  return { init };
})();
