/*
 * 临时探针：单独加载外壳 shell.html，读出左侧图标栏、顶部标签、窗口按钮的实际渲染结果。
 * 用真实 preload（IPC 没主进程接收也不影响 shell.js 的 boot 渲染）。
 * 用法： env -u ELECTRON_RUN_AS_NODE ./node_modules/.bin/electron --no-sandbox --disable-gpu tools/probe_shell.js
 */
const { app, BrowserWindow } = require('electron');
const path = require('path');

app.commandLine.appendSwitch('no-sandbox');
app.commandLine.appendSwitch('disable-gpu');

const SHELL = path.join(__dirname, '..', 'src', 'shell.html');
const PRELOAD = path.join(__dirname, '..', 'src', 'preload.js');

app.whenReady().then(async () => {
  const win = new BrowserWindow({
    width: 1360, height: 860, show: false,
    webPreferences: { preload: PRELOAD, contextIsolation: true, sandbox: false },
  });

  // 本机是 macOS，UA 会走 mac 分支；用 LC_UA 强制伪装成 Windows 验证另一条分支
  const ua = process.env.LC_UA;
  if (ua) win.webContents.setUserAgent(ua);

  const errs = [];
  win.webContents.on('console-message', (e, level, message) => {
    if (level >= 2) errs.push(String(message).slice(0, 200));
  });

  await win.loadFile(SHELL);
  await new Promise((r) => setTimeout(r, 1200));

  const out = await win.webContents.executeJavaScript(`(() => {
    const rail = Array.from(document.querySelectorAll('#sideNav .rail-item')).map((el) => ({
      tx: (el.querySelector('.tx') || {}).textContent || '',
      on: el.classList.contains('on'),
      ext: !!el.querySelector('.ext'),
    }));
    const tabs = Array.from(document.querySelectorAll('#topTabs .ab-tab')).map((el) => el.textContent.trim());
    const ctl = document.querySelector('.win-ctl');
    const ctlBtns = ctl ? Array.from(ctl.querySelectorAll('button')).map((b) => b.id) : null;
    const ctlVisible = ctl ? getComputedStyle(ctl).display !== 'none' : null;
    const appbarPad = getComputedStyle(document.querySelector('.appbar')).paddingLeft;
    return {
      rail, tabs,
      bodyClass: document.body.className,
      winCtlButtons: ctlBtns,
      winCtlVisible: ctlVisible,
      appbarPaddingLeft: appbarPad,
      sub: (document.getElementById('tbSub') || {}).textContent || '',
    };
  })()`).catch((e) => ({ evalError: String(e && e.message) }));

  console.log('=== SHELL_PROBE ===');
  console.log(JSON.stringify(out, null, 2));
  if (errs.length) {
    console.log('=== 控制台错误 ===');
    errs.forEach((m) => console.log(' ', m));
  }
  app.exit(0);
});
