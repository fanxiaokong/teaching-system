/* 教学管理系统平台 · 全局小脚本
   课程编辑器的逻辑写在 admin_course_edit.html 里（只在那一页需要）。 */
(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', function () {
    // 提示条 6 秒后自动淡出
    document.querySelectorAll('.flash').forEach(function (box) {
      setTimeout(function () {
        box.style.transition = 'opacity .6s';
        box.style.opacity = '0';
        setTimeout(function () { box.style.display = 'none'; }, 700);
      }, 6000);
    });

    // 带 data-confirm 的表单统一二次确认
    document.querySelectorAll('form[data-confirm]').forEach(function (form) {
      form.addEventListener('submit', function (event) {
        if (!window.confirm(form.getAttribute('data-confirm'))) event.preventDefault();
      });
    });

    initLivePanels();

    // 报名表：只在「加入我们」页有，用来做前端即时校验
    initJoinForm();

    // 后台列表：多选 / 全选批量删除
    initBatchDelete();
  });

  /* ---------------- 后台实时数据面板 ----------------
     用法：给容器加 data-live，容器内放
       [data-live-stat="total"]    统计数字
       [data-live-time]            最后更新时间
       [data-live-rows]            tbody，用 data-cols 指定列顺序
       [data-live-refresh]         手动刷新按钮
       [data-live-toggle]          自动刷新开关
     容器属性：data-source（JSON 接口）、data-interval（秒，默认 30） */
  function initLivePanels() {
    document.querySelectorAll('[data-live]').forEach(function (panel) {
      var source = panel.getAttribute('data-source');
      var interval = (parseInt(panel.getAttribute('data-interval'), 10) || 30) * 1000;
      var toggle = panel.querySelector('[data-live-toggle]');
      var timer = null;
      var busy = false;

      function refresh() {
        if (busy) return;
        busy = true;
        var url = source + (source.indexOf('?') === -1 ? '?' : '&') + location.search.replace(/^\?/, '');
        fetch(url, { credentials: 'same-origin', headers: { 'X-Requested-With': 'fetch' } })
          .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
          .then(function (data) { apply(panel, data); })
          .catch(function () { /* 网络抖动就等下一轮，不打扰用户 */ })
          .then(function () { busy = false; });
      }

      function schedule() {
        if (timer) clearInterval(timer);
        if (!toggle || toggle.checked) timer = setInterval(refresh, interval);
      }

      var manual = panel.querySelector('[data-live-refresh]');
      if (manual) manual.addEventListener('click', refresh);
      if (toggle) toggle.addEventListener('change', schedule);

      // 切到后台标签页时暂停，回来立刻刷一次，省资源也更及时
      document.addEventListener('visibilitychange', function () {
        if (document.hidden) { if (timer) clearInterval(timer); timer = null; }
        else { refresh(); schedule(); }
      });

      refresh();
      schedule();
    });
  }

  var COLS = {
    id: function (r) { return cell('muted', pad(r.id, 4)); },
    name: function (r) { return cell('', r.name); },
    college: function (r) { return cell('', r.college); },
    contact: function (r) { return cell('', r.contact); },
    join_group: function (r) {
      return '<td>' + (r.join_group
        ? '<span class="badge badge-ok">是</span>'
        : '<span class="badge">否</span>') + '</td>';
    },
    note: function (r) { return cell('muted stem-cell', r.note || '—'); },
    created_at: function (r) { return cell('muted', String(r.created_at || '').slice(0, 16)); },
    ip: function (r) { return cell('muted', r.ip || '—'); },
    ops: function (r, tbody) {
      var prefix = tbody.getAttribute('data-del-prefix') || '';
      var suffix = tbody.getAttribute('data-del-suffix') || '';
      return '<td><form method="post" action="' + esc(prefix + r.id + suffix) +
        '" onsubmit="return confirm(\'确定删除这条记录？\');">' +
        '<button class="link link-danger" type="submit">删除</button></form></td>';
    }
  };

  function apply(panel, data) {
    if (data.stats) {
      Object.keys(data.stats).forEach(function (key) {
        var el = panel.querySelector('[data-live-stat="' + key + '"]');
        if (!el) return;
        var value = data.stats[key];
        el.textContent = key === 'rate' ? value + '%' : value;
      });
    }
    var time = panel.querySelector('[data-live-time]');
    if (time && data.updated_at) time.textContent = data.updated_at;

    // 报名表可能在页面别处，同步统计到所有可见的位置
    document.querySelectorAll('[data-live-stat]').forEach(function (el) {
      if (panel.contains(el) || !data.stats) return;
      var key = el.getAttribute('data-live-stat');
      if (key in data.stats) el.textContent = key === 'rate' ? data.stats[key] + '%' : data.stats[key];
    });

    var tbody = panel.querySelector('[data-live-rows]');
    if (!tbody) tbody = document.querySelector('[data-live-rows]');
    if (tbody && data.rows) {
      if (!data.rows.length) {
        tbody.innerHTML = '<tr><td colspan="9" class="muted">' +
          esc(tbody.getAttribute('data-empty') || '暂无数据') + '</td></tr>';
        return;
      }
      var cols = (tbody.getAttribute('data-cols') || 'id,name,college,contact,join_group,created_at')
        .split(',').map(function (s) { return s.trim(); }).filter(Boolean);
      tbody.innerHTML = data.rows.map(function (row) {
        return '<tr>' + cols.map(function (c) {
          return COLS[c] ? COLS[c](row, tbody) : '';
        }).join('') + '</tr>';
      }).join('');
    }
  }

  function cell(cls, value) {
    return '<td class="' + cls + '">' + esc(value) + '</td>';
  }

  function pad(value, size) {
    var text = String(value == null ? '' : value);
    while (text.length < size) text = '0' + text;
    return text;
  }

  function esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  /* ---------------- 「加入我们」表单 ---------------- */
  function initJoinForm() {
    var form = document.querySelector('.join-form');
    if (!form) return;
    form.addEventListener('submit', function (event) {
      var nameEl = form.querySelector('[name="name"]');
      var collegeEl = form.querySelector('[name="college"]');
      var contactEl = form.querySelector('[name="contact"]');
      var name = (nameEl.value || '').trim();
      var college = (collegeEl.value || '').trim();
      var contact = (contactEl.value || '').trim();
      var problem = '';
      if (name.length < 2) problem = '请填写真实姓名';
      else if (college.length < 2) problem = '请填写学院';
      else if (contact.length < 5) problem = '请填写有效的联系方式';
      else if (!form.querySelector('[name="join_group"]:checked')) problem = '请选择是否加入官方群聊';
      if (problem) {
        event.preventDefault();
        alert(problem);
        return;
      }
      var button = form.querySelector('button[type="submit"]');
      if (button) { button.disabled = true; button.textContent = '提交中…'; }
    });
  }

  /* ---------------- 后台列表：多选 / 全选批量删除 ----------------
     用法：在列表外层容器加 data-batch-entity="course"（值见后端 BATCH_ENTITIES），
     列表里每一行放一个 <input type="checkbox" class="batch-check" value="<id>">。
     本函数会自动注入「全选 + 已选 N 项 + 删除选中」工具条，勾选后 POST 到 /admin/batch-delete。 */
  function initBatchDelete() {
    var wrap = document.querySelector('[data-batch-entity]');
    if (!wrap) return;
    var entity = wrap.getAttribute('data-batch-entity');
    var checks = Array.prototype.slice.call(wrap.querySelectorAll('.batch-check'));
    if (!checks.length) return;

    var bar = document.createElement('div');
    bar.className = 'batch-bar';
    bar.hidden = true;
    bar.innerHTML =
      '<label class="batch-all"><input type="checkbox" class="batch-select-all"> 全选</label>' +
      '<span class="muted">已选 <b class="batch-count">0</b> 项</span>' +
      '<button type="button" class="btn btn-danger btn-sm batch-delete-btn">删除选中</button>';
    wrap.insertBefore(bar, wrap.firstChild);

    var all = bar.querySelector('.batch-select-all');
    var btn = bar.querySelector('.batch-delete-btn');
    var count = bar.querySelector('.batch-count');

    // 有搜索/筛选的页面（如课程）会隐藏部分行；全选与计数都只针对「当前可见」的行，
    // 避免先筛选再全选时把隐藏行也删掉。
    function visibles() {
      return checks.filter(function (c) { return c.offsetParent !== null; });
    }

    function refresh() {
      var vis = visibles();
      var sel = vis.filter(function (c) { return c.checked; });
      count.textContent = sel.length;
      bar.hidden = sel.length === 0;
      all.checked = vis.length > 0 && sel.length === vis.length;
      all.indeterminate = sel.length > 0 && sel.length < vis.length;
    }

    checks.forEach(function (c) { c.addEventListener('change', refresh); });
    all.addEventListener('change', function () {
      visibles().forEach(function (c) { c.checked = all.checked; });
      refresh();
    });
    btn.addEventListener('click', function () {
      var sel = visibles().filter(function (c) { return c.checked; })
        .map(function (c) { return c.value; });
      if (!sel.length) return;
      if (!window.confirm('确定删除选中的 ' + sel.length + ' 项？此操作不可恢复。')) return;
      var f = document.createElement('form');
      f.method = 'post';
      f.action = '/admin/batch-delete';
      function hid(name, value) {
        var inp = document.createElement('input');
        inp.type = 'hidden'; inp.name = name; inp.value = value;
        f.appendChild(inp);
      }
      hid('entity', entity);
      hid('ids', sel.join(','));
      document.body.appendChild(f);
      f.submit();
    });

    refresh();
  }
})();
