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
  // PID 复用几乎不可能在同一秒内发生，这里够用
  return [
    "$ErrorActionPreference = 'SilentlyContinue'",
    '$targetPid = ' + String(target),
    'while (Get-Process -Id $targetPid -ErrorAction SilentlyContinue) { Start-Sleep -Milliseconds 300 }',
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

/** 等新文件真正落地：NSIS 静默安装收尾有时是异步的，光看进程退出会抢跑。 */
function waitForFilesScript(asarPath) {
  return [
    '$asar = ' + (asarPath ? psQuote(asarPath) : "''"),
    '$before = $null',
    'if ($asar -and (Test-Path -LiteralPath $asar)) { $before = (Get-Item -LiteralPath $asar).LastWriteTimeUtc }',
    'if ($before) {',
    '  for ($i = 0; $i -lt 120; $i++) {',
    '    Start-Sleep -Milliseconds 1000',
    '    if (-not (Test-Path -LiteralPath $asar)) { continue }',
    '    if ((Get-Item -LiteralPath $asar).LastWriteTimeUtc -gt $before) { Write-LcLog ("files updated after " + $i + "s"); break }',
    '  }',
    '} else {',
    '  Start-Sleep -Seconds 25',
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
    waitForExitScript(o.pid),
    "Write-LcLog 'target app exited'",
    waitForFilesScript(asar),
    '$p = Start-Process -FilePath ' + psQuote(pkgPath) +
      " -ArgumentList '/S','/currentuser' -PassThru -Wait",
    'Write-LcLog ("installer exit=" + $p.ExitCode)',
    // 等新版文件落地（若前面已经等到，这里会立刻通过）
    "Write-LcLog 'waiting for installed files'",
    'if ($asar) {',
    '  for ($i = 0; $i -lt 120; $i++) {',
    '    if ((Test-Path -LiteralPath $asar) -and $before -and ((Get-Item -LiteralPath $asar).LastWriteTimeUtc -gt $before)) { Write-LcLog "installed after " + $i + "s"; break }',
    '    Start-Sleep -Milliseconds 1000',
    '  }',
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
 * 两个要点：
 *  1. detached + unref 是为了让脚本活过本进程退出 —— 替换/安装必须在主程序关闭后进行。
 *     但实测 detached 启动 powershell.exe 存在「进程起来了却什么都没执行」的情况，
 *     所以调用方必须用 beacon 确认，失败时退回 detached:false 重试。
 *  2. spawn 失败是异步的（'error' 事件），try/catch 抓不到；不挂监听会让未处理的
 *     'error' 事件把主进程打挂，所以这里必须提供 onError 回调。
 */
function runHiddenPowerShell(script, onError, detached) {
  const encoded = Buffer.from(script, 'utf16le').toString('base64');
  const child = spawn(
    'powershell.exe',
    ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', encoded],
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
