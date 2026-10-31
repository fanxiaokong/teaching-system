'use strict';

/**
 * 软件更新对话框（独立无边框模态窗口）的渲染逻辑。
 *
 * 数据单向来自主进程：updater 每次状态变化都会推送 lc:update-state，
 * 这里只管把状态画成界面，用户点击统一走 lc.action(...) 交回主进程。
 */

(() => {
  const api = window.lc;
  const $ = (id) => document.getElementById(id);

  /* ---------------------------------------------------------- 图标 */

  const ICON = {
    check:
      '<path d="M8 1.9a6.1 6.1 0 1 0 0 12.2A6.1 6.1 0 0 0 8 1.9z"/><path d="M5.3 8.2l1.9 1.9 3.5-3.6"/>',
    download:
      '<path d="M8 2.2v7.4"/><path d="M4.8 6.6L8 9.8l3.2-3.2"/><path d="M2.6 13.2h10.8"/>',
    spin: '<path d="M8 2.2v2.6" /><path d="M8 11.2v2.6"/><path d="M2.2 8h2.6"/><path d="M11.2 8h2.6"/>',
    info:
      '<circle cx="8" cy="8" r="6.1"/><path d="M8 7.3v4"/><path d="M8 4.7h.01"/>',
    warn:
      '<path d="M8 2.4l5.6 10.1H2.4z"/><path d="M8 6.6v3.1"/><path d="M8 11.2h.01"/>',
    rocket:
      '<path d="M8 1.9c2.2 1.5 3.4 4 3.4 7l-3.4 3.1-3.4-3.1c0-3 1.2-5.5 3.4-7z"/><circle cx="8" cy="6.4" r="1.2"/>',
  };

  const svg = (name, size, cls) =>
    '<svg class="' + (cls || '') + '" width="' + (size || 20) + '" height="' + (size || 20) +
    '" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" ' +
    'stroke-linecap="round" stroke-linejoin="round">' + (ICON[name] || '') + '</svg>';

  /* --------------------------------------------------------- 工具 */

  function fmtSize(bytes) {
    const n = Number(bytes) || 0;
    if (n >= 1073741824) return (n / 1073741824).toFixed(2) + ' GB';
    if (n >= 1048576) return (n / 1048576).toFixed(1) + ' MB';
    if (n >= 1024) return (n / 1024).toFixed(0) + ' KB';
    return n + ' B';
  }

  function fmtSpeed(bytesPerSec) {
    const n = Number(bytesPerSec) || 0;
    if (n <= 0) return '';
    if (n >= 1048576) return (n / 1048576).toFixed(1) + ' MB/s';
    if (n >= 1024) return (n / 1024).toFixed(0) + ' KB/s';
    return n + ' B/s';
  }

  function chip(html) {
    const s = document.createElement('span');
    s.className = 'chip';
    s.innerHTML = html;
    return s;
  }

  function button(label, opts) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'btn' + (opts && opts.primary ? ' primary' : '') + (opts && opts.link ? ' link' : '');
    b.textContent = label;
    if (opts && opts.disabled) b.disabled = true;
    if (opts && opts.act) {
      b.addEventListener('click', () => api.action(opts.act));
    }
    return b;
  }

  /* --------------------------------------------------------- 渲染 */

  const HERO = {
    checking: { ic: 'spin', cls: 'wait spin', title: '正在检查更新…', sub: '正在连接服务器获取最新版本信息。' },
    latest: { ic: 'check', cls: 'ok', title: '已是最新版本', sub: '' },
    available: { ic: 'download', cls: '', title: '发现新版本', sub: '建议立即更新以获得最新功能与修复。' },
    downloading: { ic: 'download', cls: '', title: '正在下载更新包', sub: '下载期间请保持网络畅通，可随时取消。' },
    ready: { ic: 'rocket', cls: 'ok', title: '更新包已准备就绪', sub: '安装过程约需数十秒，客户端会自动重启。' },
    installing: { ic: 'spin', cls: 'wait', title: '正在启动安装程序', sub: '' },
    unsupported: { ic: 'info', cls: 'bad', title: '当前副本无法自动升级', sub: '' },
    error: { ic: 'warn', cls: 'bad', title: '更新遇到问题', sub: '' },
  };

  function renderHero(st) {
    let key = st.phase;
    if (st.phase === 'idle') key = 'checking';
    const conf = HERO[key] || HERO.checking;

    $('heroIc').className = 'hero-ic ' + (conf.cls || '');
    $('heroIc').innerHTML = svg(conf.ic, 22, conf.ic === 'spin' ? 'spin' : '');

    $('heroTitle').textContent =
      key === 'available' && st.latest ? '发现新版本 v' + st.latest.versionName : conf.title;

    let sub = conf.sub;
    if (key === 'latest') sub = '当前版本 v' + st.current + ' 已是线上最新版本，无需更新。';
    if (key === 'error') sub = st.message || '请稍后重试，或前往下载页手动下载。';
    if (key === 'unsupported') {
      sub =
        '当前客户端不是从安装目录或绿色版启动的（例如直接运行打包中间产物、或随手复制的副本）。' +
        '自动升级只会把新版本装成另一份，你启动的这个文件永远不会变。' +
        '到下载页重新安装一次即可恢复正常升级。';
    }
    if (key === 'installing') {
      sub = st.portable
        ? '正在把新版本替换到程序目录，客户端即将自动重启…'
        : st.message || '正在静默升级，装好后客户端会自动重启。';
    }
    $('heroSub').textContent = sub;
  }

  function renderVers(st) {
    const box = $('versBox');
    const hasNew = Boolean(st.latest && st.latest.versionName);
    box.hidden = !hasNew || !['available', 'downloading', 'ready'].includes(st.phase);
    if (box.hidden) return;
    $('vCur').textContent = 'v' + st.current;
    $('vNew').textContent = 'v' + st.latest.versionName;
  }

  function renderMeta(st) {
    const box = $('metaBox');
    box.innerHTML = '';
    if (!st.latest || !['available', 'downloading', 'ready'].includes(st.phase)) return;

    const L = st.latest;
    box.appendChild(chip('渠道 <b>' + (st.portable ? '绿色版（免安装）' : '安装版') + '</b>'));
    if (L.size) box.appendChild(chip('安装包 <b>' + fmtSize(L.size) + '</b>'));
    if (L.publishedAt) box.appendChild(chip('发布于 <b>' + L.publishedAt + '</b>'));
    if (L.sha512) box.appendChild(chip('SHA-512 <b>' + L.sha512.slice(0, 12) + '…</b>'));
    if (st.skipped) box.appendChild(chip('该版本已被忽略'));
  }

  function renderNotes(st) {
    const wrap = $('notesWrap');
    const show = Boolean(st.latest) && ['available', 'downloading', 'ready'].includes(st.phase);
    wrap.hidden = !show;
    if (!show) return;
    $('notesBox').textContent = (st.latest.notes || '').trim();
    $('notesBox').scrollTop = 0;
  }

  function renderProg(st) {
    const box = $('progBox');
    if (st.phase !== 'downloading') {
      box.hidden = true;
      return;
    }
    box.hidden = false;
    const bar = box.querySelector('.bar');
    const pct = Math.max(0, Math.min(100, Number(st.percent) || 0));
    if (st.total > 0) {
      bar.classList.remove('indet');
      $('barFill').style.width = pct + '%';
      $('progPct').textContent = pct + '%';
    } else {
      bar.classList.add('indet');
      $('progPct').textContent = '下载中';
    }
    const parts = [];
    if (st.total > 0) parts.push(fmtSize(st.received) + ' / ' + fmtSize(st.total));
    else if (st.received) parts.push('已下载 ' + fmtSize(st.received));
    const speed = fmtSpeed(st.speed);
    if (speed) parts.push(speed);
    $('progDetail').textContent = parts.join(' · ');
  }

  function renderMsg(st) {
    const box = $('msgBox');
    let text = '';
    let cls = '';
    if (st.devMode && st.phase === 'error') {
      text = st.message || '';
    } else if (st.phase === 'error') {
      text = '';  // 错误已呈现在标题区，这里不再重复
    } else if (st.phase === 'available' && st.skipped) {
      text = '你之前选择了「跳过此版本」。仍可点击「立即更新」进行升级。';
      cls = 'warn';
    } else if (st.phase === 'ready' && st.portable) {
      text = '绿色版将把新版本写入当前程序所在目录；若目录无写入权限，请改用手动下载。';
      cls = 'warn';
    }
    box.hidden = !text;
    box.className = 'msg ' + cls;
    box.textContent = text;
  }

  function renderFoot(st) {
    const foot = $('dlgFoot');
    foot.innerHTML = '';

    const phase = st.phase;
    if (phase === 'checking' || phase === 'idle') {
      foot.appendChild(button('在后台检查', { act: 'updateLater' }));
      return;
    }
    if (phase === 'latest') {
      foot.appendChild(button('确定', { primary: true, act: 'updateLater' }));
      return;
    }
    if (phase === 'available') {
      foot.appendChild(button('打开下载页', { link: true, act: 'updateOpenPage' }));
      const grow = document.createElement('span');
      grow.className = 'grow';
      foot.appendChild(grow);
      if (!st.skipped) foot.appendChild(button('跳过此版本', { act: 'updateSkip' }));
      foot.appendChild(button('稍后提醒', { act: 'updateLater' }));
      foot.appendChild(button('立即更新', { primary: true, act: 'updateDownload' }));
      return;
    }
    if (phase === 'downloading') {
      foot.appendChild(button('取消下载', { act: 'updateCancel' }));
      return;
    }
    if (phase === 'ready') {
      foot.appendChild(button('打开所在文件夹', { link: true, act: 'updateOpenFolder' }));
      const grow = document.createElement('span');
      grow.className = 'grow';
      foot.appendChild(grow);
      foot.appendChild(button('稍后安装', { act: 'updateLater' }));
      foot.appendChild(button('立即安装并重启', { primary: true, act: 'updateInstall' }));
      return;
    }
    if (phase === 'installing') {
      foot.appendChild(button('正在安装…', { disabled: true }));
      return;
    }
    if (phase === 'unsupported') {
      const grow = document.createElement('span');
      grow.className = 'grow';
      foot.appendChild(grow);
      foot.appendChild(button('稍后提醒', { act: 'updateLater' }));
      foot.appendChild(button('前往下载页', { primary: true, act: 'updateOpenPage' }));
      return;
    }
    // error
    foot.appendChild(button('打开下载页', { link: true, act: 'updateOpenPage' }));
    const grow = document.createElement('span');
    grow.className = 'grow';
    foot.appendChild(grow);
    foot.appendChild(button('关闭', { act: 'updateLater' }));
    foot.appendChild(
      button(st.latest ? '重新下载' : '重试', { primary: true, act: st.latest ? 'updateDownload' : 'updateCheck' })
    );
  }

  function render(st) {
    if (!st) return;
    document.body.className = 'phase-' + (st.phase || 'idle');
    renderHero(st);
    renderVers(st);
    renderMeta(st);
    renderNotes(st);
    renderProg(st);
    renderMsg(st);
    renderFoot(st);
  }

  /* --------------------------------------------------------- 启动 */

  $('btnClose').addEventListener('click', () => api.action('updateLater'));

  document.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape') {
      ev.preventDefault();
      api.action('updateLater');
    }
  });

  // 当前阶段按钮在安装中不可点，避免误触关闭
  render({ phase: 'checking', current: '' });

  if (api && api.onUpdateState) {
    api.onUpdateState(render);
    api.action('updateReady');
  }
})();
