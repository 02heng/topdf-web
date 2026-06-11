/**
 * 浏览器端文件存储 — IndexedDB 保存上传的 PDF/PPT 及转换后的 PDF
 */
const FileStore = (() => {
  const DB_NAME = 'topdf-web';
  const DB_VERSION = 1;
  const STORE = 'files';
  let dbPromise = null;

  function openDb() {
    if (dbPromise) return dbPromise;
    dbPromise = new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains(STORE)) {
          db.createObjectStore(STORE, { keyPath: 'id' });
        }
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
    return dbPromise;
  }

  async function put(record) {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, 'readwrite');
      tx.objectStore(STORE).put(record);
      tx.oncomplete = () => resolve(record);
      tx.onerror = () => reject(tx.error);
    });
  }

  async function get(id) {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, 'readonly');
      const req = tx.objectStore(STORE).get(id);
      req.onsuccess = () => resolve(req.result || null);
      req.onerror = () => reject(req.error);
    });
  }

  async function remove(id) {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, 'readwrite');
      tx.objectStore(STORE).delete(id);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  }

  function makeId() {
    return `f_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;
  }

  async function saveUploadedFile(file, pdfBytes, meta = {}) {
    const id = makeId();
    const record = {
      id,
      name: file.name,
      mime: file.type || 'application/octet-stream',
      originalBytes: await file.arrayBuffer(),
      pdfBytes: pdfBytes || await file.arrayBuffer(),
      totalPages: meta.totalPages || 0,
      createdAt: Date.now(),
    };
    await put(record);
    return record;
  }

  async function getPdfArrayBuffer(fileId) {
    const rec = await get(fileId);
    if (!rec?.pdfBytes) throw new Error('PDF 不可用');
    return rec.pdfBytes instanceof ArrayBuffer ? rec.pdfBytes : rec.pdfBytes.buffer;
  }

  async function getPdfBase64(fileId) {
    const buf = await getPdfArrayBuffer(fileId);
    const bytes = new Uint8Array(buf);
    let binary = '';
    const chunk = 0x8000;
    for (let i = 0; i < bytes.length; i += chunk) {
      binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
    }
    return btoa(binary);
  }

  return { put, get, remove, saveUploadedFile, getPdfArrayBuffer, getPdfBase64, makeId };
})();
