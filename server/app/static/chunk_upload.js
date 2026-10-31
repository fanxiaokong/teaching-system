/* 分片上传：把大文件切成 8MB 小片逐片 POST，绕开 2GB 请求体上限，
   同时避免一次性占用大量服务器内存。小文件也一样走，逻辑统一。
   用法：给上传表单加 data-chunk-upload 属性即可（记得去掉 data-progress，避免两套进度冲突）。 */
(function () {
  'use strict';

  var RETRY = 3;

  function injectStyle() {
    if (document.getElementById('chunkUploadStyle')) return;
    var s = document.createElement('style');
    s.id = 'chunkUploadStyle';
    s.textContent =
      '.chunk-prog{margin-top:12px;padding:10px 12px;border:1px solid #d7e0ea;border-radius:8px;background:#f7f9fc}' +
      '.chunk-prog p{margin:0 0 6px;font-size:13px;color:#33475b;word-break:break-all}' +
      '.chunk-track{height:8px;border-radius:4px;background:#e3e9f0;overflow:hidden}' +
      '.chunk-track i{display:block;height:100%;width:0;background:linear-gradient(90deg,#005fb8,#2b8ae6);transition:width .2s}' +
      '.chunk-meta{margin:6px 0 0!important;font-size:12px;color:#7b8794!important}' +
      '.chunk-done{color:#1a7f37}';
    document.head.appendChild(s);
  }

  function human(n) {
    var u = ['B', 'KB', 'MB', 'GB', 'TB'], i = 0;
    n = Number(n) || 0;
    while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
    return (i === 0 ? n : n.toFixed(1)) + ' ' + u[i];
  }

  function wait(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  function postJSON(url, obj) {
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(obj)
    }).then(function (r) { return r.json(); });
  }

  function postForm(url, fd) {
    return fetch(url, { method: 'POST', body: fd }).then(function (r) { return r.json(); });
  }

  function makePanel(form) {
    injectStyle();
    var box = form.querySelector('.chunk-prog');
    if (!box) {
      box = document.createElement('div');
      box.className = 'chunk-prog';
      box.innerHTML = '<p class="chunk-name"></p>' +
        '<div class="chunk-track"><i></i></div>' +
        '<p class="chunk-meta"></p>';
      form.appendChild(box);
    }
    return {
      box: box,
      name: box.querySelector('.chunk-name'),
      fill: box.querySelector('.chunk-track i'),
      meta: box.querySelector('.chunk-meta')
    };
  }

  function sendChunks(file, uid, chunkSize, total, done, ui) {
    var sent = 0;
    for (var k in done) {
      if (Object.prototype.hasOwnProperty.call(done, k)) {
        var s = Number(k) * chunkSize;
        sent += Math.min(chunkSize, file.size - s);
      }
    }
    var t0 = Date.now();

    function paint(idx) {
      var pct = file.size ? Math.min(100, (sent / file.size) * 100) : 100;
      ui.fill.style.width = pct.toFixed(1) + '%';
      var sec = (Date.now() - t0) / 1000;
      var speed = sec > 0.5 ? human(sent / sec) + '/s' : '计算中…';
      ui.meta.textContent = human(sent) + ' / ' + human(file.size) + '（' + pct.toFixed(1) +
        '%） · 第 ' + Math.min(idx + 1, total) + '/' + total + ' 片 · ' + speed;
    }

    function attempt(i, n) {
      var start = i * chunkSize;
      var end = Math.min(start + chunkSize, file.size);
      var fd = new FormData();
      fd.append('upload_id', uid);
      fd.append('index', i);
      fd.append('chunk', file.slice(start, end), file.name + '.part' + i);
      return postForm('/upload/chunk/part', fd).then(function (r) {
        if (r && r.ok) return r;
        throw new Error((r && r.error) || ('第 ' + (i + 1) + ' 片上传失败'));
      }).catch(function (e) {
        if (n < RETRY) {
          ui.meta.textContent = '第 ' + (i + 1) + ' 片失败，' + (n + 1) + ' 秒后重试（' + (n + 1) + '/' + RETRY + '）…';
          return wait(1000 * (n + 1)).then(function () { return attempt(i, n + 1); });
        }
        throw e;
      });
    }

    function next(i) {
      if (i >= total) return Promise.resolve(uid);
      if (done[i]) { return next(i + 1); }
      return attempt(i, 0).then(function () {
        sent += Math.min(chunkSize, file.size - i * chunkSize);
        done[i] = 1;
        paint(i);
        return next(i + 1);
      });
    }

    paint(0);
    return next(0);
  }

  function uploadOne(file, fields, ui) {
    ui.name.textContent = '正在上传：' + file.name + '（' + human(file.size) + '）';
    ui.fill.style.width = '0%';
    ui.meta.textContent = '准备中…';

    var payload = { filename: file.name, size: file.size };
    for (var k in fields) {
      if (Object.prototype.hasOwnProperty.call(fields, k)) payload[k] = fields[k];
    }

    return postJSON('/upload/chunk/init', payload).then(function (res) {
      if (!res || !res.ok) throw new Error((res && res.error) || '初始化上传失败');
      return res;
    }).then(function (res) {
      var done = {};
      return fetch('/upload/chunk/status?upload_id=' + encodeURIComponent(res.upload_id))
        .then(function (r) { return r.json(); })
        .then(function (st) {
          (st.received || []).forEach(function (i) { done[i] = 1; });
          return sendChunks(file, res.upload_id, res.chunk_size, res.chunks, done, ui);
        });
    }).then(function (uid) {
      ui.meta.textContent = '所有分片已到达，正在合并…';
      return postJSON('/upload/chunk/finish', { upload_id: uid });
    }).then(function (res) {
      if (!res || !res.ok) throw new Error((res && res.error) || '合并文件失败');
      ui.name.innerHTML = '<span class="chunk-done">✓ ' + file.name + ' 上传完成（' +
        human(res.size) + '）</span>';
      ui.fill.style.width = '100%';
      ui.meta.textContent = '';
      return res;
    });
  }

  function collect(form) {
    var out = {};
    Array.prototype.forEach.call(form.elements, function (el) {
      if (!el.name) return;
      if (el.type === 'file' || el.type === 'submit' || el.type === 'button') return;
      if (el.disabled) return;
      if ((el.type === 'checkbox' || el.type === 'radio') && !el.checked) return;
      out[el.name] = el.value;
    });
    return out;
  }

  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (!form || form.tagName !== 'FORM') return;
    if (!form.hasAttribute('data-chunk-upload')) return;

    var input = form.querySelector('input[type=file]');
    if (!input || !input.files || !input.files.length) return;   // 没选文件 → 交给原表单

    e.preventDefault();
    e.stopImmediatePropagation();

    var files = Array.prototype.filter.call(input.files, function (f) { return f.size > 0; });
    if (!files.length) return;

    var btn = form.querySelector('button[type=submit], .btn-primary');
    var oldText = btn ? btn.textContent : '';
    if (btn) { btn.disabled = true; btn.textContent = '上传中…'; }

    var ui = makePanel(form);
    var fields = collect(form);
    var chain = Promise.resolve();
    var okCount = 0;
    var errors = [];

    files.forEach(function (f) {
      chain = chain.then(function () {
        return uploadOne(f, fields, ui).then(function () {
          okCount++;
        }).catch(function (err) {
          errors.push(f.name + '：' + (err && err.message ? err.message : err));
        });
      });
    });

    chain.then(function () {
      if (btn) { btn.disabled = false; btn.textContent = oldText; }
      if (errors.length) {
        ui.name.textContent = '完成 ' + okCount + ' 个，失败 ' + errors.length + ' 个';
        ui.meta.textContent = errors.join('；');
        return;
      }
      ui.name.innerHTML = '<span class="chunk-done">✓ 全部上传完成（' + okCount + ' 个文件）</span>';
      setTimeout(function () { window.location.reload(); }, 900);
    });
  });
})();
