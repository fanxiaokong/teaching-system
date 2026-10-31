'use strict';

/* 外壳渲染逻辑：顶栏（品牌 / 分类标签 / 搜索）、左侧图标栏、状态栏 */

(() => {
  const api = window.lc;
  const qs = new URLSearchParams(location.search);
  const MODE = qs.get('mode') === 'sub' ? 'sub' : 'main';
  const SUB_URL = qs.get('url') || '';

  /* macOS 端用系统原生左上角红绿灯，隐藏自绘窗口按钮、顶栏左侧让位。
     用 UA 判断而不是 process.platform：这里跑在渲染进程，拿不到 process。 */
  const IS_MAC = /macintosh|mac os x/i.test(navigator.userAgent || '');

  document.body.className =
    (MODE === 'sub' ? 'mode-sub' : 'mode-main') + (IS_MAC ? ' platform-mac' : '');

  const $ = (id) => document.getElementById(id);

  /* ------------------------------------------------------------ 图标 */

  const ICONS = {
    home: '<path d="M2.8 6.9L8 2.7l5.2 4.2v6.1a.5.5 0 0 1-.5.5h-3.2V9.7H6.5v3.8H3.3a.5.5 0 0 1-.5-.5z"/>',
    book: '<path d="M8 3.6C6.8 2.8 5.1 2.6 3 2.9v9.3c2.1-.3 3.8-.1 5 .7 1.2-.8 2.9-1 5-.7V2.9c-2.1-.3-3.8-.1-5 .7z"/><path d="M8 3.6v9.3"/>',
    flag: '<path d="M4 13.6V2.6"/><path d="M4 3.3h8.2l-1.7 2.5 1.7 2.5H4"/>',
    chat: '<path d="M2.6 7.6c0-2.6 2.4-4.6 5.4-4.6s5.4 2 5.4 4.6-2.4 4.6-5.4 4.6c-.6 0-1.2-.1-1.7-.2l-2.8 1.4.6-2A4.3 4.3 0 0 1 2.6 7.6z"/>',
    cloud: '<path d="M4.8 12.6h6.4a2.9 2.9 0 0 0 .3-5.8 3.6 3.6 0 0 0-6.9-.8A3 3 0 0 0 4.8 12.6z"/>',
    check: '<rect x="3.4" y="3.4" width="9.2" height="10.2" rx="1.5"/><path d="M6 2.4h4v2.2H6z"/><path d="M6.1 8.4l1.5 1.5 2.6-2.6"/>',
    user: '<circle cx="8" cy="5.6" r="2.6"/><path d="M3.4 13.2c0-2.5 2.1-4.1 4.6-4.1s4.6 1.6 4.6 4.1"/>',
    tools:
      '<path d="M14.7 6.3a1 1 0 0 0 0-1.4l-3.6-3.6a1 1 0 0 0-1.4 0l-1 1a1 1 0 0 0 0 1.4l3.6 3.6a1 1 0 0 0 1.4 0z"/><path d="M11.2 5.6l-8 8a1.5 1.5 0 0 0-.4.7l-.7 2.6 2.6-.7a1.5 1.5 0 0 0 .7-.4l8-8"/>',
    exam: '<rect x="2.6" y="2.8" width="10.8" height="10.4" rx="1.5"/><path d="M5.5 7.6l1.5 1.5 3.5-3.5"/>',
    server:
      '<rect x="2.6" y="3" width="10.8" height="4.1" rx="1.1"/><rect x="2.6" y="8.9" width="10.8" height="4.1" rx="1.1"/><path d="M5.1 5.05h.01M5.1 10.95h.01"/>',
    heart:
      '<path d="M8 13.6C3.2 10.2 1.9 8 1.9 6.1A3.1 3.1 0 0 1 8 4.4 3.1 3.1 0 0 1 14.1 6.1c0 1.9-1.3 4.1-6.1 7.5z"/>',
  };

  const svg = (name, size) =>
    '<svg width="' +
    (size || 16) +
    '" height="' +
    (size || 16) +
    '" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" ' +
    'stroke-linecap="round" stroke-linejoin="round">' +
    (ICONS[name] || '') +
    '</svg>';

  /* -------------------------------------------------------- 导航定义 */

  /* primary:true 的条目同时出现在顶部分类标签里（对应 bilibili 顶栏的分类 tab） */
  const NAV = [
    {
      label: '导航',
      items: [
        { id: 'home', label: '首页', path: '/', icon: 'home', primary: true },
        { id: 'courses', label: '课程资料', path: '/courses', icon: 'book', primary: true },
        { id: 'challenges', label: '挑战', path: '/challenges', icon: 'flag', primary: true },
        { id: 'community', label: '社区', path: '/community', icon: 'chat', primary: true },
        { id: 'drive', label: '云盘', path: '/drive', icon: 'cloud', primary: true },
        // 1.4.10 去掉「报到」——该功能已于 2026-10-16 整体下架，线上 /report 恒为 404
        { id: 'me', label: '我的', path: '/me', icon: 'user' },
      ],
    },
    {
      // 1.4.2 去掉「App 下载」，1.4.3 把「格式转换」并入工具箱页，
      // 1.4.9 去掉「健康饮食」——该功能 2026-10-05 整体下架，线上 /health 恒为 404。
      // 这一组现在只剩工具箱一个入口。
      label: '工具',
      items: [
        { id: 'tools', label: '工具箱', short: '工具箱', path: '/tools', icon: 'tools' },
      ],
    },
    {
      label: '实验室内部',
      items: [
        { id: 'kaoshi', label: '考试系统', short: '考试', url: 'https://exam.your-server.example.com', icon: 'exam' },
        { id: 'docker', label: 'Docker 面板', short: 'Docker', url: 'https://docker.your-server.example.com', icon: 'server' },
      ],
    },
  ];

  const PATH_ITEMS = [];
  NAV.forEach((g) => g.items.forEach((it) => { if (it.path) PATH_ITEMS.push(it); }));
  const PRIMARY = [];
  NAV.forEach((g) => g.items.forEach((it) => { if (it.primary) PRIMARY.push(it); }));

  /* 顶部分类标签 */
  function buildTabs() {
    const host = $('topTabs');
    if (!host) return;
    const frag = document.createDocumentFragment();
    PRIMARY.forEach((item) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'ab-tab';
      btn.dataset.id = item.id;
      btn.textContent = item.label;
      btn.title = item.label;
      btn.addEventListener('click', () => api.action('navigate', item.path));
      frag.appendChild(btn);
    });
    host.innerHTML = '';
    host.appendChild(frag);
  }

  /* 左侧图标栏 */
  function buildRail() {
    const host = $('sideNav');
    if (!host) return;
    const frag = document.createDocumentFragment();

    NAV.forEach((group, gi) => {
      if (gi > 0) {
        const sep = document.createElement('div');
        sep.className = 'rail-sep';
        frag.appendChild(sep);
      }
      group.items.forEach((item) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'rail-item';
        btn.dataset.id = item.id;
        btn.title = item.label + (item.url ? '（' + item.url.replace(/^https?:\/\//, '') + '）' : '');
        btn.innerHTML =
          '<span class="ic">' +
          svg(item.icon, 22) +
          '</span><span class="tx"></span>' +
          (item.url ? '<span class="ext">↗</span>' : '');
        btn.querySelector('.tx').textContent = item.short || item.label;

        btn.addEventListener('click', () => {
          if (item.url) api.action('openChild', { url: item.url, title: item.label });
          else api.action('navigate', item.path);
        });

        frag.appendChild(btn);
      });
    });

    host.innerHTML = '';
    host.appendChild(frag);
  }

  function matchItem(pathname) {
    let p = (pathname || '/').split('?')[0].split('#')[0];
    if (!p.startsWith('/')) p = '/' + p;
    if (p.length > 1 && p.endsWith('/')) p = p.slice(0, -1);
    if (p === '/' || p === '') return 'home';

    let best = null;
    PATH_ITEMS.forEach((it) => {
      if (it.path === '/' || it.path === p || p.startsWith(it.path + '/')) {
        if (!best || it.path.length > best.path.length) best = it;
      }
    });
    return best ? best.id : null;
  }

  function setActive(id) {
    document.querySelectorAll('.ab-tab').forEach((el) => {
      el.classList.toggle('on', el.dataset.id === id);
    });
    document.querySelectorAll('.rail-item').forEach((el) => {
      el.classList.toggle('on', el.dataset.id === id);
    });
  }

  /* ---------------------------------------------------------- 搜索框 */

  const SCOPE = {
    courses: { label: '课程', ph: '搜索课程' },
    files: { label: '资料', ph: '搜索资料' },
  };
  let scope = 'courses';

  function setupSearch() {
    const form = $('searchForm');
    const input = $('searchInput');
    const btn = $('searchScope');
    if (!form || !input) return;

    const sync = () => {
      const m = SCOPE[scope];
      if (btn) btn.textContent = m.label;
      input.placeholder = m.ph;
    };

    if (btn) {
      btn.addEventListener('click', () => {
        scope = scope === 'courses' ? 'files' : 'courses';
        sync();
        input.focus();
      });
    }

    form.addEventListener('submit', (ev) => {
      ev.preventDefault();
      const q = (input.value || '').trim();
      api.action('navigate', '/' + scope + (q ? '?q=' + encodeURIComponent(q) : ''));
    });

    sync();
  }

  /* -------------------------------------------------------- 工具栏 */

  const bind = (id, action, payload) => {
    const el = $(id);
    if (!el) return;
    el.addEventListener('click', () => api.action(action, payload));
    return el;
  };

  function platformLabel() {
    const ua = navigator.userAgent || '';
    if (/macintosh|mac os x/i.test(ua)) return 'macOS 客户端';
    if (/linux/i.test(ua) && !/android/i.test(ua)) return 'Linux 客户端';
    return 'Windows 客户端';
  }

  function setupChrome() {
    const sub = $('tbSub');
    if (sub) sub.textContent = MODE === 'sub' ? '子站窗口' : platformLabel();

    if (MODE === 'sub') {
      ['btnSidebar', 'navHome', 'btnAcct', 'btnUpdate'].forEach((id) => {
        const el = $(id);
        if (el) el.style.display = 'none';
      });
      const fh = $('footHost');
      if (fh) fh.textContent = SUB_URL.replace(/^https?:\/\//, '').split('/')[0] || '';
    }

    bind('navBack', 'back');
    bind('navFwd', 'forward');
    bind('navReload', 'reload');
    bind('navHome', 'home');
    // Windows 风格窗口按钮；macOS 端 shell.html 不渲染这几个元素，bind 会自动跳过
    bind('winMin', 'minimize');
    bind('winMax', 'toggleMaximize');
    bind('winClose', 'close');

    const side = $('btnSidebar');
    if (side) {
      side.addEventListener('click', () => {
        document.body.classList.toggle('sidebar-hidden');
        const hidden = document.body.classList.contains('sidebar-hidden');
        side.classList.toggle('on', !hidden);
        api.action('sidebar', hidden);
      });
    }

    const titlebar = $('titlebar');
    if (titlebar) titlebar.addEventListener('dblclick', () => api.action('toggleMaximize'));

    setupMenu();

    // 外壳按键：Alt+←/→ 导航，Alt+Home 回首页
    document.addEventListener('keydown', (ev) => {
      if (!ev.altKey) return;
      const k = ev.key;
      if (k === 'ArrowLeft') { ev.preventDefault(); api.action('back'); }
      else if (k === 'ArrowRight') { ev.preventDefault(); api.action('forward'); }
      else if (k === 'Home') { ev.preventDefault(); api.action('home'); }
    });
  }

  /* --------------------------------------------------- 原生弹出菜单 */

  /* 外壳画的浮层会被内容区原生视图盖住，所以 ☰ 与账户按钮交给系统原生菜单：
     这里只负责把按钮的落点坐标送过去，菜单内容由主进程构建。 */
  function popMenu(section) {
    const btn = section === 'account' ? $('btnAcct') : $('btnMenu');
    if (!btn) return;
    const r = btn.getBoundingClientRect();
    const m = $('btnMenu');
    if (m) {
      m.setAttribute('aria-expanded', 'true');
      m.classList.add('on');
    }
    const a = $('btnAcct');
    if (a) a.classList.add('open');
    api.action('menu', {
      section: section || 'main',
      x: Math.round(r.left),
      y: Math.round(r.bottom + 4),
    });
  }

  // 原生菜单关闭后没有回调，用窗口重获焦点来复位按钮的按下态
  window.addEventListener('focus', () => {
    const b = $('btnMenu');
    if (b) {
      b.classList.remove('on');
      b.setAttribute('aria-expanded', 'false');
    }
    const a = $('btnAcct');
    if (a) a.classList.remove('open');
  });

  function setupMenu() {
    const btnMenu = $('btnMenu');
    const btnAcct = $('btnAcct');
    if (btnMenu) btnMenu.addEventListener('click', (ev) => { ev.stopPropagation(); popMenu('main'); });
    if (btnAcct) btnAcct.addEventListener('click', (ev) => { ev.stopPropagation(); popMenu('account'); });
  }

  /* -------------------------------------------------------- 状态渲染 */

  const state = {
    loading: false,
    zoom: 0,
    lastTitle: '',
  };

  function zoomPct(level) {
    return Math.round(Math.pow(1.2, level || 0) * 100) + '%';
  }

  function pathLabel(pathname) {
    const id = matchItem(pathname);
    if (id && id !== 'home') {
      const hit = PATH_ITEMS.find((i) => i.id === id);
      if (hit) return hit.label;
    }
    return '首页';
  }

  /* 网页标题 → 副标题：剥掉站点名前后缀，过长则截断；与主标题重复时退回域名路径 */
  function docSub(doc, path, titleText) {
    let t = String(doc || '').replace(/\s+/g, ' ').trim();
    t = t
      .replace(/^教学管理系统\s*[·|\-–—]\s*/, '')
      .replace(/\s*[·|\-–—]\s*教学管理系统$/, '')
      .replace(/^教学管理系统$/, '')
      .trim();
    const fallback = 'your-server.example.com' + (path && path !== '/' ? path : '');
    if (!t || t === titleText) return fallback;
    return t.length > 52 ? t.slice(0, 52) + '…' : t;
  }

  function setProgress(mode) {
    const el = $('progress');
    if (!el) return;
    el.classList.remove('idle', 'done');
    if (mode === 'idle') el.classList.add('idle');
    else if (mode === 'done') {
      el.classList.add('done');
      setTimeout(() => el.classList.add('idle'), 520);
    }
  }

  function renderConn(state) {
    const el = $('conn');
    const txt = $('connText');
    const bar = $('statusbar');
    if (!el) return;
    el.classList.remove('ok', 'bad', 'load');
    if (bar) bar.classList.remove('bad', 'load');

    if (state.phase === 'loading') {
      el.classList.add('load');
      if (bar) bar.classList.add('load');
      if (txt) txt.textContent = '正在加载';
      const st = $('statusText');
      if (st) st.textContent = '正在打开页面…';
    } else if (state.phase === 'error') {
      el.classList.add('bad');
      if (bar) bar.classList.add('bad');
      if (txt) txt.textContent = '连接失败';
      const st = $('statusText');
      if (st) st.textContent = '无法连接到服务器';
    } else {
      el.classList.add('ok');
      if (txt) txt.textContent = '已连接';
      const st = $('statusText');
      if (st) st.textContent = '就绪';
    }
  }

  function applyView(state) {
    if (!state) return;

    if (typeof state.loading === 'boolean') {
      setProgress(state.loading ? 'run' : 'done');
    }
    if (typeof state.zoom === 'number') {
      const zl = $('zoomLabel');
      if (zl) zl.textContent = zoomPct(state.zoom);
    }

    const back = $('navBack');
    const fwd = $('navFwd');
    if (back) back.disabled = !state.canGoBack;
    if (fwd) fwd.disabled = !state.canGoForward;

    const pt = $('pageTitle');
    const ps = $('pageSub');

    if (state.phase === 'error') {
      if (pt) pt.textContent = '无法连接';
      if (ps) ps.textContent = 'your-server.example.com';
    } else if (state.path !== undefined) {
      setActive(matchItem(state.path));
      const label = pathLabel(state.path);
      if (pt) pt.textContent = label;
      if (ps) ps.textContent = docSub(state.docTitle, state.path, label);
    } else if (state.docTitle) {
      if (ps) ps.textContent = docSub(state.docTitle, '', '');
    }

    const su = $('statusUrl');
    if (state.url && su) su.textContent = state.url;

    renderConn(state);
  }

  function applyWindow(state) {
    const icon = $('winMaxIcon');
    const btn = $('winMax');
    if (!icon || !btn) return;
    if (state.maximized) {
      btn.title = '向下还原';
      icon.innerHTML =
        '<rect x="0.5" y="2.5" width="7" height="7" fill="none" stroke="currentColor" stroke-width="1"/>' +
        '<path d="M2.5 2.5V0.5h7v7h-2" fill="none" stroke="currentColor" stroke-width="1"/>';
    } else {
      btn.title = '最大化';
      icon.innerHTML =
        '<rect x="0.5" y="0.5" width="9" height="9" fill="none" stroke="currentColor" stroke-width="1"/>';
    }
  }

  function applyDownload(state) {
    const el = $('dlInfo');
    if (!el) return;
    if (!state || !state.active) {
      el.textContent = '';
      return;
    }
    el.textContent = '↓ ' + (state.name || '文件') + ' ' + (state.percent || 0) + '%';
  }

  const acct = { loggedIn: false, name: '' };

  function renderAcctButton() {
    const btn = $('btnAcct');
    if (!btn) return;
    const av = $('acctAv');
    const nm = $('acctName');
    const n = (acct.name || '').trim();
    if (acct.loggedIn) {
      btn.classList.add('in');
      if (av) av.textContent = (n || '?').charAt(0).toUpperCase();
      if (nm) nm.textContent = n || '已登录';
      btn.title = '账户：' + n;
    } else {
      btn.classList.remove('in');
      if (av) av.textContent = '?';
      if (nm) nm.textContent = '未登录';
      btn.title = '登录 / 注册';
    }
  }

  function applyAccount(state) {
    if (!state) return;
    acct.loggedIn = Boolean(state.loggedIn);
    acct.name = state.name || '';

    // 图标栏底部：空间窄，只放短状态
    const el = $('footAcct');
    if (el) {
      if (acct.loggedIn) {
        el.textContent = acct.name || '已登录';
        el.title = '已登录：' + (acct.name || '');
      } else {
        el.textContent = '未登录';
        el.title = '会话状态：未登录';
      }
    }

    renderAcctButton();
  }

  /* ------------------------------------------------------ 软件更新 */

  /* 工具栏徽标 + 状态栏进度：真正的更新界面是独立的模态对话框，
     外壳只显示「有新版本 / 正在下载 / 可以安装」这层提示。 */
  function applyUpdate(state) {
    if (!state) return;
    const btn = $('btnUpdate');
    const txt = $('updText');
    const dot = $('updDot');
    const info = $('updInfo');
    if (!btn) return;

    const ver = state.latest ? state.latest.versionName : '';
    let label = '';
    let tip = '';
    let badge = false;
    let accent = false;

    switch (state.phase) {
      case 'checking':
        label = '检查中';
        tip = '正在检查更新…';
        break;
      case 'available':
        label = '新版本 v' + ver;
        tip = '发现新版本 v' + ver + '，点击查看更新内容';
        badge = !state.skipped;
        accent = true;
        break;
      case 'downloading':
        label = (state.percent || 0) + '%';
        tip = '正在下载更新包 ' + (state.percent || 0) + '%';
        badge = true;
        accent = true;
        break;
      case 'ready':
        label = '可安装';
        tip = '更新包 v' + ver + ' 已下载完成，点击安装';
        badge = true;
        accent = true;
        break;
      case 'installing':
        label = '安装中';
        tip = '正在安装更新，客户端即将重启';
        accent = true;
        break;
      case 'error':
        label = '更新失败';
        tip = state.message || '更新失败，点击重试';
        break;
      default:
        label = '';
        tip = '软件更新';
    }

    btn.hidden = !label;
    if (txt) txt.textContent = label;
    btn.title = tip;
    btn.classList.toggle('upd-on', accent);
    if (dot) dot.hidden = !badge;

    if (info) {
      if (state.phase === 'downloading') {
        info.textContent = '更新 ' + (state.percent || 0) + '%';
      } else if (state.phase === 'ready') {
        info.textContent = '待安装 v' + ver;
      } else if (state.phase === 'available' && !state.skipped) {
        info.textContent = '可更新 v' + ver;
      } else {
        info.textContent = '';
      }
    }
  }

  /* ------------------------------------------------------------ 启动 */

  function boot() {
    setupChrome();
    renderAcctButton();
    if (MODE === 'main') {
      buildTabs();
      buildRail();
      setActive('home');
    }
    setupSearch();
    const fh = $('footHost');
    if (fh) fh.textContent = 'your-server.example.com';
    setProgress('run');
  }

  if (!api) {
    boot();
    return;
  }

  api.onViewState(applyView);
  api.onWindowState(applyWindow);
  api.onDownloadState(applyDownload);
  api.onAccountState(applyAccount);
  api.onUpdateState(applyUpdate);
  api.onBoot((b) => {
    if (b && b.appVersion) {
      const fv = $('footVer');
      if (fv) fv.textContent = 'v' + b.appVersion;
      const side = $('btnSidebar');
      if (side && MODE === 'main') {
        const hidden = b.sidebar === false;
        document.body.classList.toggle('sidebar-hidden', hidden);
        side.classList.toggle('on', !hidden);
      }
      if (b.sidebarWidth) {
        document.documentElement.style.setProperty('--rail-w', b.sidebarWidth + 'px');
      }
    }
  });

  boot();
})();
