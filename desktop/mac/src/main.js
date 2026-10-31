'use strict';

/**
 * 教学管理系统 · macOS 客户端（桌面应用版）
 *
 * 架构：无边框窗口 + 自绘外壳（标题栏 / 工具栏 / 侧边导航 / 状态栏）
 *       网页内容由 WebContentsView 作为原生子视图嵌入内容区。
 */

const {
  app,
  BrowserWindow,
  WebContentsView,
  Menu,
  shell,
  session,
  dialog,
  Notification,
  nativeImage,
  clipboard,
  Tray,
  ipcMain,
} = require('electron');
const path = require('path');
const fs = require('fs');

const updater = require('./updater');

const SITE_ORIGIN = 'https://your-server.example.com';
const SITE_URL = SITE_ORIGIN + '/';
const SITE_HOSTS = ['your-server.example.com'];
const OFFLINE_FILE = path.join(__dirname, 'offline.html');

/* 外壳尺寸，必须与 shell.css 保持一致（bilibili 式排版：顶栏 + 左侧图标栏） */
const L = { appbar: 56, progress: 3, status: 26, sidebar: 76 };
const CHROME_TOP = L.appbar + L.progress;

/* 窗口外观
 * macOS：用系统原生的左上角红绿灯（titleBarStyle: hiddenInset），不再自绘窗口按钮。
 *        trafficLightPosition 把三颗灯垂直居中到 56px 的顶栏里；
 *        shell.css 的 .appbar 左侧留了 78px 内边距避免品牌区压在灯上（两处要一起改）。
 * 其它平台：沿用自绘无边框标题栏。 */
const WINDOW_CHROME = process.platform === 'darwin'
  ? { titleBarStyle: 'hiddenInset', trafficLightPosition: { x: 18, y: 22 } }
  : { frame: false };

const ICON_PATH = path.join(__dirname, '..', 'assets', 'icon.png');
const TRAY_PATH = path.join(__dirname, '..', 'assets', 'tray.png');
const PRELOAD = path.join(__dirname, 'preload.js');

const USER_DATA = app.getPath('userData');
const CONFIG_FILE = path.join(USER_DATA, 'window-state.json');

let mainWindow = null;
let splashWindow = null;
let tray = null;
let isQuitting = false;

/* ------------------------------------------------------------------ *
 * 配置持久化
 * ------------------------------------------------------------------ */

const DEFAULT_STATE = {
  width: 1440,
  height: 900,
  x: undefined,
  y: undefined,
  maximized: false,
  zoom: 0,
  sidebarVisible: true,
  appMode: true,
  autoCheckUpdate: true,
  skippedVersion: '',
};

let settings = Object.assign({}, DEFAULT_STATE);

function loadState() {
  try {
    settings = Object.assign({}, DEFAULT_STATE, JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf8')));
  } catch (err) {
    settings = Object.assign({}, DEFAULT_STATE);
  }
}

function saveState(patch) {
  if (patch) Object.assign(settings, patch);
  try {
    fs.mkdirSync(USER_DATA, { recursive: true });
    fs.writeFileSync(CONFIG_FILE, JSON.stringify(settings, null, 2), 'utf8');
  } catch (err) {
    /* 忽略 */
  }
}

function persistBounds(win) {
  if (!win || win.isDestroyed() || win !== mainWindow) return;
  const maximized = win.isMaximized();
  const b = maximized ? { width: settings.width, height: settings.height } : win.getNormalBounds();
  saveState({ width: b.width, height: b.height, x: b.x, y: b.y, maximized });
}

/* ------------------------------------------------------------------ *
 * 链接判定
 * ------------------------------------------------------------------ */

function hostOf(rawUrl) {
  try {
    return new URL(rawUrl).hostname.toLowerCase();
  } catch (err) {
    return '';
  }
}

function isSiteUrl(rawUrl) {
  const host = hostOf(rawUrl);
  return SITE_HOSTS.some((h) => host === h || host.endsWith('.' + h));
}

/* ------------------------------------------------------------------ *
 * 布局：把网页视图放进内容区
 * ------------------------------------------------------------------ */

function layout(win) {
  if (!win || win.isDestroyed() || !win._lc) return;
  const view = win._lc.view;
  if (!view) return;
  const [w, h] = win.getContentSize();
  const sideW = win._lc.sidebarVisible ? L.sidebar : 0;
  view.setBounds({
    x: sideW,
    y: CHROME_TOP,
    width: Math.max(1, w - sideW),
    height: Math.max(1, h - CHROME_TOP - L.status),
  });
}

function sendToShell(win, channel, payload) {
  if (!win || win.isDestroyed()) return;
  const wc = win.webContents;
  if (wc && !wc.isDestroyed()) wc.send(channel, payload);
}

/* ------------------------------------------------------------------ *
 * 视图状态推送
 * ------------------------------------------------------------------ */

function viewState(win) {
  const s = win._lc.viewState;
  sendToShell(win, 'lc:view-state', {
    url: s.url,
    path: s.path,
    title: s.title,
    docTitle: s.docTitle,
    canGoBack: s.canGoBack,
    canGoForward: s.canGoForward,
    loading: s.loading,
    phase: s.phase,
    zoom: s.zoom,
  });
}

function syncNavState(win) {
  const wc = win._lc.view.webContents;
  const s = win._lc.viewState;
  try {
    s.canGoBack = wc.navigationHistory.canGoBack();
    s.canGoForward = wc.navigationHistory.canGoForward();
  } catch (err) {
    s.canGoBack = false;
    s.canGoForward = false;
  }
}

/* ------------------------------------------------------------------ *
 * 应用模式：隐藏网页自身重复的顶部导航（品牌 + 页面链接），保留右侧账户入口
 * ------------------------------------------------------------------ */

const APP_MODE_CSS = `
  /* 客户端已用自绘工具栏 + 侧边导航替代站点顶部导航，整条隐藏避免重复 */
  header.nav { display: none !important; }
  .main { padding-top: 22px; }
  /* 桌面端：收紧站点的浮层圆角与阴影，贴合应用观感 */
  ::-webkit-scrollbar { width: 12px; height: 12px; }
  ::-webkit-scrollbar-track { background: #fafbfd; }
  ::-webkit-scrollbar-thumb { background: #ccd3de; border: 3px solid #fafbfd; border-radius: 8px; }
  ::-webkit-scrollbar-thumb:hover { background: #b3bccb; }
`;

async function applyAppMode(win) {
  if (!win._lc || !win._lc.view) return;
  const wc = win._lc.view.webContents;
  if (win._lc.cssKey) {
    try {
      await wc.removeInsertedCSS(win._lc.cssKey);
    } catch (err) {
      /* 导航后旧 key 失效，忽略 */
    }
    win._lc.cssKey = null;
  }
  if (settings.appMode && wc.getURL().startsWith(SITE_ORIGIN)) {
    try {
      win._lc.cssKey = await wc.insertCSS(APP_MODE_CSS);
    } catch (err) {
      /* 忽略 */
    }
  }
}

/* ------------------------------------------------------------------ *
 * 会话状态（用于工具栏账户区 / 侧栏底部 / 菜单账户段）
 *
 * 站点有两套独立鉴权，必须都认：
 *   1) 网页登录 → Flask session cookie（session["uid"]），页面路由据此放行
 *   2) 接口登录 → Authorization: Bearer <token>，仅 /api/v1/* 认
 * 网页登录不会产生 token，所以只查 /api/v1/me 会把已登录误判成未登录。
 * 因此优先读页面里渲染出来的账户区（base.html 的 .nav-right），
 * 拿不到再退回 token 探测。
 * ------------------------------------------------------------------ */

const PROBE_ACCOUNT_JS = `(() => {
  try {
    const nr = document.querySelector('.nav-right');
    if (!nr) return JSON.stringify({ found: false });
    // 已登录时 base.html 渲染「个人中心 + 退出」两个链接
    const out = nr.querySelector('a[href*="logout"]');
    if (!out) return JSON.stringify({ found: true, loggedIn: false, name: '' });
    const me = nr.querySelector('a[href*="/me"]');
    let name = '';
    if (me) {
      const spans = me.querySelectorAll('span');
      name = (spans.length ? spans[spans.length - 1].textContent : me.textContent) || '';
    }
    return JSON.stringify({ found: true, loggedIn: true, name: name.trim() });
  } catch (e) {
    return JSON.stringify({ found: false });
  }
})()`;

async function refreshAccount(win) {
  if (!win._lc || win._lc.mode !== 'main') return;

  let loggedIn = false;
  let name = '';

  // 1) 页面会话：直接问渲染出来的账户区
  try {
    const wc = win._lc.view && win._lc.view.webContents;
    if (wc && !wc.isDestroyed() && wc.getURL().startsWith(SITE_ORIGIN)) {
      const raw = await wc.executeJavaScript(PROBE_ACCOUNT_JS, false);
      const d = raw ? JSON.parse(raw) : null;
      if (d && d.found) {
        loggedIn = Boolean(d.loggedIn);
        name = d.name || '';
      }
    }
  } catch (err) {
    /* 保持未登录，继续尝试 token */
  }

  // 2) token 兜底（接口登录 / 安卓式登录）
  if (!loggedIn) {
    try {
      const s = session.fromPartition('persist:teaching-system');
      const res = await s.fetch(SITE_ORIGIN + '/api/v1/me', { method: 'GET' });
      const body = await res.json().catch(() => null);
      const d = body && body.data ? body.data : null;
      const u = d && (d.user || d);
      const n = u ? u.nickname || u.username || '' : '';
      if (res.ok && body && body.ok && (n || (u && u.id))) {
        loggedIn = true;
        name = n;
      }
    } catch (err) {
      /* 忽略 */
    }
  }

  win._lc.account = { loggedIn: Boolean(loggedIn), name: String(name || '') };
  sendToShell(win, 'lc:account-state', { loggedIn, name });
}

/* ------------------------------------------------------------------ *
 * 下载
 * ------------------------------------------------------------------ */

let downloadHandlerReady = false;

function setupDownloadHandler(s) {
  if (downloadHandlerReady) return;
  downloadHandlerReady = true;

  s.on('will-download', (event, item) => {
    const name = item.getFilename();
    if (!item.getSavePath()) {
      item.setSavePath(path.join(app.getPath('downloads'), name));
    }

    const targetWin = () => {
      const f = BrowserWindow.getFocusedWindow();
      if (f && !f.isDestroyed()) return f;
      return mainWindow && !mainWindow.isDestroyed() ? mainWindow : null;
    };

    const w0 = targetWin();
    if (w0) w0.setProgressBar(0);

    item.on('updated', (e, state) => {
      if (state !== 'progressing') return;
      const total = item.getTotalBytes();
      if (total <= 0) return;
      const got = item.getReceivedBytes();
      const w = targetWin();
      if (w) w.setProgressBar(got / total);
      if (mainWindow && !mainWindow.isDestroyed()) {
        sendToShell(mainWindow, 'lc:download-state', {
          active: true,
          name: name,
          percent: Math.floor((got / total) * 100),
        });
      }
    });

    item.once('done', (e, state) => {
      const w = targetWin();
      if (w) w.setProgressBar(-1);
      if (mainWindow && !mainWindow.isDestroyed()) {
        sendToShell(mainWindow, 'lc:download-state', { active: false });
      }
      if (state === 'completed') {
        const savePath = item.getSavePath();
        if (savePath && fs.existsSync(savePath)) {
          askAfterDownload(w || mainWindow, savePath);
        } else {
          notify('下载完成', savePath ? path.basename(savePath) : name);
        }
      } else if (state === 'interrupted') {
        notify('下载中断', (name || '文件') + ' 未能完成，请重试');
      }
    });
  });
}

/**
 * 下载完成后让用户选择下一步：打开文件 / 打开所在文件夹 / 什么都不做。
 * 以前只发一条系统通知，用户还得自己去找文件——下载目录一深就找不着了。
 */
function askAfterDownload(win, fullPath) {
  const target = win && !win.isDestroyed() ? win : null;
  const name = path.basename(fullPath);
  dialog
    .showMessageBox(target, {
      type: 'info',
      title: '下载完成',
      message: name,
      detail: '文件已保存到：\n' + fullPath,
      buttons: ['打开文件', '打开所在文件夹', '完成'],
      defaultId: 0,
      cancelId: 2,
      noLink: true,
    })
    .then((res) => {
      if (res.response === 0) {
        // 没有关联程序时 openPath 会返回错误串，这时退回「打开所在文件夹」
        shell.openPath(fullPath).then((err) => {
          if (err) {
            shell.showItemInFolder(fullPath);
            notify('没有找到可以打开这个文件的应用', '已为你打开文件所在文件夹');
          }
        });
      } else if (res.response === 1) {
        shell.showItemInFolder(fullPath);
      }
    })
    .catch(() => {
      /* 窗口在弹窗期间被关闭等情况，忽略 */
    });
}

function notify(title, body, onClick) {
  try {
    if (!Notification.isSupported()) return null;
    const n = new Notification({
      title,
      body: String(body || '').slice(0, 180),
      icon: ICON_PATH,
      silent: false,
    });
    if (typeof onClick === 'function') n.on('click', onClick);
    n.show();
    return n;
  } catch (err) {
    /* 忽略 */
    return null;
  }
}

/* ------------------------------------------------------------------ *
 * 内容视图事件
 * ------------------------------------------------------------------ */

function wireView(win, view) {
  const wc = view.webContents;

  const isOfflineUrl = (u) => u.startsWith('file:') && u.includes('offline.html');

  wc.on('did-start-loading', () => {
    win._lc.viewState.loading = true;
    win._lc.viewState.phase = 'loading';
    viewState(win);
  });

  wc.on('did-stop-loading', () => {
    win._lc.viewState.loading = false;
    if (win._lc.viewState.phase !== 'error') win._lc.viewState.phase = 'ready';
    syncNavState(win);
    viewState(win);
  });

  wc.on('did-navigate', (event, url) => {
    const s = win._lc.viewState;
    s.url = url;
    s.docTitle = '';
    if (isOfflineUrl(url)) {
      s.path = '';
      s.title = '无法连接';
      s.phase = 'error';
    } else if (url.startsWith(SITE_ORIGIN)) {
      try {
        s.path = new URL(url).pathname || '/';
      } catch (err) {
        s.path = '/';
      }
      s.phase = 'ready';
    } else {
      s.path = '';
    }
    syncNavState(win);
    viewState(win);
  });

  wc.on('did-navigate-in-page', (event, url, isMainFrame) => {
    if (!isMainFrame) return;
    const s = win._lc.viewState;
    s.url = url;
    try {
      s.path = new URL(url).pathname || '/';
    } catch (err) {
      /* 忽略 */
    }
    syncNavState(win);
    viewState(win);
  });

  wc.on('page-title-updated', (event, title) => {
    // 无边框窗口：标题只作页内信息展示，绝不改写窗口标题（保持任务栏稳定）
    event.preventDefault();
    const t = String(title || '').replace(/\s+/g, ' ').trim();
    if (t) win._lc.viewState.docTitle = t;
    viewState(win);
  });

  wc.on('dom-ready', () => {
    applyAppMode(win);
  });

  wc.on('did-finish-load', () => {
    win._lc.viewState.loading = false;
    syncNavState(win);
    viewState(win);
    layout(win);
    applyAppMode(win);
    refreshAccount(win);
  });

  wc.on('did-fail-load', (event, code, desc, failedUrl, isMainFrame) => {
    if (!isMainFrame || code === -3) return;
    const s = win._lc.viewState;
    s.phase = 'error';
    s.loading = false;
    s.title = '无法连接';
    viewState(win);
    if (!String(failedUrl || '').startsWith('file:')) {
      wc.loadFile(OFFLINE_FILE, {
        query: { url: failedUrl || SITE_URL, code: String(code), desc: desc || '' },
      });
    }
  });

  wc.on('will-navigate', (event, url) => {
    if (!isSiteUrl(url) && !url.startsWith('file:')) {
      event.preventDefault();
      shell.openExternal(url);
    }
  });

  wc.setWindowOpenHandler(({ url }) => {
    if (isSiteUrl(url)) {
      openChildWindow(url);
    } else {
      shell.openExternal(url);
    }
    return { action: 'deny' };
  });

  wc.on('context-menu', (event, params) => {
    const items = [];
    if (params.linkURL) {
      items.push(
        { label: '在浏览器中打开', click: () => shell.openExternal(params.linkURL) },
        { label: '复制链接地址', click: () => clipboard.writeText(params.linkURL) },
        { type: 'separator' }
      );
    }
    if (params.isEditable) {
      items.push(
        { label: '撤销', role: 'undo' },
        { label: '重做', role: 'redo' },
        { type: 'separator' },
        { label: '剪切', role: 'cut' },
        { label: '复制', role: 'copy' },
        { label: '粘贴', role: 'paste' },
        { label: '全选', role: 'selectAll' },
        { type: 'separator' }
      );
    } else if (params.selectionText) {
      items.push(
        { label: '复制', role: 'copy' },
        { label: '全选', role: 'selectAll' },
        { type: 'separator' }
      );
    }
    items.push(
      {
        label: '后退',
        enabled: win._lc.viewState.canGoBack,
        click: () => wc.navigationHistory.goBack(),
      },
      {
        label: '前进',
        enabled: win._lc.viewState.canGoForward,
        click: () => wc.navigationHistory.goForward(),
      },
      { label: '刷新', click: () => wc.reload() },
      { type: 'separator' },
      { label: '开发者工具', click: () => wc.openDevTools({ mode: 'bottom' }) }
    );
    Menu.buildFromTemplate(items).popup({ window: win });
  });

  wc.on('render-process-gone', (event, details) => {
    if (win.isDestroyed()) return;
    dialog
      .showMessageBox(win, {
        type: 'error',
        title: '页面异常',
        message: '页面进程意外退出（' + details.reason + '）。',
        buttons: ['重新加载', '关闭'],
        defaultId: 0,
        cancelId: 1,
        noLink: true,
      })
      .then((res) => {
        if (res.response === 0 && !win.isDestroyed()) {
          wc.loadURL(win._lc.homeUrl);
        }
      });
  });

  /* 快捷键：菜单加速键之外再兜一层，保证无边框窗口下一定生效 */
  const onKey = (event, input) => {
    if (input.type !== 'keyDown') return;
    const k = (input.key || '').toLowerCase();
    const ctrl = input.control || input.meta;
    const shift = input.shift;
    const alt = input.alt;
    let act = null;

    if (k === 'f5') act = 'reload';
    else if (ctrl && shift && k === 'r') act = 'hardReload';
    else if (ctrl && k === 'r') act = 'reload';
    else if (alt && k === 'arrowleft') act = 'back';
    else if (alt && k === 'arrowright') act = 'forward';
    else if (alt && k === 'home') act = 'home';
    else if (k === 'f11') act = 'fullscreen';
    else if (k === 'f12') act = 'devtools';
    else if (ctrl && (k === '+' || k === '=' || k === 'add')) act = 'zoomIn';
    else if (ctrl && (k === '-' || k === 'subtract')) act = 'zoomOut';
    else if (ctrl && k === '0') act = 'zoomReset';
    else if (ctrl && k === 'q') act = 'quit';

    if (!act) return;
    event.preventDefault();
    runAction(win, act);
  };
  wc.on('before-input-event', onKey);
}

/* ------------------------------------------------------------------ *
 * 动作分发
 * ------------------------------------------------------------------ */

function runAction(win, name, payload) {
  if (!win || win.isDestroyed() || !win._lc || !win._lc.view) return;
  const wc = win._lc.view.webContents;

  // 菜单加速键与 before-input-event 可能重复触发，做去抖
  const now = Date.now();
  const key = name + ':' + (payload ? JSON.stringify(payload) : '');
  if (win._lc.lastAction && win._lc.lastAction.key === key && now - win._lc.lastAction.t < 160) {
    return;
  }
  win._lc.lastAction = { key, t: now };

  switch (name) {
    case 'back':
      if (wc.navigationHistory.canGoBack()) wc.navigationHistory.goBack();
      break;
    case 'forward':
      if (wc.navigationHistory.canGoForward()) wc.navigationHistory.goForward();
      break;
    case 'reload':
      wc.reload();
      break;
    case 'hardReload':
      wc.reloadIgnoringCache();
      break;
    case 'home':
      wc.loadURL(win._lc.homeUrl);
      break;
    case 'navigate':
      wc.loadURL(SITE_ORIGIN + payload);
      break;
    case 'openChild':
      openChildWindow(payload.url, payload.title);
      break;
    case 'zoomIn':
      settings.zoom = Math.min((win._lc.viewState.zoom || 0) + 0.5, 5);
      wc.setZoomLevel(settings.zoom);
      win._lc.viewState.zoom = settings.zoom;
      saveState();
      viewState(win);
      break;
    case 'zoomOut':
      settings.zoom = Math.max((win._lc.viewState.zoom || 0) - 0.5, -3);
      wc.setZoomLevel(settings.zoom);
      win._lc.viewState.zoom = settings.zoom;
      saveState();
      viewState(win);
      break;
    case 'zoomReset':
      settings.zoom = 0;
      wc.setZoomLevel(0);
      win._lc.viewState.zoom = 0;
      saveState();
      viewState(win);
      break;
    case 'sidebar':
      // 外壳传来的 payload 是「是否隐藏」（true=刚折叠）；主进程语义是「是否显示」，
      // 必须取反。曾因极性反了导致折叠/展开后内容视图与侧栏 DOM 不同步，
      // 内容视图盖住侧栏（或留白条），且错误的值被持久化。
      // （Windows 端 1.4.x 已修，macOS 端 1.0.5 同步修掉）
      win._lc.sidebarVisible = payload !== true;
      if (win === mainWindow) saveState({ sidebarVisible: win._lc.sidebarVisible });
      layout(win);
      Menu.setApplicationMenu(buildMenu());
      break;
    case 'menu': {
      // 工具栏 ☰ / 账户按钮：弹出系统原生菜单（外壳画的浮层会被内容区原生视图挡住）
      const menu = buildToolbarMenu(win, payload && payload.section === 'account');
      const anchor = {
        window: win,
        x: payload && typeof payload.x === 'number' ? Math.round(payload.x) : undefined,
        y: payload && typeof payload.y === 'number' ? Math.round(payload.y) : undefined,
      };
      menu.popup(anchor);
      break;
    }
    case 'minimize':
      win.minimize();
      break;
    case 'toggleMaximize':
      if (win.isMaximized()) win.unmaximize();
      else win.maximize();
      break;
    case 'fullscreen':
      win.setFullScreen(!win.isFullScreen());
      break;
    case 'close':
      win.close();
      break;
    case 'quit':
      // macOS 上 Cmd+Q 的语义是「退出应用」而不是「关掉当前窗口」
      isQuitting = true;
      app.quit();
      break;
    case 'devtools':
      wc.toggleDevTools();
      break;
    case 'clearSession': {
      dialog
        .showMessageBox(win, {
          type: 'question',
          title: '确认操作',
          message: '将清空本站的 Cookie 与本地存储，登录状态会失效。确定继续？',
          buttons: ['确定', '取消'],
          defaultId: 1,
          cancelId: 1,
          noLink: true,
        })
        .then(async (res) => {
          if (res.response !== 0) return;
          const s = session.fromPartition('persist:teaching-system');
          await s.clearStorageData({ storages: ['cookies', 'localstorage', 'indexdb'] });
          wc.loadURL(win._lc.homeUrl);
        });
      break;
    }
    case 'openDownloads':
      shell.openPath(app.getPath('downloads'));
      break;
    case 'openBrowser':
      shell.openExternal(SITE_URL);
      break;

    /* ---------------- OTA 在线升级 ---------------- */
    case 'updateReady':
    case 'updateShow':
    case 'updateCheck':
    case 'updateDownload':
    case 'updateCancel':
    case 'updateInstall':
    case 'updateLater':
    case 'updateSkip':
    case 'updateClearSkip':
    case 'updateOpenPage':
    case 'updateOpenFolder':
      handleUpdateAction(name);
      break;

    case 'about': {
      const us = updater.currentState();
      const detail = [
        '版本：' + app.getVersion() + (us.portable ? '（绿色版）' : '（安装版）'),
        '站点：' + SITE_URL,
        '内核：Chromium ' + process.versions.chrome,
        '',
        us.phase === 'available' && us.latest
          ? '发现新版本 v' + us.latest.versionName + '，可在「菜单 → 检查更新」中升级。'
          : '已开启自动检查更新（启动时与运行期间每 6 小时各一次）。',
        '',
        '教学管理系统官方桌面客户端。',
        '内容与服务端实时同步，登录、云盘、社区、挑战等功能与网页版一致。',
        '管理员：QQ2559709613',
      ].join('\n');
      dialog
        .showMessageBox(win, {
          type: 'info',
          title: '关于 教学管理系统',
          message: '教学管理系统 · macOS 客户端',
          detail,
          buttons: ['检查更新', '确定'],
          defaultId: 1,
          cancelId: 1,
          noLink: true,
          icon: nativeImage.createFromPath(ICON_PATH),
        })
        .then((res) => {
          if (res.response === 0) updater.check({ manual: true });
        });
      break;
    }
    default:
      break;
  }
}

/* ------------------------------------------------------------------ *
 * 窗口创建
 * ------------------------------------------------------------------ */

function baseWebPreferences(extra) {
  return Object.assign(
    {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      spellcheck: false,
    },
    extra || {}
  );
}

function attachView(win, homeUrl) {
  const view = new WebContentsView({
    webPreferences: baseWebPreferences({
      partition: 'persist:teaching-system',
      backgroundThrottling: false,
    }),
  });

  win.contentView.addChildView(view);

  win._lc.view = view;
  win._lc.homeUrl = homeUrl;
  win._lc.viewState = {
    url: homeUrl,
    path: '/',
    title: '',
    docTitle: '',
    canGoBack: false,
    canGoForward: false,
    loading: true,
    phase: 'loading',
    zoom: settings.zoom || 0,
  };

  view.webContents.setZoomLevel(settings.zoom || 0);
  wireView(win, view);
  view.webContents.loadURL(homeUrl);
}

/* ------------------------------------------------------------------ *
 * 更新对话框
 *
 * 为什么不用外壳页面里的浮层：内容区是原生 WebContentsView，永远盖在外壳
 * HTML 之上，外壳画的浮层会被网页挡住。所以更新界面做成独立的无边框模态
 * 子窗口 —— 既保证可见，也更接近 Windows 桌面软件的原生对话框。
 * ------------------------------------------------------------------ */

let updateWindow = null;
const UPDATE_W = 560;
const UPDATE_H = 512;

function destroyUpdateWindow() {
  const w = updateWindow;
  updateWindow = null;
  if (w && !w.isDestroyed()) {
    try { w.destroy(); } catch (err) { /* ignore */ }
  }
}

function showUpdateWindow() {
  if (!mainWindow || mainWindow.isDestroyed()) return null;
  if (updateWindow && !updateWindow.isDestroyed()) {
    // 下载过程中状态会频繁刷新，这里只在隐藏时重新显示，避免每次都抢焦点
    if (!updateWindow.isVisible()) {
      updateWindow.show();
      updateWindow.focus();
    }
    return updateWindow;
  }

  const b = mainWindow.getBounds();
  updateWindow = new BrowserWindow({
    width: UPDATE_W,
    height: UPDATE_H,
    x: Math.round(b.x + (b.width - UPDATE_W) / 2),
    y: Math.round(b.y + (b.height - UPDATE_H) / 2),
    parent: mainWindow,
    modal: true,
    show: false,
    frame: false,
    resizable: false,
    maximizable: false,
    minimizable: false,
    fullscreenable: false,
    skipTaskbar: true,
    backgroundColor: '#f3f3f3',
    title: '软件更新 · 教学管理系统',
    icon: ICON_PATH,
    webPreferences: baseWebPreferences({ preload: PRELOAD, backgroundThrottling: false }),
  });

  updateWindow.loadFile(path.join(__dirname, 'update.html'));
  updateWindow.once('ready-to-show', () => {
    if (!updateWindow || updateWindow.isDestroyed()) return;
    updateWindow.show();
    updateWindow.focus();
  });
  updateWindow.on('closed', () => {
    updateWindow = null;
  });
  return updateWindow;
}

/** 状态同时推给外壳（工具栏徽标 / 状态栏进度）和更新窗口 */
function pushUpdateState(state) {
  sendToShell(mainWindow, 'lc:update-state', state);
  if (updateWindow && !updateWindow.isDestroyed()) {
    updateWindow.webContents.send('lc:update-state', state);
  }
}

/** 由 state.dialog 决定更新窗口开关 */
function syncUpdateWindow(state) {
  if (state && state.dialog) showUpdateWindow();
  else destroyUpdateWindow();
}

/* 更新相关动作：外壳与更新窗口都会用，集中在一处 */
function handleUpdateAction(name) {
  switch (name) {
    case 'updateReady':
      syncUpdateWindow(updater.currentState());
      pushUpdateState(updater.currentState());
      break;
    case 'updateShow':
      updater.show();
      break;
    case 'updateCheck':
      updater.check({ manual: true });
      break;
    case 'updateDownload':
      updater.startDownload();
      break;
    case 'updateCancel':
      updater.cancelDownload();
      break;
    case 'updateInstall':
      updater.install();
      break;
    case 'updateLater':
      updater.later();
      break;
    case 'updateSkip':
      updater.skipVersion();
      break;
    case 'updateClearSkip':
      updater.clearSkip();
      updater.check({ manual: true });
      break;
    case 'updateOpenPage':
      updater.openDownloadPage();
      break;
    case 'updateOpenFolder':
      updater.openUpdateFolder();
      break;
    default:
      break;
  }
}

const UPDATE_ACTIONS = new Set([
  'updateReady',
  'updateShow',
  'updateCheck',
  'updateDownload',
  'updateCancel',
  'updateInstall',
  'updateLater',
  'updateSkip',
  'updateClearSkip',
  'updateOpenPage',
  'updateOpenFolder',
]);

function createMainWindow() {
  const opts = {
    width: settings.width,
    height: settings.height,
    minWidth: L.sidebar + 940,
    minHeight: 700,
    ...WINDOW_CHROME,
    show: false,
    resizable: true,
    backgroundColor: '#f3f3f3',
    title: '教学管理系统',
    icon: ICON_PATH,
    webPreferences: baseWebPreferences({
      preload: PRELOAD,
      backgroundThrottling: false,
    }),
  };
  if (typeof settings.x === 'number' && typeof settings.y === 'number') {
    opts.x = settings.x;
    opts.y = settings.y;
  }

  mainWindow = new BrowserWindow(opts);
  mainWindow._lc = {
    mode: 'main',
    sidebarVisible: settings.sidebarVisible !== false,
    cssKey: null,
    lastAction: null,
    account: { loggedIn: false, name: '' },
  };

  mainWindow.loadFile(path.join(__dirname, 'shell.html'), { query: { mode: 'main' } });
  attachView(mainWindow, SITE_URL);
  setupDownloadHandler(session.fromPartition('persist:teaching-system'));

  if (settings.maximized) mainWindow.maximize();

  const pushWindowState = () =>
    sendToShell(mainWindow, 'lc:window-state', { maximized: mainWindow.isMaximized() });

  mainWindow.on('maximize', () => {
    pushWindowState();
    persistBounds(mainWindow);
  });
  mainWindow.on('unmaximize', () => {
    pushWindowState();
    persistBounds(mainWindow);
  });
  mainWindow.on('resize', () => {
    layout(mainWindow);
    persistBounds(mainWindow);
  });
  mainWindow.on('move', () => persistBounds(mainWindow));
  mainWindow.on('enter-full-screen', () => layout(mainWindow));
  mainWindow.on('leave-full-screen', () => layout(mainWindow));

  mainWindow.webContents.once('did-finish-load', () => {
    sendToShell(mainWindow, 'lc:boot', {
      appVersion: app.getVersion(),
      sidebar: mainWindow._lc.sidebarVisible,
      appMode: settings.appMode,
      sidebarWidth: L.sidebar,
    });
    sendToShell(mainWindow, 'lc:update-state', updater.currentState());
    pushWindowState();
    layout(mainWindow);
  });

  // 外壳页面本身不应该导航
  mainWindow.webContents.on('will-navigate', (event) => event.preventDefault());
  mainWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));

  mainWindow.webContents.on('before-input-event', (event, input) => {
    if (input.type !== 'keyDown') return;
    const k = (input.key || '').toLowerCase();
    const ctrl = input.control || input.meta;
    let act = null;
    if (k === 'f5' || (ctrl && k === 'r')) act = 'reload';
    else if (k === 'f11') act = 'fullscreen';
    else if (k === 'f12') act = 'devtools';
    else if (ctrl && k === 'q') act = 'quit';
    if (!act) return;
    event.preventDefault();
    runAction(mainWindow, act);
  });

  mainWindow.once('ready-to-show', () => {
    closeSplash();
    if (!mainWindow.isDestroyed()) mainWindow.show();
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  return mainWindow;
}

function openChildWindow(url, title) {
  const win = new BrowserWindow({
    width: 1180,
    height: 800,
    minWidth: 720,
    minHeight: 520,
    ...WINDOW_CHROME,
    show: false,
    backgroundColor: '#f3f3f3',
    title: title || '教学管理系统',
    icon: ICON_PATH,
    parent: mainWindow && !mainWindow.isDestroyed() ? mainWindow : undefined,
    webPreferences: baseWebPreferences({
      preload: PRELOAD,
      backgroundThrottling: false,
    }),
  });

  win._lc = {
    mode: 'sub',
    sidebarVisible: false,
    cssKey: null,
    lastAction: null,
  };

  win.loadFile(path.join(__dirname, 'shell.html'), {
    query: { mode: 'sub', url: url || '', title: title || '' },
  });
  attachView(win, url);

  const pushWindowState = () => sendToShell(win, 'lc:window-state', { maximized: win.isMaximized() });
  win.on('maximize', pushWindowState);
  win.on('unmaximize', pushWindowState);
  win.on('resize', () => layout(win));
  win.on('enter-full-screen', () => layout(win));
  win.on('leave-full-screen', () => layout(win));

  win.webContents.once('did-finish-load', () => {
    sendToShell(win, 'lc:boot', { appVersion: app.getVersion(), sidebar: false });
    pushWindowState();
    layout(win);
  });

  win.once('ready-to-show', () => {
    if (!win.isDestroyed()) win.show();
  });

  return win;
}

/* ------------------------------------------------------------------ *
 * 启动画面 / 托盘
 * ------------------------------------------------------------------ */

function createSplash() {
  splashWindow = new BrowserWindow({
    width: 420,
    height: 264,
    frame: false,
    resizable: false,
    center: true,
    show: true,
    backgroundColor: '#1f4e79',
    skipTaskbar: true,
    alwaysOnTop: true,
    icon: ICON_PATH,
    webPreferences: baseWebPreferences(),
  });
  splashWindow.loadFile(path.join(__dirname, 'splash.html'));
  splashWindow.on('closed', () => {
    splashWindow = null;
  });
}

function closeSplash() {
  if (splashWindow && !splashWindow.isDestroyed()) splashWindow.close();
}

function createTray() {
  try {
    if (!fs.existsSync(TRAY_PATH)) return;
    const img = nativeImage.createFromPath(TRAY_PATH);
    if (img.isEmpty()) return;
    tray = new Tray(img.resize({ width: 16, height: 16 }));
    tray.setToolTip('教学管理系统 · macOS 客户端');
    tray.setContextMenu(
      Menu.buildFromTemplate([
        {
          label: '显示主窗口',
          click: () => {
            if (!mainWindow || mainWindow.isDestroyed()) createMainWindow();
            else {
              if (mainWindow.isMinimized()) mainWindow.restore();
              mainWindow.show();
              mainWindow.focus();
            }
          },
        },
        { label: '回到首页', click: () => runAction(mainWindow, 'home') },
        { label: '检查更新…', click: () => runAction(mainWindow, 'updateCheck') },
        { label: '在浏览器中打开网站', click: () => shell.openExternal(SITE_URL) },
        { type: 'separator' },
        {
          label: '退出',
          click: () => {
            isQuitting = true;
            app.quit();
          },
        },
      ])
    );
    tray.on('double-click', () => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.show();
        mainWindow.focus();
      }
    });
  } catch (err) {
    /* 托盘不可用则忽略 */
  }
}

/* ------------------------------------------------------------------ *
 * 外壳 -> 主进程
 * ------------------------------------------------------------------ */

function setupIpc() {
  ipcMain.on('lc:action', (event, name, payload) => {
    const win = BrowserWindow.fromWebContents(event.sender);
    if (!win || win.isDestroyed()) return;
    const act = String(name);

    // 更新对话框是模态子窗口，没有内容视图，动作一律转交主窗口处理
    if (updateWindow && win === updateWindow) {
      if (UPDATE_ACTIONS.has(act)) handleUpdateAction(act);
      return;
    }
    if (act === 'updateReady') {
      handleUpdateAction(act);
      return;
    }
    runAction(win, act, payload);
  });
}

/* ------------------------------------------------------------------ *
 * 菜单（无边框窗口不显示菜单栏，用于 ☰ 菜单按钮弹出，同时提供加速键）
 * ------------------------------------------------------------------ */

function buildMenu() {
  const A = (name, payload) => () => runAction(BrowserWindow.getFocusedWindow() || mainWindow, name, payload);
  const target = () => BrowserWindow.getFocusedWindow() || mainWindow;

  // macOS 的应用菜单（以 App 名命名，含 关于/服务/隐藏/退出）。用自绘无边框窗口时不需要，
  // 换成系统原生红绿灯后就该有——这也是 Cmd+Q / Cmd+H 的标准落点。
  const appMenu = process.platform === 'darwin' ? [{
    label: app.name,
    submenu: [
      { label: '关于教学管理系统', click: A('about') },
      { type: 'separator' },
      { label: '服务', role: 'services', submenu: [] },
      { type: 'separator' },
      { label: '隐藏教学管理系统', role: 'hide' },
      { label: '隐藏其他', role: 'hideOthers' },
      { label: '全部显示', role: 'unhide' },
      { type: 'separator' },
      { label: '退出教学管理系统', role: 'quit' },
    ],
  }] : [];

  return Menu.buildFromTemplate([
    ...appMenu,
    {
      label: '文件',
      submenu: [
        { label: '关闭窗口', role: 'close' },
        { label: '刷新', accelerator: 'F5', click: A('reload') },
        { label: '强制刷新（忽略缓存）', accelerator: 'CmdOrCtrl+Shift+R', click: A('hardReload') },
        { type: 'separator' },
        {
          label: '应用模式（隐藏网页顶部导航）',
          type: 'checkbox',
          checked: settings.appMode !== false,
          click: (item) => {
            settings.appMode = item.checked;
            saveState();
            const w = mainWindow;
            if (w && !w.isDestroyed() && w._lc && w._lc.view) {
              w._lc.view.webContents.reload();
            }
          },
        },
        {
          label: '显示侧边导航',
          type: 'checkbox',
          checked: settings.sidebarVisible !== false,
          click: (item) => {
            if (mainWindow && !mainWindow.isDestroyed()) {
              mainWindow._lc.sidebarVisible = item.checked;
              saveState({ sidebarVisible: item.checked });
              layout(mainWindow);
              sendToShell(mainWindow, 'lc:boot', {
                appVersion: app.getVersion(),
                sidebar: item.checked,
                sidebarWidth: L.sidebar,
              });
            }
          },
        },
        {
          label: '自动检查更新',
          type: 'checkbox',
          checked: settings.autoCheckUpdate !== false,
          click: (item) => {
            settings.autoCheckUpdate = item.checked;
            saveState();
            if (item.checked) updater.check({ manual: false });
          },
        },
        { type: 'separator' },
        { label: '检查更新…', click: A('updateCheck') },
        { type: 'separator' },
        { label: '清空登录状态并重新加载', click: A('clearSession') },
      ],
    },
    {
      label: '导航',
      submenu: [
        { label: '后退', accelerator: 'Alt+Left', click: A('back') },
        { label: '前进', accelerator: 'Alt+Right', click: A('forward') },
        { type: 'separator' },
        { label: '首页', accelerator: 'Alt+Home', click: A('home') },
        { type: 'separator' },
        { label: '课程资料', click: A('navigate', '/courses') },
        { label: '挑战', click: A('navigate', '/challenges') },
        { label: '社区', click: A('navigate', '/community') },
        { label: '云盘', click: A('navigate', '/drive') },
        { label: '文件系统', click: A('navigate', '/files') },
        { label: '报到', click: A('navigate', '/report') },
        { type: 'separator' },
        {
          label: '考试系统',
          click: () => openChildWindow('https://exam.your-server.example.com', '考试系统'),
        },
        {
          label: 'Docker 管理面板',
          click: () => openChildWindow('https://docker.your-server.example.com', 'Docker 管理面板'),
        },
      ],
    },
    {
      label: '编辑',
      submenu: [
        { label: '撤销', role: 'undo' },
        { label: '重做', role: 'redo' },
        { type: 'separator' },
        { label: '剪切', role: 'cut' },
        { label: '复制', role: 'copy' },
        { label: '粘贴', role: 'paste' },
        { label: '全选', role: 'selectAll' },
      ],
    },
    {
      label: '视图',
      submenu: [
        { label: '放大', accelerator: 'CmdOrCtrl+Plus', click: A('zoomIn') },
        { label: '缩小', accelerator: 'CmdOrCtrl+-', click: A('zoomOut') },
        { label: '实际大小', accelerator: 'CmdOrCtrl+0', click: A('zoomReset') },
        { type: 'separator' },
        {
          label: '全屏',
          accelerator: 'F11',
          click: () => {
            const w = target();
            if (w) w.setFullScreen(!w.isFullScreen());
          },
        },
        { type: 'separator' },
        {
          label: '开发者工具',
          accelerator: 'F12',
          click: () => {
            const w = target();
            if (w && w._lc && w._lc.view) w._lc.view.webContents.toggleDevTools();
          },
        },
      ],
    },
    // macOS 标准「窗口」菜单：自绘按钮去掉后，Cmd+M 最小化 / Cmd+W 关闭都靠这里
    {
      label: '窗口',
      submenu: [
        { label: '最小化', role: 'minimize' },
        { label: '缩放', role: 'zoom' },
        { type: 'separator' },
        { label: '关闭窗口', role: 'close' },
        { type: 'separator' },
        { label: '全部置于顶层', role: 'front' },
      ],
    },
    {
      label: '帮助',
      submenu: [
        { label: '检查更新…', click: A('updateCheck') },
        { type: 'separator' },
        { label: '在浏览器中打开网站', click: A('openBrowser') },
        { label: '打开下载目录', click: A('openDownloads') },
        { type: 'separator' },
        { label: '关于本软件', click: A('about') },
      ],
    },
  ]);
}

/* ------------------------------------------------------------------ *
 * 工具栏 ☰ / 账户按钮弹出的原生菜单
 *
 * 说明：外壳页面里画的浮层会被内容区的原生 WebContentsView 盖住，
 * 所以这两处弹层改用系统原生菜单，天然置顶且与 Windows 观感一致。
 * ------------------------------------------------------------------ */

function updateMenuEntry(win) {
  const go = (name) => () => runAction(win, name);
  const us = updater.currentState();
  const label = us.latest ? us.latest.versionName : '';

  if (us.phase === 'checking') return { label: '正在检查更新…', enabled: false };
  if (us.phase === 'downloading') return { label: '正在下载更新 ' + us.percent + '%', click: go('updateShow') };
  if (us.phase === 'installing') return { label: '正在安装更新…', enabled: false };
  if (us.phase === 'ready') return { label: '安装已下载的 v' + label, click: go('updateInstall') };
  if (us.phase === 'available') return { label: '安装新版本 v' + label + '…', click: go('updateShow') };
  return { label: '检查更新…', click: go('updateCheck') };
}

function buildToolbarMenu(win, accountOnly) {
  if (!win || win.isDestroyed() || !win._lc) return Menu.buildFromTemplate([]);
  const acct = win._lc.account || { loggedIn: false, name: '' };
  const go = (name, payload) => () => runAction(win, name, payload);

  const account = [
    { label: acct.loggedIn ? '已登录：' + (acct.name || '用户') : '未登录（登录后可上传、发帖、报到）', enabled: false },
    { type: 'separator' },
  ];
  if (acct.loggedIn) {
    account.push({ label: '个人中心', click: go('navigate', '/me') });
    account.push({ label: '退出登录', click: go('navigate', '/logout') });
  } else {
    account.push({ label: '登录', click: go('navigate', '/login') });
    account.push({ label: '注册新账号', click: go('navigate', '/register') });
  }

  if (accountOnly) return Menu.buildFromTemplate(account);

  const items = account.concat([
    { type: 'separator' },
    { label: '刷新', accelerator: 'F5', click: go('reload') },
    { label: '强制刷新（忽略缓存）', accelerator: 'CmdOrCtrl+Shift+R', click: go('hardReload') },
    { label: '回到首页', accelerator: 'Alt+Home', click: go('home') },
    { type: 'separator' },
    { label: '放大', accelerator: 'CmdOrCtrl+Plus', click: go('zoomIn') },
    { label: '缩小', accelerator: 'CmdOrCtrl+-', click: go('zoomOut') },
    { label: '实际大小', accelerator: 'CmdOrCtrl+0', click: go('zoomReset') },
    { type: 'separator' },
    {
      label: '全屏',
      accelerator: 'F11',
      click: () => win.setFullScreen(!win.isFullScreen()),
    },
    {
      label: '开发者工具',
      accelerator: 'F12',
      click: () => {
        if (win._lc && win._lc.view) win._lc.view.webContents.toggleDevTools();
      },
    },
    { type: 'separator' },
    {
      label: '显示侧边导航',
      type: 'checkbox',
      checked: win._lc.sidebarVisible !== false,
      click: (item) => {
        win._lc.sidebarVisible = item.checked;
        saveState({ sidebarVisible: item.checked });
        layout(win);
        sendToShell(win, 'lc:boot', {
          appVersion: app.getVersion(),
          sidebar: item.checked,
          sidebarWidth: L.sidebar,
        });
      },
    },
    {
      label: '自动检查更新',
      type: 'checkbox',
      checked: settings.autoCheckUpdate !== false,
      click: (item) => {
        settings.autoCheckUpdate = item.checked;
        saveState();
        if (item.checked) updater.check({ manual: false });
      },
    },
    updateMenuEntry(win),
  ]);

  if (settings.skippedVersion) {
    items.push({
      label: '恢复被忽略的版本（v' + settings.skippedVersion + '）',
      click: go('updateClearSkip'),
    });
  }

  items.push(
    { type: 'separator' },
    { label: '打开下载文件夹', click: go('openDownloads') },
    { label: '清除缓存与登录状态…', click: go('clearSession') },
    { label: '关于本客户端', click: go('about') }
  );

  return Menu.buildFromTemplate(items);
}

/* ------------------------------------------------------------------ *
 * 生命周期
 * ------------------------------------------------------------------ */

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.show();
      mainWindow.focus();
    } else {
      createMainWindow();
    }
  });

  // 干净的 Chrome UA：让站点呈现与浏览器完全一致，不带 Electron 标识
  // macOS 版假装成 Mac 上的 Chrome，避免站点按 Windows 分支走差异化逻辑
  app.userAgentFallback = [
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
    'AppleWebKit/537.36 (KHTML, like Gecko)',
    'Chrome/' + process.versions.chrome.split('.')[0],
    'Safari/537.36',
  ].join(' ');

  app.commandLine.appendSwitch('lang', 'zh-CN');

  // 仅开发调试用：设置 LC_DEBUG_PORT 才开启远端调试端口（打包运行时不受影响）
  if (process.env.LC_DEBUG_PORT) {
    app.commandLine.appendSwitch('remote-debugging-port', String(process.env.LC_DEBUG_PORT));
  }

  app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit();
  });

  app.on('before-quit', () => {
    isQuitting = true;
  });

  app.whenReady().then(() => {
    // setAppUserModelId 仅 Windows 有效，macOS 上该 API 不存在
    if (process.platform === 'win32') app.setAppUserModelId('com.teachingsystem.desktop');
    loadState();

    const s = session.fromPartition('persist:teaching-system');
    s.setPermissionRequestHandler((wc, permission, callback) => {
      callback(
        [
          'clipboard-read',
          'clipboard-sanitized-write',
          'notifications',
          'fullscreen',
          'media',
          'pointerLock',
        ].includes(permission)
      );
    });
    s.setPermissionCheckHandler((wc, permission) =>
      ['clipboard-read', 'clipboard-sanitized-write', 'notifications', 'fullscreen'].includes(
        permission
      )
    );

    Menu.setApplicationMenu(buildMenu());
    setupIpc();
    createSplash();
    createMainWindow();
    createTray();

    updater.init({
      getSettings: () => settings,
      patchSettings: (patch) => saveState(patch),
      emit: (state) => {
        pushUpdateState(state);
        syncUpdateWindow(state);
      },
      getWindow: () => (mainWindow && !mainWindow.isDestroyed() ? mainWindow : null),
      notify: notify,
      isQuitting: () => {
        isQuitting = true;
      },
    });
    updater.scheduleStartupCheck();

    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) createMainWindow();
    });
  });
}
