'use strict';

/**
 * 外壳窗口（标题栏 / 工具栏 / 侧边栏 / 状态栏）与主进程之间的桥。
 * 只暴露白名单方法，内容区的网页不加载任何 preload。
 */

const { contextBridge, ipcRenderer } = require('electron');

const CHANNELS = {
  state: 'lc:view-state',
  window: 'lc:window-state',
  download: 'lc:download-state',
  account: 'lc:account-state',
  boot: 'lc:boot',
  update: 'lc:update-state',
};

contextBridge.exposeInMainWorld('lc', {
  /* 主动动作 */
  action(name, payload) {
    ipcRenderer.send('lc:action', String(name), payload);
  },

  /* 主进程 -> 外壳 的状态推送 */
  onViewState(cb) {
    ipcRenderer.on(CHANNELS.state, (event, state) => cb(state));
  },
  onWindowState(cb) {
    ipcRenderer.on(CHANNELS.window, (event, state) => cb(state));
  },
  onDownloadState(cb) {
    ipcRenderer.on(CHANNELS.download, (event, state) => cb(state));
  },
  onAccountState(cb) {
    ipcRenderer.on(CHANNELS.account, (event, state) => cb(state));
  },
  onBoot(cb) {
    ipcRenderer.on(CHANNELS.boot, (event, boot) => cb(boot));
  },
  onUpdateState(cb) {
    ipcRenderer.on(CHANNELS.update, (event, state) => cb(state));
  },
});
