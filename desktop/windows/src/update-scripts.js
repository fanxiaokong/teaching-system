'use strict';

/**
 * 更新安装脚本生成器（纯逻辑，不依赖 Electron）。
 *
 * 之所以单独拆出来：安装脚本涉及中文路径、PowerShell 编码、文件占用重试等
 * 容易出错又难验证的部分。拆成无依赖模块后，tools/install-sim.js 可以直接
 * 引用同一个函数做「真脚本 + 真文件」的落地演练，保证被测代码 == 发版代码。
 *
 * 关键设计：
 *  - 脚本用 UTF-16LE base64 经 -EncodedCommand 传入，彻底绕开控制台代码页问题，
 *    这也是中文路径唯一可靠的传参方式（不要改成写 .ps1/.bat 文件）。
 *  - 安装/替换必须由「主程序退出之后」的独立 PowerShell 完成，
 *    因为运行中的 exe 无法被覆盖（实测 mv 会报 Device or resource busy）。
 *  - 第一件事是写「启动凭据」（beacon）：主进程靠它确认帮手真的跑起来了，
 *    确认不到就【不退出】并报错 —— 杜绝「客户端自己关了但其实没升级」。
 *  - 全程写日志，装完/失败都可追溯（早期版本把所有错误静默吞掉，极难排查）。
 */

const { spawn } = require('child_process');

/** PowerShell 单引号字符串转义：内部单引号翻倍 */
function psQuote(value) {
  return "'" + String(value).replace(/'/g, "''") + "'";
}

/**
 * 等待目标进程退出。
 * @param {number} [pid] 要等待的进程号，默认当前进程。
 *                       测试时可传入一个「已经不存在的 PID」让等待立即返回。
 */
function waitForExitScript(pid) {
  const target = typeof pid === 'number' ? pid : process.pid;
  // 修复：等待目标进程退出必须有超时上限，不能无限循环。
  //
  // 血泪教训：早期版本这里是 `while (Get-Process -Id $targetPid) { sleep }` 无限等。
  // 一旦主进程因为某种原因（杀软拦截退出、WebContentsView 未销毁、更新窗口未关、
  // 系统卡顿等）没能干净退出，帮手就会永久卡在这里，静默安装一步都走不到，
  // 用户看到的现象就是「点了更新、提示完成，重开还是旧版本」。
  //
  // 现在：最多等 30 秒（正常退出只要 1~2 秒，30 秒已足够宽裕）；
  // 超时后不再死等，用 taskkill /F /T 强制终止整个进程树（含渲染/GPU 子进程），
  // 确保 NSIS 静默安装时 exe 不被占用。装不上也只会提示失败，绝不会无限悬挂。
  return [
    "$ErrorActionPreference = 'SilentlyContinue'",
    '$targetPid = ' + String(target),
    '$waited = 0',
    'while (Get-Process -Id $targetPid -ErrorAction SilentlyContinue) {',
    '  Start-Sleep -Milliseconds 300',
    '  $waited += 0.3',
    '  if ($waited -ge 30) {',
    "    Write-LcLog ('timeout waiting for app exit after ' + $waited + 's, force-killing process tree')",
    '    taskkill /F /T /PID $targetPid 2>$null | Out-Null',
    '    Start-Sleep -Seconds 2',
    '    break',
    '  }',
    '}',
    "Write-LcLog ('app exit waited ' + [math]::Round($waited,1) + 's')",
    'Start-Sleep -Milliseconds 700',
  ].join('\n');
}

/**
 * 「帮手已启动」凭据：必须是脚本的第一个动作。
 * 主进程等到这个文件出现才敢退出自己。
 *
 * 同时兼作「互斥锁」：如果凭据已存在，说明已经有一个帮手在跑，直接退出 ——
 * 主进程在确认不到凭据时会退回非分离方式再启动一次，这个判断保证不会出现
 * 两个帮手同时做替换（那会把绿色版的原地替换搞坏）。
 */
function beaconScript(beaconPath) {
  const q = psQuote(beaconPath);
  return [
    "$ErrorActionPreference = 'SilentlyContinue'",
    'if (Test-Path -LiteralPath ' + q + ') { exit }',
    'Set-Content -LiteralPath ' + q + " -Value 'ok' -Encoding ASCII",
  ].join('\n');
}

/** 日志函数。所有关键节点都记一笔，出问题能直接看日志定位。 */
function logScript(logPath) {
  return [
    "$ErrorActionPreference = 'SilentlyContinue'",
    'function Write-LcLog($m) {',
    '  Add-Content -LiteralPath ' + psQuote(logPath) +
      " -Value ((Get-Date).ToString('yyyy-MM-dd HH:mm:ss') + '  ' + $m) -ErrorAction SilentlyContinue",
    '}',
  ].join('\n');
}

/**
 * 安装版：静默原地升级，然后自动拉起新版本。
 *
 * 为什么不再用安装向导：
 *  electron-builder 的 NSIS 会从注册表 HKCU\Software\<APP_GUID>\InstallLocation
 *  读出上次的安装目录（multiUser.nsh 的 setInstallModePerUser），所以 /S /currentuser
 *  就是「装回原目录」的原地升级，既不需要用户点任何东西，也不会装出第二份。
 *  之前的向导方案把「装到哪」交给了用户点选，一旦选到别处就会出现
 *  「向导走完了，但你一直启动的那个 exe 从没被换过」=> 表现为「升级后还是旧版本」。
 *  /currentuser 是为了避免触发 UAC（本工程 perMachine: false，只装单用户）。
 */
function installerScript(pkgPath, opts) {
  const o = opts || {};
  const installDir = o.installDir || '';
  const launchExe = o.launchExe || '';
  const asar = installDir ? installDir + '\\resources\\app.asar' : '';

  return [
    beaconScript(o.beacon),
    logScript(o.log),
    "Write-LcLog 'helper started (setup)'",
    // 记录安装前 asar 时间戳，用于安装后判断「文件是否真的被更新了」
    '$asar = ' + (asar ? psQuote(asar) : "''"),
    '$before = $null',
    'if ($asar -and (Test-Path -LiteralPath $asar)) { $before = (Get-Item -LiteralPath $asar).LastWriteTimeUtc }',
    waitForExitScript(o.pid),
    "Write-LcLog 'target app exited'",
    '$p = Start-Process -FilePath ' + psQuote(pkgPath) +
      " -ArgumentList '/S','/currentuser' -PassThru -Wait",
    'Write-LcLog ("installer exit=" + $p.ExitCode)',
    // 等新版文件落地（NSIS 静默安装收尾有时异步，光看进程退出会抢跑）
    "Write-LcLog 'waiting for installed files'",
    'if ($asar) {',
    '  $updated = $false',
    '  for ($i = 0; $i -lt 120; $i++) {',
    '    if ((Test-Path -LiteralPath $asar) -and $before -and ((Get-Item -LiteralPath $asar).LastWriteTimeUtc -gt $before)) { $updated = $true; Write-LcLog "installed after " + $i + "s"; break }',
    '    Start-Sleep -Milliseconds 1000',
    '  }',
    '  if (-not $updated -and $before) { Write-LcLog "WARNING: asar mtime not changed, install may have failed" }',
    '}',
    launchExe ? 'Start-Process -FilePath ' + psQuote(launchExe) + " -ArgumentList '--updated'" : '',
    "Write-LcLog 'relaunch issued'",
  ].filter(Boolean).join('\n');
}

/**
 * 绿色版：当前 exe 先改名让位，新 exe 顶上来，再启动。
 * 运行中的 exe 不能覆盖自己，但退出后由独立进程改名/替换是可行的。
 */
function portableScript(portableExe, pkgPath, opts) {
  const o = opts || {};
  const old = portableExe + '.old';
  const tryMove = [
    'function Move-WithRetry($from, $to) {',
    '  for ($i = 0; $i -lt 25; $i++) {',
    '    Move-Item -LiteralPath $from -Destination $to -Force -ErrorAction SilentlyContinue',
    '    if (-not (Test-Path -LiteralPath $from)) { return $true }',
    '    Start-Sleep -Milliseconds 400',
    '  }',
    '  return $false',
    '}',
  ].join('\n');

  return [
    beaconScript(o.beacon),
    logScript(o.log),
    "Write-LcLog 'helper started (portable)'",
    tryMove,
    waitForExitScript(o.pid),
    "Write-LcLog 'target app exited'",
    'Remove-Item -LiteralPath ' + psQuote(old) + ' -Force -ErrorAction SilentlyContinue',
    'if (Move-WithRetry ' + psQuote(portableExe) + ' ' + psQuote(old) + ') {',
    '  Write-LcLog "old exe renamed"',
    '  if (Move-WithRetry ' + psQuote(pkgPath) + ' ' + psQuote(portableExe) + ') {',
    '    Write-LcLog "new exe in place"',
    '    Start-Process -FilePath ' + psQuote(portableExe),
    '    Write-LcLog "relaunch issued"',
    '    Start-Sleep -Seconds 3',
    '    Remove-Item -LiteralPath ' + psQuote(old) + ' -Force -ErrorAction SilentlyContinue',
    '  } else {',
    '    Write-LcLog "FAILED to move new exe, rolling back"',
    '    Move-WithRetry ' + psQuote(old) + ' ' + psQuote(portableExe),
    '  }',
    '} else {',
    '  Write-LcLog "FAILED to rename running exe (locked?), giving up"',
    '}',
  ].join('\n');
}

/**
 * 以「无窗口」方式跑一段 PowerShell，不阻塞主程序，便于随后立刻退出自身。
 *
 * 血泪教训（v1.4.4→1.4.5 升级失败的根因，此处修复）：
 *  1. 之前用 `spawn('powershell.exe', ..., { detached: true, unref: true })` 以为能让
 *     脚本「活过主进程退出」。但在 Windows + Electron 下这是靠不住的——Electron 主进程
 *     退出时会把纳入其进程树/Job Object 的子进程（含 detached 的 powershell）一并终止。
 *     帮手往往刚写完 beacon + 第一行日志 `helper started (setup)` 就被连带杀死，
 *     NSIS 静默安装一步都没走到。用户看到的现象就是「点立即安装并重启 → 没反应 →
 *     重开还是旧版本」，update.log 永远停在第一行。
 *  2. 可靠做法：通过 `cmd.exe /c start` 再套一层。`start` 用 ShellExecute 语义另起进程，
 *     新进程脱离父进程 Job Object，主进程退出后它照样继续跑完「等退出 → 静默安装 → 拉起新版」。
 *  3. 为什么不直接 `start powershell -EncodedCommand <base64>`：`start` 会按命令行
 *     解析规则重排参数，base64 里常见的 `=`、`+`、`/` 会被当成参数分隔符破坏，导致
 *     脚本解密失败。所以这里让 `start` 只启动一个 `cmd.exe /c ...`，把 base64 藏进
 *     cmd 的参数里，由 cmd 原样交给 powershell 的 -EncodedCommand，不再被 start 改写。
 *  4. `start` 是异步返回的，Node 侧拿不到真正的 powershell 进程句柄；调用方仍然必须
 *     靠 beacon 文件确认帮手真的跑起来了，失败时重试一次。
 *  5. spawn 失败是异步的（'error' 事件），try/catch 抓不到；不挂监听会让未处理的
 *     'error' 事件把主进程打挂，所以这里必须提供 onError 回调。
 */
function runHiddenPowerShell(script, onError, detached) {
  const encoded = Buffer.from(script, 'utf16le').toString('base64');
  // start 只负责启动一个独立的 cmd，base64 作为 cmd 的参数原样传递：
  //   start "" /b cmd.exe /c powershell.exe -NoProfile ... -EncodedCommand <base64>
  // 注意 start 的标题占位 ""、/b（不新开窗口）都在外层，真正的 powershell 命令在 cmd 里。
  const child = spawn(
    'cmd.exe',
    [
      '/c', 'start', '', '/b', 'cmd.exe', '/c',
      'powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
      '-EncodedCommand', encoded,
    ],
    { detached: detached !== false, stdio: 'ignore', windowsHide: true }
  );
  if (typeof onError === 'function') {
    child.on('error', (err) => onError(err));
  }
  child.unref();
  return child;
}

module.exports = {
  psQuote,
  waitForExitScript,
  beaconScript,
  installerScript,
  portableScript,
  runHiddenPowerShell,
};
