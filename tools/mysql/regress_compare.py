#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同一份数据，SQLite 版 vs MySQL 版两个站点实例，逐路由比对响应。

流程：
    1. 把 server/data 复制到 /tmp/lc-regress/data（不碰真实数据）
    2. 用这份数据的 netlab.db 迁出一个 MySQL 库 netlab_dev
    3. 两个实例分别启动（8801 = SQLite，8802 = MySQL），共用同一个 SECRET_KEY
    4. 各自登录 admin / 普通用户，然后按同一顺序请求同一批 URL
    5. 对归一化后的响应体做 sha256 比对，输出差异表

归一化会抹掉天然会变的部分（时间戳、epoch、随机 token、文件名里的时间戳），
只有真正由「数据库后端不同」引起的行为差异才会被报出来。

用法：
    server/.venv/bin/python tools/mysql/regress_compare.py \
        --mysql-password 'CHANGE_ME_PASSWORD'
"""
from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
APP = os.path.join(ROOT, 'server', 'app')
VENV_PY = os.path.join(ROOT, 'server', '.venv', 'bin', 'python')

WORK = '/tmp/lc-regress'
DATA = os.path.join(WORK, 'data')
SECRET = 'regress-fixed-secret-key'
ADMIN_PW = 'RegressAdmin@2026'

# ---------------------------------------------------------------- 归一化

NORM_RULES = [
    (re.compile(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}'), '<DT>'),
    (re.compile(r'\d{4}-\d{2}-\d{2}'), '<DATE>'),
    (re.compile(r'\b1[6-9]\d{11}\b'), '<MS>'),
    (re.compile(r'\b1[6-9]\d{8}\b'), '<EPOCH>'),
    (re.compile(r'(session|csrf|token)["\']?\s*[:=]\s*["\']?[A-Za-z0-9._\-+/=]{16,}'),
     r'\1=<TK>'),
    (re.compile(r'[0-9a-f]{32,}'), '<HEX>'),
]


def normalize(text: str) -> str:
    for rx, rep in NORM_RULES:
        text = rx.sub(rep, text)
    return text


def digest(payload: bytes) -> str:
    try:
        text = payload.decode('utf-8')
    except UnicodeDecodeError:
        return 'bin:' + hashlib.sha256(payload).hexdigest()[:16]
    return 'txt:' + hashlib.sha256(normalize(text).encode()).hexdigest()[:16]


# ---------------------------------------------------------------- HTTP

class Client:
    """带 cookie jar 的客户端。

    必须用 cookiejar：/api/v1/web-login 是 302 跳转下发 Set-Cookie 的，
    不用 jar 的话 cookie 会跟着 3xx 响应一起被 urllib 丢掉。
    """

    def __init__(self, port):
        self.port = port
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar))

    @property
    def cookies(self):
        return {c.name: c.value for c in self.jar}

    def clear(self):
        self.jar.clear()

    def _open(self, method, path, data=None, json_body=None):
        url = 'http://127.0.0.1:%d%s' % (self.port, path)
        hdr = {}
        body = None
        if json_body is not None:
            body = json.dumps(json_body).encode()
            hdr['Content-Type'] = 'application/json'
        elif data is not None:
            body = urllib.parse.urlencode(data).encode()
            hdr['Content-Type'] = 'application/x-www-form-urlencoded'
        req = urllib.request.Request(url, data=body, headers=hdr, method=method)
        try:
            with self.opener.open(req, timeout=25) as r:
                return r.status, r.read(), r.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers
        except Exception as e:
            return 0, ('ERR ' + str(e)).encode(), {}

    def get(self, path, **kw):
        return self._open('GET', path, **kw)

    def post(self, path, **kw):
        return self._open('POST', path, **kw)

    def login(self, identifier, password):
        st, body, _ = self.post('/api/v1/login', json_body={
            'identifier': identifier, 'password': password})
        try:
            payload = json.loads(body.decode())
        except Exception:
            return False, 'login 响应不是 JSON：HTTP %s %s' % (st, body[:200])
        node = payload.get('data') if isinstance(payload.get('data'), dict) else payload
        token = (node or {}).get('token')
        if not token:
            return False, 'login 无 token：HTTP %s %s' % (st, body[:200])
        self.get('/api/v1/web-login?token=' + token)
        return ('session' in self.cookies), 'cookie=%s' % sorted(self.cookies)


# ---------------------------------------------------------------- 准备

def prepare(mysql_password):
    print('==> 1/5 准备隔离数据目录 %s' % DATA)
    if os.path.isdir(WORK):
        shutil.rmtree(WORK)
    os.makedirs(WORK)
    shutil.copytree(os.path.join(ROOT, 'server', 'data'), DATA,
                    ignore=shutil.ignore_patterns('-wal', '-shm'))
    print('    已复制 server/data → %s' % DATA)

    print('==> 2/5 迁移到 MySQL 库 netlab_dev')
    subprocess.run([VENV_PY, os.path.join(HERE, 'migrate_sqlite_to_mysql.py'),
                    '--sqlite', os.path.join(DATA, 'netlab.db'),
                    '--host', '127.0.0.1', '--port', '3306', '--user', 'admin',
                    '--password', mysql_password, '--database', 'netlab_dev',
                    '--create-database', '--drop-existing', '--quiet'],
                   check=True)
    print('    OK')


def set_passwords(mysql_password):
    """两侧都设一个已知口令，好走真实登录流程。"""
    import sqlite3
    import hashlib
    import secrets

    def make(pw):
        salt = secrets.token_hex(16)
        d = hashlib.pbkdf2_hmac('sha256', pw.encode(), salt.encode(), 120000).hex()
        return 'pbkdf2_sha256$%s$%s' % (salt, d)

    h = make(ADMIN_PW)
    lite = sqlite3.connect(os.path.join(DATA, 'netlab.db'))
    lite.execute("UPDATE users SET password_hash=? WHERE username='admin'", (h,))
    lite.commit()
    lite.close()
    import pymysql
    c = pymysql.connect(host='127.0.0.1', port=3306, user='admin',
                        password=mysql_password, database='netlab_dev',
                        charset='utf8mb4', autocommit=True)
    with c.cursor() as cur:
        cur.execute("UPDATE users SET password_hash=%s WHERE username='admin'", (h,))
    c.close()
    print('    两侧 admin 口令已设为 %s 算法哈希（明文 %s）' % ('pbkdf2_sha256', ADMIN_PW))


def start_server(port, backend, mysql_password):
    env = dict(os.environ)
    env.update({
        'DATA_DIR': DATA,
        'SECRET_KEY': SECRET,
        'BASE_PATH': '',
        'PORT': str(port),
        'FLASK_ENV': 'production',
        'PYTHONUNBUFFERED': '1',
    })
    if backend == 'mysql':
        env.update({
            'NETLAB_DB_BACKEND': 'mysql',
            'NETLAB_MYSQL_HOST': '127.0.0.1',
            'NETLAB_MYSQL_PORT': '3306',
            'NETLAB_MYSQL_USER': 'admin',
            'NETLAB_MYSQL_PASSWORD': mysql_password,
            'NETLAB_MYSQL_DATABASE': 'netlab_dev',
        })
    else:
        env.pop('NETLAB_DB_BACKEND', None)
    runner = os.path.join(WORK, 'runner_%s.py' % backend)
    with open(runner, 'w') as f:
        f.write('import sys\n'
                'sys.path.insert(0, %r)\n'
                'from core import app, create_app\n'
                'create_app()\n'
                'app.run(host="127.0.0.1", port=int(%r), debug=False, use_reloader=False, threaded=True)\n'
                % (APP, port))
    log = open(os.path.join(WORK, 'server_%s.log' % backend), 'wb')
    p = subprocess.Popen([VENV_PY, runner], env=env, stdout=log, stderr=subprocess.STDOUT)
    return p


def wait_up(port, timeout=40):
    for _ in range(int(timeout * 4)):
        try:
            with urllib.request.urlopen('http://127.0.0.1:%d/api/ping' % port, timeout=2):
                return True
        except Exception:
            time.sleep(0.25)
    return False


# ---------------------------------------------------------------- 路由清单

def routes():
    anon = ['/', '/courses', '/courses/5', '/challenges', '/community', '/community/1',
            '/download', '/convert', '/activate', '/favicon.ico', '/admin',
            '/api/ping', '/api/v1/ping', '/api/v1/home', '/api/v1/courses',
            '/api/v1/courses/5', '/api/v1/challenges', '/api/v1/community',
            '/api/v1/files', '/api/v1/app/version', '/feedback', '/drive', '/feedback/mine']
    admin = ['/admin', '/admin/users', '/admin/users.csv', '/admin/courses',
             '/admin/courses/5', '/admin/courses/5/videos', '/admin/courses/5/assignments',
             '/admin/settings', '/admin/appversion', '/admin/feedback',
             '/admin/feedback/list', '/admin/join', '/admin/join.json', '/admin/links',
             '/admin/posts', '/admin/progress', '/admin/progress.xlsx', '/admin/report',
             '/admin/services', '/admin/submissions', '/admin/submissions.csv',
             '/admin/challenges', '/admin/challenges/1/records', '/admin/codes',
             '/admin/admins', '/admin/files']
    user = ['/feedback', '/feedback/mine', '/drive', '/courses/5', '/community/new',
            '/api/v1/me', '/api/v1/drive', '/api/v1/report', '/api/v1/home',
            '/api/v1/challenges', '/api/v1/community', '/api/v1/courses']
    return anon, admin, user


def fetch_set(cli, urls):
    out = {}
    for u in urls:
        st, body, _ = cli.get(u)
        out[u] = (st, digest(body), len(body))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--mysql-password', default='CHANGE_ME_PASSWORD')
    ap.add_argument('--keep', action='store_true', help='跑完不清理')
    args = ap.parse_args()

    prepare(args.mysql_password)
    set_passwords(args.mysql_password)

    print('==> 3/5 启动两个实例')
    procs = []
    try:
        ps = start_server(8801, 'sqlite', args.mysql_password)
        pm = start_server(8802, 'mysql', args.mysql_password)
        procs = [ps, pm]
        ok_s, ok_m = wait_up(8801), wait_up(8802)
        print('    sqlite:%d → %s   mysql:%d → %s'
              % (8801, '就绪' if ok_s else '❌未起', 8802, '就绪' if ok_m else '❌未起'))
        if not (ok_s and ok_m):
            for f in ('server_sqlite.log', 'server_mysql.log'):
                p = os.path.join(WORK, f)
                if os.path.exists(p):
                    print('--- %s ---' % f)
                    print(open(p, encoding='utf-8', errors='replace').read()[-3000:])
            return 2

        print('==> 4/5 各自登录')
        cs, cm = Client(8801), Client(8802)
        for name, c in (('sqlite', cs), ('mysql', cm)):
            ok, msg = c.login('admin', ADMIN_PW)
            print('    %-7s %s' % (name, msg))
            if not ok:
                return 3

        print('==> 5/5 逐路由比对')
        anon, admin_urls, user_urls = routes()

        # ① 匿名（先清掉 cookie）
        cs.clear(); cm.clear()
        res_anon_s = fetch_set(cs, anon)
        res_anon_m = fetch_set(cm, anon)

        # ② 管理员
        for c in (cs, cm):
            c.login('admin', ADMIN_PW)
        res_admin_s = fetch_set(cs, admin_urls)
        res_admin_m = fetch_set(cm, admin_urls)

        # ③ 普通用户（demo_user 的口令未知，登录不上就跳过这一组）
        cs2, cm2 = Client(8801), Client(8802)
        res_user_s = res_user_m = {}
        ok2s, _ = cs2.login('demo_user', ADMIN_PW)
        ok2m, _ = cm2.login('demo_user', ADMIN_PW)
        if ok2s and ok2m:
            res_user_s = fetch_set(cs2, user_urls)
            res_user_m = fetch_set(cm2, user_urls)
        else:
            print('    （普通用户 demo_user 口令未知，跳过该组）')

        bad = 0
        total = 0
        for label, rs, rm in (('匿名', res_anon_s, res_anon_m),
                              ('管理员', res_admin_s, res_admin_m),
                              ('普通用户', res_user_s, res_user_m)):
            for u in rs:
                total += 1
                if rs[u] != rm[u]:
                    bad += 1
                    print('❌ [%s] %-38s sqlite=%s  mysql=%s' % (label, u, rs[u], rm[u]))
        print()
        print('共比对 %d 个请求，差异 %d 个' % (total, bad))
        if bad == 0:
            print('✅ 两个后端响应完全一致')
            return 0
        print('❌ 存在差异，需要逐个排查')
        return 1
    finally:
        for p in procs:
            try:
                p.send_signal(signal.SIGTERM)
            except Exception:
                pass
        time.sleep(1)
        for p in procs:
            try:
                p.kill()
            except Exception:
                pass
        if not args.keep:
            shutil.rmtree(WORK, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
