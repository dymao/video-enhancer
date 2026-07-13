const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('videoEnhancer', {
  getDefaults: () => ipcRenderer.invoke('app:get-defaults'),
  selectOutputDir: () => ipcRenderer.invoke('dialog:select-output-dir'),
  selectCookiesFile: () => ipcRenderer.invoke('dialog:select-cookies-file'),
  importBrowserCookies: () => ipcRenderer.invoke('cookies:import-browser'),
  getQualityOptions: (payload) => ipcRenderer.invoke('video:get-quality-options', payload),
  openPath: (targetPath) => ipcRenderer.invoke('shell:open-path', targetPath),
  startWorker: (payload) => ipcRenderer.invoke('worker:start', payload),
  cancelWorker: () => ipcRenderer.invoke('worker:cancel'),
  onWorkerEvent: (callback) => {
    const listener = (_event, payload) => callback(payload);
    ipcRenderer.on('worker:event', listener);
    return () => ipcRenderer.removeListener('worker:event', listener);
  },
});
