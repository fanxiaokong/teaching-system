'use strict';

/**
 * OTA 在线升级（检查 → 下载 → 校验 → 安装重启）
 *
 * 版本来源：站点 /api/v1/app/version?platform=mac
 *   macOS 版统一跑 platform=mac（无安装版 / 绿色版之分）。
 *
 * 安装方式：
 *   - 安装版：静默原地升级（pkg /S /currentuser，装回注册表里记录的安装目录），装完自动拉起新版
 *   - 绿色版：把新 exe 原地替换掉当前绿色版文件，再重新启动
 *   两者都需要先让当前进程退出，所以安装动作交给一个 PowerShell 辅助进程：
 *   它先写「已启动」凭据 → 等本进程 PID 消失 → 执行安装/替换 → 重新拉起客户端。
 *   主进程必须等到凭据才退出（见 install()），否则会出现「自己关了但没升级」。
 *
 * 为什么用 -EncodedCommand：脚本与路径里都可能有中文，
 * 直接写在命令行上会被控制台代码页弄乱，base64(UTF-16LE) 完全避开编码问题。
 */

const { app, net, shell } = require('electron');
const path = require('path');
const fs = require('fs');
const crypto = require('crypto');
const {
  installerScript,
  portableScript,
  runHiddenPowerShell,
} = require('./update-scripts');

const SITE_ORIGIN = 'https://your-server.example.com';
const CHECK_INTERVAL_MS = 6 * 60 * 60 * 1000; // 运行期间每 6 小时自动查一次
const STARTUP_DELAY_MS = 8000;                // 启动后延迟检查，不打扰首屏
const UPDATE_DIR = () => path.join(app.getPath('userData'), 'updates');

/* ------------------------------------------------------------------ *
 * 版本号
 * ------------------------------------------------------------------ */

/** "1.3.0" -> 1003000，与服务端 db.semver_code 保持同一套编码 */
function semverCode(name) {
  const text = String(name || '').trim().replace(/^v/i, '');
  if (!text) return 0;
  const parts = [];
  for (const chunk of text.split('.')) {
    let digits = '';
    for (const ch of chunk) {
      if (ch >= '0' && ch <= '9') digits += ch;
      else break;
    }
    if (!digits) break;
    parts.push(parseInt(digits, 10));
  }
  while (parts.length < 3) parts.push(0);
  const [major, minor, patch] = parts;
  if (minor > 999 || patch > 999) return 0;
  return major * 1000000 + minor * 1000 + patch;
}

/** 语义化比较：a > b 返回正数，相等 0，小于为负。解析失败退回 0。 */
function compareSemver(a, b) {
  const na = semverCode(a);
  const nb = semverCode(b);
  if (na > 0 && nb > 0) return na - nb;
  const sa = String(a || '').split('.').map((x) => parseInt(x, 10) || 0);
  const sb = String(b || '').split('.').map((x) => parseInt(x, 10) || 0);
  for (let i = 0; i < 3; i += 1) {
    const d = (sa[i] || 0) - (sb[i] || 0);
    if (d) return d;
  }
  return 0;
}

function fmtSize(bytes) {
  const n = Number(bytes) || 0;
  if (n >= 1073741824) return (n / 1073741824).toFixed(2) + ' GB';
  if (n >= 1048576) return (n / 1048576).toFixed(1) + ' MB';
  if (n >= 1024) return (n / 1024).toFixed(0) + ' KB';
  return n + ' B';
}

/* ------------------------------------------------------------------ *
 * HTTP（走 Electron net，继承系统代理设置）
 * ------------------------------------------------------------------ */

function netGetJson(url, timeoutMs) {
  return new Promise((resolve, reject) => {
    let req;
    try {
      req = net.request({ method: 'GET', url, redirect: 'follow' });
    } catch (err) {
      reject(err);
      return;
    }
    const chunks = [];
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      try { req.abort(); } catch (err) { /* ignore */ }
      reject(new Error('请求超时'));
    }, timeoutMs || 20000);
    const done = (err, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (err) reject(err);
      else resolve(value);
    };
    req.setHeader('Cache-Control', 'no-cache');
    req.setHeader('Pragma', 'no-cache');
    req.setHeader('Accept', 'application/json');
    req.on('response', (res) => {
      if (res.statusCode !== 200) {
        try { res.resume(); } catch (err) { /* ignore */ }
        done(new Error('服务器返回 HTTP ' + res.statusCode));
        return;
      }
      res.on('data', (chunk) => chunks.push(chunk));
      res.on('end', () => {
        try {
          done(null, JSON.parse(Buffer.concat(chunks).toString('utf8')));
        } catch (err) {
          done(new Error('服务器返回内容无法解析'));
        }
      });
      res.on('error', (err) => done(err));
    });
    req.on('error', (err) => done(err));
    req.end();
  });
}

/* ------------------------------------------------------------------ *
 * 模块状态
 * ------------------------------------------------------------------ */

let host = null; // { emit, notify, getSettings, patchSettings, isQuitting }
let timer = null;
let activeRequest = null; // 下载中的 net 请求

const st = {
  phase: 'idle',      // idle | checking | latest | available | downloading | ready | installing | error
  dialog: false,      // 是否要求外壳弹出「软件更新」窗口
  manual: false,      // 是否由用户手动触发（手动检查「已是最新」也要给回执）
  current: '',
  channel: 'mac',
  portable: false,
  latest: null,       // { versionName, versionCode, notes, size, url, publishedAt, fileName }
  file: '',           // 下载到本地的安装包路径
  percent: 0,
  received: 0,
  total: 0,
  speed: 0,
  message: '',
  skipped: false,
  installed: false,   // 已发起安装（外壳显示「正在安装」）
  devMode: false,
};

function snapshot() {
  return {
    phase: st.phase,
    dialog: st.dialog,
    manual: st.manual,
    current: st.current,
    channel: st.channel,
    portable: st.portable,
    installed: st.installed,
    canAutoUpdate: st.canAutoUpdate,
    latest: st.latest,
    percent: st.percent,
    received: st.received,
    total: st.total,
    speed: st.speed,
    message: st.message,
    skipped: st.skipped,
    devMode: st.devMode,
    file: st.file ? path.basename(st.file) : '',
  };
}

function push() {
  if (host && host.emit) host.emit(snapshot());
}

function setProgress(win, value) {
  try {
    if (win && !win.isDestroyed()) win.setProgressBar(value);
  } catch (err) {
    /* ignore */
  }
}

/* ------------------------------------------------------------------ *
 * 初始化
 * ------------------------------------------------------------------ */

/**
 * 清理已经用不上的安装包：文件版本号 ≤ 当前运行版本的都没必要留着
 * （升级成功后旧包就是这一档；比当前版本新的包说明还没装，继续保留）。
 */
function cleanStalePackages() {
  try {
    const dir = UPDATE_DIR();
    if (!fs.existsSync(dir)) return;
    const local = semverCode(st.current);
    for (const name of fs.readdirSync(dir)) {
      if (!/\.(dmg|zip|pkg)$/i.test(name)) continue;
      const m = name.match(/v(\d+(?:\.\d+)*)/i);
      const code = m ? semverCode(m[1]) : 0;
      if (code > 0 && local > 0 && code > local) continue;
      try {
        fs.unlinkSync(path.join(dir, name));
      } catch (err) {
        /* 文件被占用（正等着安装）就留着，下次启动再清 */
      }
    }
  } catch (err) {
    /* ignore */
  }
}

function init(options) {
  host = options || {};
  const settings = host.getSettings ? host.getSettings() : {};
  st.current = app.getVersion();
  st.portable = false; // macOS 无绿色版概念
  st.channel = 'mac';
  st.devMode = !app.isPackaged;

  /*
   * 判断「当前这个副本」到底能不能被自动升级。
   *
   * Windows 端：必须确认 exe 真的处在安装位置（旁边有卸载器，或带
   * PORTABLE_EXECUTABLE_FILE），否则下载的安装包只会装到标准目录、
   * 当前副本一个字节不变，表现为「升级成功却还是旧版」。
   *
   * macOS 端：没有 NSIS 卸载器这一套，App 默认就在 /Applications 里。
   * 受限于 Gatekeeper/签名，无法像 Windows 那样静默原地替换，
   * 因此采用「下载安装包 → 打开（dmg 挂载 / zip 解压）→ 退出客户端，
   * 由用户在 Finder 里把新 App 拖进「应用程序」」的方式。只要能下载、
   * 能打开就算具备升级条件，所以恒为 true。
   */
  if (process.platform === 'win32') {
    const exeDir = path.dirname(app.getPath('exe'));
    let hasUninstaller = false;
    try {
      hasUninstaller = fs.readdirSync(exeDir).some((n) => /^Uninstall\b.*\.exe$/i.test(n));
    } catch (err) {
      /* 目录读不了就当没有 */
    }
    st.installed = hasUninstaller;
    st.canAutoUpdate = st.portable || hasUninstaller;
  } else {
    st.installed = true;
    st.canAutoUpdate = true;
  }

  cleanStalePackages();

  if (timer) clearInterval(timer);
  timer = setInterval(() => {
    const s = host.getSettings ? host.getSettings() : {};
    if (s.autoCheckUpdate !== false) check({ manual: false });
  }, CHECK_INTERVAL_MS);
  if (timer.unref) timer.unref();

  void settings;
}

function scheduleStartupCheck() {
  setTimeout(() => {
    const s = host && host.getSettings ? host.getSettings() : {};
    if (s.autoCheckUpdate === false) return;
    check({ manual: false });
  }, STARTUP_DELAY_MS);
}

/**
 * 用户主动唤出更新窗口（工具栏徽标 / 菜单）：
 * 已知新版本或正处于更新流程中 → 直接把弹窗亮出来，不重新发请求；
 * 否则当成一次手动检查。
 */
function show() {
  const live = ['checking', 'available', 'downloading', 'ready', 'installing', 'error'];
  if (st.latest || live.includes(st.phase)) {
    if (st.phase === 'checking') st.manual = true;
    st.dialog = true;
    if (!st.message || st.phase === 'available') st.message = '';
    push();
    return snapshot();
  }
  return check({ manual: true });
}

/* ------------------------------------------------------------------ *
 * 检查更新
 * ------------------------------------------------------------------ */

function buildUrl() {
  return (
    SITE_ORIGIN +
    '/api/v1/app/version?platform=' + encodeURIComponent(st.channel) +
    '&version_code=' + semverCode(st.current) +
    '&_=' + Date.now()
  );
}

async function check(options) {
  const manual = Boolean(options && options.manual);
  if (st.phase === 'downloading' || st.phase === 'installing') {
    if (manual) {
      st.manual = true;
      st.message = '正在更新中，请稍候…';
      st.dialog = true;
      push();
    }
    return snapshot();
  }

  if (!st.canAutoUpdate) {
    // 当前副本不具备自动升级条件：直接说清楚，别去下安装包「装到别处」
    st.manual = manual;
    st.skipped = false;
    st.phase = 'unsupported';
    st.message = '';
    st.dialog = manual;
    push();
    return snapshot();
  }

  st.manual = manual;
  st.phase = 'checking';
  st.message = '';
  st.dialog = manual;
  push();

  let payload;
  try {
    payload = await netGetJson(buildUrl(), 20000);
  } catch (err) {
    st.phase = 'error';
    st.message = '檢查更新失败：' + (err && err.message ? err.message : '网络不可用');
    st.dialog = manual;
    push();
    return snapshot();
  }

  const data = (payload && payload.data) || null;
  const hasUpdate = Boolean(payload && payload.ok && data && data.has_update && data.download_url);

  if (!hasUpdate) {
    st.phase = 'latest';
    st.latest = null;
    st.message = '当前已是最新版本 v' + st.current;
    st.dialog = manual;
    push();
    return snapshot();
  }

  const latestCode = Number(data.version_code) || 0;
  const localCode = semverCode(st.current);
  const newer =
    compareSemver(data.version_name, st.current) > 0 || (latestCode > 0 && latestCode > localCode);

  if (!newer) {
    // 服务端标记的「最新版」不比本地新（例如本机装了比线上更新的测试版）
    st.phase = 'latest';
    st.latest = null;
    st.message = '当前已是最新版本 v' + st.current;
    st.dialog = manual;
    push();
    return snapshot();
  }

  st.latest = {
    versionName: String(data.version_name || ''),
    versionCode: latestCode,
    notes: String(data.release_notes || ''),
    size: Number(data.file_size) || 0,
    sizeText: fmtSize(data.file_size),
    publishedAt: String(data.published_at || ''),
    fileName: String(data.file_name || ''),
    url: resolveUrl(data.download_url),
    sha512: String(data.sha512 || '').trim(),
  };

  const settings = host && host.getSettings ? host.getSettings() : {};
  st.skipped = Boolean(settings.skippedVersion) && settings.skippedVersion === st.latest.versionName;
  st.phase = 'available';
  st.message = '';
  // 自动检查不打断使用：只亮工具栏徽标 + 发系统通知，用户点了才弹更新窗口
  st.dialog = manual;
  push();

  if (!manual && !st.skipped && host && host.notify) {
    host.notify('发现新版本 v' + st.latest.versionName, '点击查看更新内容并升级', () => {
      st.dialog = true;
      push();
    });
  }
  return snapshot();
}

function resolveUrl(raw) {
  const text = String(raw || '').trim();
  if (/^https?:\/\//i.test(text)) return text;
  if (!text) return '';
  return SITE_ORIGIN + (text.startsWith('/') ? text : '/' + text);
}

/* ------------------------------------------------------------------ *
 * 下载
 * ------------------------------------------------------------------ */

function targetPath(info) {
  const dir = UPDATE_DIR();
  fs.mkdirSync(dir, { recursive: true });
  // 按服务端下发的下载地址推断扩展名（dmg / zip / pkg），缺省 dmg
  const m = String((info && info.url) || '').split('?')[0].match(/\.(dmg|zip|pkg)$/i);
  const ext = m ? m[1].toLowerCase() : 'dmg';
  return path.join(dir, 'teaching-system-mac-v' + info.versionName + '.' + ext);
}

function clearDownloads() {
  try {
    const dir = UPDATE_DIR();
    if (!fs.existsSync(dir)) return;
    for (const name of fs.readdirSync(dir)) {
      try { fs.unlinkSync(path.join(dir, name)); } catch (err) { /* ignore */ }
    }
  } catch (err) {
    /* ignore */
  }
}

/**
 * 解析服务端下发的 SHA-512 校验值。
 *
 * 坑：base64 是大小写敏感的，绝不能先 toLowerCase 再比较 —— 一旦把 base64 小写化，
 * 校验必然失败（表现为「文件明明完整下载了，却提示 SHA-512 校验未通过」）。
 * 这里两种格式都接受：128 位十六进制忽略大小写，base64 按原样比较。
 * 站点后台与 tools/publish_app.py 都以 hex 存库，base64 只是兼容兜底。
 */
function expectedSha512(raw) {
  const text = String(raw || '').trim();
  if (!text) return null;
  if (/^[0-9a-fA-F]{128}$/.test(text)) return { kind: 'hex', value: text.toLowerCase() };
  if (/^[A-Za-z0-9+/]{86}==$/.test(text)) return { kind: 'base64', value: text };
  return null;
}

function startDownload() {
  if (!st.latest || !st.latest.url) {
    return Promise.resolve(snapshot());
  }
  if (st.phase === 'downloading') return Promise.resolve(snapshot());

  if (!st.canAutoUpdate) {
    // 兜底：万一有人绕过界面直接触发下载，也不要在这种副本上装
    openDownloadPage();
    return Promise.resolve(snapshot());
  }

  if (st.devMode) {
    st.phase = 'error';
    st.dialog = true;
    st.message = '开发模式下不执行下载与安装，请使用打包后的客户端。';
    push();
    return Promise.resolve(snapshot());
  }

  const info = st.latest;
  const dest = targetPath(info);
  const part = dest + '.part';

  try {
    if (fs.existsSync(dest)) fs.unlinkSync(dest);
    if (fs.existsSync(part)) fs.unlinkSync(part);
  } catch (err) {
    /* ignore */
  }

  st.phase = 'downloading';
  st.dialog = true;
  st.percent = 0;
  st.received = 0;
  st.total = info.size || 0;
  st.speed = 0;
  st.message = '';
  st.file = '';
  push();

  return new Promise((resolve) => {
    const out = fs.createWriteStream(part);
    const hash = crypto.createHash('sha512');
    const win = () => (host && host.getWindow ? host.getWindow() : null);

    let req = null;
    let received = 0;
    let total = info.size || 0;
    let lastTick = Date.now();
    let lastBytes = 0;
    let stage = 'stream'; // stream | flushing | done
    let idleTimer = null;
    let flushTimer = null;

    /** 失败收尾：中断请求、删掉半成品、把错误暴露到界面 */
    const fail = (message) => {
      if (stage === 'done') return;
      stage = 'done';
      clearTimeout(idleTimer);
      clearTimeout(flushTimer);
      activeRequest = null;
      try { if (req) req.abort(); } catch (err) { /* ignore */ }
      try { out.destroy(); } catch (err) { /* ignore */ }
      try { if (fs.existsSync(part)) fs.unlinkSync(part); } catch (err) { /* ignore */ }
      setProgress(win(), -1);
      st.phase = 'error';
      st.dialog = true;
      st.message = message;
      st.percent = 0;
      st.speed = 0;
      st.file = '';
      push();
      resolve(snapshot());
    };

    /** 空闲看门狗：长时间收不到新数据就报错，避免界面永远停在「下载中」 */
    const armIdle = () => {
      clearTimeout(idleTimer);
      idleTimer = setTimeout(() => {
        if (stage !== 'stream') return;
        fail('下载超时（已收到 ' + fmtSize(received) + (total ? ' / ' + fmtSize(total) : '') + '）');
      }, 45000);
    };

    /**
     * 数据收齐后的收尾：等写流落盘 → 校验字节数与 SHA-512 → 改名成正式安装包。
     *
     * 关键经验：Electron 的 net 流有时不派发 end 事件（实测 78MB 的包已经完整落盘，
     * 界面却卡在「下载中」）。所以完成判定不依赖 end，而是以「已收字节数 ≥ 声明的
     * Content-Length」为准，再核对磁盘上的真实大小。
     */
    const finalize = () => {
      if (stage !== 'stream') return;
      stage = 'flushing';
      clearTimeout(idleTimer);
      activeRequest = null;
      setProgress(win(), 1);

      let closed = false;
      const complete = () => {
        if (closed) return;
        closed = true;
        clearTimeout(flushTimer);

        let onDisk = 0;
        try { onDisk = fs.statSync(part).size; } catch (err) { onDisk = 0; }
        if (total && onDisk !== total) {
          fail('下载文件大小与服务器不一致（磁盘 ' + fmtSize(onDisk) + ' / 服务器 ' + fmtSize(total) + '）');
          return;
        }

        const hex = hash.digest('hex');
        const expect = expectedSha512(info.sha512);
        if (expect) {
          const base64 = Buffer.from(hex, 'hex').toString('base64');
          const actual = expect.kind === 'hex' ? hex : base64;
          if (actual !== expect.value) {
            fail('安装包 SHA-512 校验未通过，文件已丢弃，请重试。');
            return;
          }
        }

        try {
          fs.renameSync(part, dest);
        } catch (err) {
          fail('无法保存安装包：' + err.message);
          return;
        }

        stage = 'done';
        st.file = dest;
        st.phase = 'ready';
        st.percent = 100;
        st.received = onDisk || received;
        st.total = total || st.received;
        st.speed = 0;
        st.message = '';
        setProgress(win(), -1);
        push();
        if (host && host.notify) {
          host.notify(
            '更新包已就绪',
            '教学管理系统 v' + info.versionName + ' 已下载完成，点击立即安装',
            () => {
              st.dialog = true;
              push();
            }
          );
        }
        if (typeof resolve === 'function') resolve(snapshot());
      };

      try {
        out.end(complete);
      } catch (err) {
        /* 写流已关闭，直接走 complete 的兜底 */
      }
      // 兜底：写流回调万一不来，也要在超时后尝试落地（complete 内会核对磁盘字节数）
      flushTimer = setTimeout(complete, 12000);
    };

    try {
      req = net.request({ method: 'GET', url: info.url, redirect: 'follow' });
    } catch (err) {
      fail('无法发起下载：' + err.message);
      return;
    }
    activeRequest = req;
    armIdle();

    req.on('response', (res) => {
      if (res.statusCode !== 200) {
        try { res.resume(); } catch (err) { /* ignore */ }
        fail('服务器返回 HTTP ' + res.statusCode);
        return;
      }
      const len = Number(res.headers['content-length']);
      if (len > 0) total = len;
      st.total = total;
      armIdle();

      res.on('data', (chunk) => {
        received += chunk.length;
        hash.update(chunk);
        // 写盘跟不上就暂停接收，避免 80MB 包在内存里堆积
        if (!out.write(chunk)) {
          try { res.pause(); } catch (err) { /* ignore */ }
          out.once('drain', () => {
            try { res.resume(); } catch (err) { /* ignore */ }
          });
        }
        const now = Date.now();
        if (now - lastTick >= 300) {
          const deltaMs = Math.max(1, now - lastTick);
          st.speed = Math.round(((received - lastBytes) / deltaMs) * 1000);
          lastTick = now;
          lastBytes = received;
        }
        st.received = received;
        st.percent = total > 0 ? Math.min(100, Math.floor((received / total) * 100)) : 0;
        push();
        if (total > 0) setProgress(win(), st.percent / 100);

        armIdle();
        // 收够字节数就收尾，不等 end 事件
        if (total > 0 && received >= total) finalize();
      });
      res.on('end', finalize);
      res.on('close', () => {
        if (total === 0) finalize();
      });
      res.on('error', (err) => fail('下载中断：' + err.message));
    });

    req.on('error', (err) => {
      if (stage !== 'stream') return;
      fail('下载失败：' + err.message);
    });

    req.end();
  });
}

function cancelDownload() {
  if (st.phase !== 'downloading') return snapshot();
  try {
    if (activeRequest) activeRequest.abort();
  } catch (err) {
    /* ignore */
  }
  activeRequest = null;
  const win = host && host.getWindow ? host.getWindow() : null;
  setProgress(win, -1);
  if (st.file) {
    try { fs.unlinkSync(st.file); } catch (err) { /* ignore */ }
  }
  st.file = '';
  st.phase = 'available';
  st.dialog = true;
  st.message = '已取消下载。';
  st.percent = 0;
  st.received = 0;
  st.speed = 0;
  push();
  return snapshot();
}

/* ------------------------------------------------------------------ *
 * 安装
 *
 * 脚本生成（psQuote / waitForExitScript / installerScript / portableScript）
 * 与「分离式隐藏 PowerShell」启动器都放在 ./update-scripts.js，
 * 那里不依赖 Electron，便于 tools/install-sim.js 用同一份代码做落地演练。
 * ------------------------------------------------------------------ */

function install() {
  if (st.phase !== 'ready' || !st.file) return snapshot();
  if (!fs.existsSync(st.file)) {
    st.phase = 'error';
    st.dialog = true;
    st.message = '安装包已不存在，请重新下载。';
    push();
    return snapshot();
  }
  if (!st.canAutoUpdate) {
    st.phase = 'unsupported';
    st.dialog = true;
    st.message = '';
    push();
    return snapshot();
  }

  const name = st.latest ? st.latest.versionName : '';

  st.phase = 'installing';
  st.dialog = true;
  st.message = '已打开安装包，请将「教学管理系统」拖入「应用程序」完成升级，客户端即将退出…';
  push();

  /*
   * macOS 没有 NSIS / PowerShell 那一套：下载完成后直接打开安装包
   * （.dmg 会被挂载并弹出 Finder 窗口，.zip 会被归档工具解压到同目录），
   * 再由用户手动把新 App 拖进「应用程序」覆盖旧版。然后退出当前客户端。
   */
  try {
    shell.openPath(st.file);
  } catch (err) {
    try {
      shell.openExternal(SITE_ORIGIN + '/download');
    } catch (e) {
      /* ignore */
    }
  }

  setTimeout(() => {
    if (host && host.isQuitting) host.isQuitting();
    app.quit();
  }, 800);

  return snapshot();
}

/* ------------------------------------------------------------------ *
 * 用户操作
 * ------------------------------------------------------------------ */

function later() {
  st.dialog = false;
  st.manual = false; // 用户已收起弹窗，后续结果只更新徽标，不再自动弹回来
  st.message = '';
  push();
  return snapshot();
}

function skipVersion() {
  const name = st.latest ? st.latest.versionName : '';
  st.skipped = true;
  st.dialog = false;
  st.manual = false;
  st.message = '';
  if (host && host.patchSettings && name) host.patchSettings({ skippedVersion: name });
  push();
  return snapshot();
}

function clearSkip() {
  st.skipped = false;
  if (host && host.patchSettings) host.patchSettings({ skippedVersion: '' });
  push();
  return snapshot();
}

function openDownloadPage() {
  const { shell } = require('electron');
  shell.openExternal(SITE_ORIGIN + '/download');
}

function openUpdateFolder() {
  const { shell } = require('electron');
  const p = st.file || UPDATE_DIR();
  try {
    if (st.file && fs.existsSync(st.file)) {
      shell.showItemInFolder(st.file);
      return;
    }
  } catch (err) {
    /* ignore */
  }
  shell.openPath(UPDATE_DIR());
}

function currentState() {
  return snapshot();
}

module.exports = {
  init,
  scheduleStartupCheck,
  show,
  check,
  startDownload,
  cancelDownload,
  install,
  later,
  skipVersion,
  clearSkip,
  openDownloadPage,
  openUpdateFolder,
  currentState,
  clearDownloads,
  semverCode,
  compareSemver,
};
