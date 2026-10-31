/*
 * electron-builder afterPack 钩子：对打包好的 .app 做「临时签名」(ad-hoc)。
 *
 * 为什么必须做：
 *   我们用 "identity": null 关掉了 electron-builder 的正式签名（本机没有 Apple
 *   开发者证书）。但 electron-builder 在打包时会改写 Electron.app —— 重命名可执行
 *   文件、写入 Contents/Resources/app.asar、改 Info.plist —— 这会**破坏** Electron
 *   自带的 linker 临时签名，于是：
 *       codesign --verify  →  code has no resources but signature indicates they must be present
 *   Apple 芯片上签名无效的包，macOS 会直接弹「已损坏，无法打开，你应该将它移到废纸篓」
 *   （注意：这跟「未公证」不是一回事，后者还能在系统设置里放行，前者彻底打不开）。
 *
 *   在 afterPack 阶段重新做一次 ad-hoc 深度签名，签名即恢复有效；之后
 *   electron-builder 再用这个已签名的 .app 去打 DMG / ZIP，产物就是可用的。
 *
 * 注意：不要加 --options runtime（强化运行时）。ad-hoc + 强化运行时会因为缺少
 *       allow-jit 等 entitlement 让 Electron 起不来。也不要用 --timestamp（需要证书）。
 */

const { execFileSync, spawnSync } = require('child_process');
const path = require('path');

function run(cmd, args) {
  execFileSync(cmd, args, { stdio: 'inherit' });
}

async function afterPack(context) {
  if (context.electronPlatformName !== 'darwin') return;

  const appName = context.packager.appInfo.productFilename + '.app';
  const appPath = path.join(context.appOutDir, appName);

  console.log('[afterpack-sign] ad-hoc 签名：' + appPath);

  // 深度重签：连同 Frameworks 下的 Helper.app / *.framework 一起签
  run('codesign', ['--force', '--deep', '--sign', '-', appPath]);

  // 立刻验证，签名无效就让构建失败，避免又发出去一个「已损坏」的包
  run('codesign', ['--verify', '--deep', '--strict', '--verbose=2', appPath]);

  // codesign -dv 的信息是写到 stderr 的，用 spawnSync 才能同时拿到 stdout/stderr
  const dump = spawnSync('codesign', ['-dv', '--verbose=2', appPath], { encoding: 'utf8' });
  const info = String(dump.stdout || '') + '\n' + String(dump.stderr || '');
  const pick = (key) => {
    const line = String(info).split('\n').find((l) => l.startsWith(key));
    return line ? line.trim() : key + '?';
  };
  console.log('[afterpack-sign] ' + pick('Identifier=') + ' | ' + pick('Sealed Resources'));
  console.log('[afterpack-sign] 完成，签名有效');
}

module.exports = afterPack;
module.exports.default = afterPack;
