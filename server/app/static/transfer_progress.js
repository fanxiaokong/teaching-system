/* 传输进度：上传（接管表单）+ 下载（接管带 data-progress 的链接）
 * 全站通用，不依赖任何业务 CSS。
 */
(function () {
  'use strict';

  function fmt(bytes) {
    if (!bytes || bytes <= 0) return '0 B';
    var units = ['B', 'KB', 'MB', 'GB'];
    var v = bytes, i = 0;
    while (v >= 1024 && i < units.length - 1) { v = v / 1024; i++; }
    return (i === 0 ? Math.round(v) : v.toFixed(1)) + ' ' + units[i];
  }

  // 右下角浮动进度面板容器
  var stack = null;
  function ensureStack() {
    if (stack) return stack;
    stack = document.createElement('div');
    stack.id = 'lc-progress-stack';
    stack.style.cssText = 'position:fixed;right:20px;bottom:20px;z-index:99999;display:flex;flex-direction:column;gap:10px;max-width:320px;';
    document.body.appendChild(stack);
    return stack;
  }

  function Panel(title) {
    var host = ensureStack();
    var box = document.createElement('div');
    box.style.cssText = 'background:#fff;border:1px solid #e2e8f0;border-radius:10px;box-shadow:0 6px 20px rgba(15,23,42,.12);padding:12px 14px;font:14px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;color:#1f2937;';

    var head = document.createElement('div');
    head.style.cssText = 'display:flex;justify-content:space-between;gap:12px;align-items:baseline;';
    var t = document.createElement('span');
    t.textContent = title;
    t.style.cssText = 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
    var pct = document.createElement('span');
    pct.textContent = '0%';
    pct.style.cssText = 'color:#2563eb;font-weight:600;flex:none;';
    head.appendChild(t); head.appendChild(pct);

    var bar = document.createElement('div');
    bar.style.cssText = 'margin-top:8px;height:8px;background:#eef2f7;border-radius:8px;overflow:hidden;';
    var fill = document.createElement('i');
    fill.style.cssText = 'display:block;height:100%;width:0;background:#2563eb;border-radius:8px;transition:width .15s linear;';
    bar.appendChild(fill);

    var sub = document.createElement('div');
    sub.style.cssText = 'margin-top:6px;font-size:12px;color:#8a94a6;';

    box.appendChild(head); box.appendChild(bar); box.appendChild(sub);
    host.appendChild(box);

    return {
      setTitle: function (s) { t.textContent = s; },
      update: function (percent, text) {
        if (percent >= 0) {
          fill.style.width = Math.min(100, percent) + '%';
          pct.textContent = Math.min(100, percent) + '%';
        } else {
          pct.textContent = '…';
        }
        if (text) sub.textContent = text;
      },
      // action 可选：{ label, onClick, hint } —— 下载完成后给一个「打开文件」按钮。
      // 传了 action 就不自动 1.2 秒消失，改成 10 秒，给用户留出点击时间。
      done: function (msg, action) {
        fill.style.width = '100%';
        pct.textContent = '100%';
        pct.style.color = '#16a34a';
        fill.style.background = '#16a34a';
        sub.textContent = msg || '完成';
        if (action && action.label && action.onClick) {
          var row = document.createElement('div');
          row.style.cssText = 'margin-top:8px;display:flex;align-items:center;gap:10px;';
          var btn = document.createElement('button');
          btn.type = 'button';
          btn.textContent = action.label;
          btn.style.cssText = 'border:0;background:#2563eb;color:#fff;border-radius:6px;padding:5px 12px;font:inherit;cursor:pointer;';
          btn.addEventListener('click', function () { action.onClick(); });
          row.appendChild(btn);
          if (action.hint) {
            var tip = document.createElement('span');
            tip.textContent = action.hint;
            tip.style.cssText = 'font-size:12px;color:#8a94a6;';
            row.appendChild(tip);
          }
          box.appendChild(row);
          setTimeout(this.remove, 10000);
        } else {
          setTimeout(this.remove, 1200);
        }
      },
      fail: function (msg) {
        pct.textContent = '失败';
        pct.style.color = '#dc2626';
        fill.style.background = '#dc2626';
        sub.textContent = msg || '出错了';
        setTimeout(this.remove, 4000);
      },
      remove: function () { if (box.parentNode) box.parentNode.removeChild(box); }
    };
  }

  // ===== 上传：接管带 data-progress 的 multipart 表单 =====
  // 说明：故意不做「全局自动接管」——像 /convert 这种"提交后把结果渲染在本页"的表单，
  // 一旦被 XHR 接管就会丢结果，所以这里只处理显式加了 data-progress 的表单。
  var lastSubmitter = null;
  document.addEventListener('click', function (e) {
    var b = e.target && e.target.closest ? e.target.closest('button,input[type=submit]') : null;
    if (b && b.form) lastSubmitter = b;
  }, true);

  // 处理上传后的响应：服务端发生了跳转就跟过去；否则把返回的页面渲染进当前文档
  // （这样能保留 flash 提示、转换结果链接这类内容；页面级脚本已在初次加载时注册到 document 上，
  //  不会因为替换 body 而失效）
  function applyResult(xhr, form) {
    var target = xhr.responseURL || form.getAttribute('action') || location.href;
    var type = (xhr.getResponseHeader('Content-Type') || '').toLowerCase();
    if (type.indexOf('text/html') === -1 || target !== location.href) {
      setTimeout(function () { location.assign(target); }, 400);
      return;
    }
    try {
      var doc = new DOMParser().parseFromString(xhr.responseText, 'text/html');
      if (!doc.body) { location.reload(); return; }
      document.title = doc.title || document.title;
      document.body.innerHTML = doc.body.innerHTML;
      window.scrollTo(0, 0);
    } catch (e) {
      location.reload();
    }
  }

  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (!form || form.tagName !== 'FORM') return;
    var enc = (form.getAttribute('enctype') || '').toLowerCase();
    if (enc.indexOf('multipart/form-data') === -1) return;      // 只处理带文件的表单
    if (!form.hasAttribute('data-progress')) return;            // 只处理显式开启的表单
    if (form.hasAttribute('data-no-progress')) return;
    var fileInput = form.querySelector('input[type=file]');
    if (!fileInput) return;

    var files = fileInput.files;
    var name = (files && files[0]) ? files[0].name : '文件';
    var totalBytes = 0;
    if (files) { for (var i = 0; i < files.length; i++) totalBytes += files[i].size; }

    e.preventDefault();
    var panel = Panel('上传：' + name);
    panel.update(0, fmt(totalBytes));

    var fd = new FormData(form);
    // 补上被点击按钮的 name/value（后端可能靠它区分动作）
    if (lastSubmitter && lastSubmitter.name && lastSubmitter.form === form) {
      fd.append(lastSubmitter.name, lastSubmitter.value || '');
    }

    var xhr = new XMLHttpRequest();
    xhr.open((form.getAttribute('method') || 'POST').toUpperCase(),
             form.getAttribute('action') || location.href, true);
    xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
    xhr.upload.addEventListener('progress', function (ev) {
      if (ev.lengthComputable) {
        panel.update(Math.round(ev.loaded * 100 / ev.total), fmt(ev.loaded) + ' / ' + fmt(ev.total));
      } else {
        panel.update(-1, fmt(ev.loaded));
      }
    });
    xhr.addEventListener('load', function () {
      if (xhr.status >= 200 && xhr.status < 400) {
        panel.done('上传完成');
        applyResult(xhr, form);
      } else {
        panel.fail('上传失败（' + xhr.status + '）');
      }
    });
    xhr.addEventListener('error', function () { panel.fail('网络错误'); });
    xhr.addEventListener('abort', function () { panel.fail('已取消'); });
    xhr.send(fd);
  }, true);

  // ===== 下载：接管带 data-progress 的链接 =====
  function fileNameFrom(headers, fallback) {
    var cd = headers.get('Content-Disposition') || '';
    // filename* 才是 RFC 5987 里带完整中文名字段，必须优先取；
    // 旧写法会先命中 ASCII 回退的 filename=，纯中文名只剩 ".zip"，
    // 存下来是个没有文件名的文件，打开自然是乱码。
    var star = /filename\*\s*=\s*(?:UTF-8|utf-8)''([^;]+)/i.exec(cd);
    if (star) {
      try { return decodeURIComponent(star[1].trim()); } catch (e) { /* 继续走兜底 */ }
    }
    var plain = /filename\s*=\s*"?([^";]+)"?/i.exec(cd);
    if (plain && plain[1].trim()) return plain[1].trim();
    return fallback;
  }

  function startDownload(url, name) {
    var panel = Panel('下载：' + name);
    panel.update(-1, '准备中…');
    fetch(url, { credentials: 'same-origin' }).then(function (res) {
      if (!res.ok) {
        panel.fail('下载失败（' + res.status + '）');
        return;
      }
      var fname = fileNameFrom(res.headers, name);
      var total = parseInt(res.headers.get('Content-Length'), 10) || 0;
      // 浏览器不支持流式读取时退回原生下载
      if (!res.body || !res.body.getReader) {
        panel.done('已开始下载');
        location.href = url;
        return;
      }
      var reader = res.body.getReader();
      var chunks = [], received = 0;
      function pump() {
        return reader.read().then(function (r) {
          if (r.done) {
            var blob = new Blob(chunks, { type: res.headers.get('Content-Type') || 'application/octet-stream' });
            var blobUrl = URL.createObjectURL(blob);
            // 先把文件交给浏览器下载（这样它进的是浏览器的下载列表，
            // 用户在浏览器下载栏里既能打开也能「在文件夹中显示」）
            var a = document.createElement('a');
            a.href = blobUrl;
            a.download = fname;
            document.body.appendChild(a);
            a.click();
            a.remove();
            // 面板上再给一个「打开文件」：用同一个 blob 在新标签页打开，
            // 浏览器认得的类型（PDF/图片/文本）会直接预览，其它类型会再次触发保存。
            panel.done('下载完成：' + fname, {
              label: '打开文件',
              hint: '找文件位置请到浏览器下载栏',
              onClick: function () { window.open(blobUrl, '_blank'); }
            });
            // 给「打开文件」留出足够长的有效期，用完再释放
            setTimeout(function () { URL.revokeObjectURL(blobUrl); }, 60000);
            return;
          }
          chunks.push(r.value);
          received += r.value.length;
          if (total) {
            panel.update(Math.min(100, Math.round(received * 100 / total)), fmt(received) + ' / ' + fmt(total));
          } else {
            panel.update(-1, fmt(received));
          }
          return pump();
        });
      }
      return pump();
    }).catch(function () { panel.fail('下载失败'); });
  }

  document.addEventListener('click', function (e) {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    var a = e.target && e.target.closest ? e.target.closest('a[data-progress]') : null;
    if (!a) return;
    e.preventDefault();
    startDownload(a.getAttribute('href'), a.getAttribute('data-progress-name') || (a.textContent || '文件').trim());
  }, true);
})();
