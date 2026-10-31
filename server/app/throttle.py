"""登录/敏感动作的轻量限流（进程内滑动窗口）。

为什么要它
----------
站点口令目前是明文，且大量账号是弱口令。不设闸门的话，一个脚本可以对
某个账号疯狂试密码。这里用最朴素的办法把它们挡住：

    · 同一个 (来源IP + 账号)      → 5 分钟内最多 8 次
    · 同一个 来源IP              → 5 分钟内最多 120 次

两级设计的原因：学校机房、宿舍楼出口往往共用一个公网 IP。如果只按 IP 限，
一个班 30 个人同时登录就会被误伤。所以「打某一个账号」卡得很紧，
「同一个出口 IP 的大量正常登录」放得比较宽。

已知局限（够用就好，不引入额外依赖）：
    · mod_wsgi daemon 下每个进程各记一份 → 实际阈值会乘以进程数（当前 1 个）
    · 进程重启即清零
真要严格限流得上 Redis / nginx limit_req，那是另一个量级的改造。
"""
from __future__ import annotations

import threading
import time

_LOCK = threading.Lock()
_BUCKETS: dict[str, list[float]] = {}
_MAX_BUCKETS = 20000


def _prune(now: float) -> None:
    """防止被随机 IP 刷爆内存：桶太多时清掉已经空掉的。"""
    if len(_BUCKETS) <= _MAX_BUCKETS:
        return
    for key in [k for k, v in _BUCKETS.items() if not v][: _MAX_BUCKETS // 2]:
        _BUCKETS.pop(key, None)


def retry_after(key: str, limit: int, window: float) -> int:
    """记一次动作。

    返回 0 表示放行；返回 >0 表示需要等这么多秒（调用方应回 429）。
    """
    now = time.time()
    with _LOCK:
        bucket = _BUCKETS.setdefault(key, [])
        # 丢掉窗口之外的记录
        bucket[:] = [t for t in bucket if now - t < window]
        if len(bucket) >= limit:
            return int(window - (now - bucket[0])) + 1
        bucket.append(now)
        _prune(now)
        return 0


def clear(prefix: str) -> None:
    """清掉某前缀的所有计数（例如登录成功后）。"""
    with _LOCK:
        for key in [k for k in _BUCKETS if k.startswith(prefix)]:
            _BUCKETS.pop(key, None)


def client_ip() -> str:
    """取真实来源 IP。

    站点在 Apache mod_wsgi 后面，remote_addr 就是真实对端；
    若以后加了反向代理，X-Forwarded-For 的第一段才是真的。
    """
    from flask import request
    fwd = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    return fwd or (request.environ.get("REMOTE_ADDR") or "-")


# 阈值集中在这里，方便一处调整
LOGIN_PER_ACCOUNT = (8, 300)    # 同一 IP 打同一账号：5 分钟 8 次
LOGIN_PER_IP = (120, 300)       # 同一 IP 所有登录：5 分钟 120 次


def login_gate(identifier: str) -> int:
    """登录前的闸门。返回 0 放行，否则返回应等待的秒数。

    顺序很关键：先查「打这个账号」的桶，再查「这个 IP」的桶。
    """
    ip = client_ip()
    wait = retry_after(f"login:acct:{ip}:{identifier.lower()}", *LOGIN_PER_ACCOUNT)
    if wait:
        return wait
    return retry_after(f"login:ip:{ip}", *LOGIN_PER_IP)


def login_ok(identifier: str) -> None:
    """登录成功 → 清掉这个账号的失败计数（但保留 IP 总计数，防止成功登录洗白）。"""
    clear(f"login:acct:{client_ip()}:{identifier.lower()}")


# 阈值集中在这里，方便一处调整
FORGOT_PER_ACCOUNT = (6, 600)   # 同一 IP 打同一账号的「找回密码」：10 分钟 6 次
FORGOT_PER_IP = (30, 600)       # 同一 IP 所有「找回密码」：10 分钟 30 次


def forgot_gate(identifier: str) -> int:
    """找回密码的闸门。

    比登录卡得更紧：登录失败还有「再想想密码」的余地，而找回密码一旦被脚本刷，
    配合明文口令就等于批量撞库。所以同一账号 10 分钟只给 6 次。
    """
    ip = client_ip()
    wait = retry_after(f"forgot:acct:{ip}:{(identifier or '-').lower()}", *FORGOT_PER_ACCOUNT)
    if wait:
        return wait
    return retry_after(f"forgot:ip:{ip}", *FORGOT_PER_IP)


def forgot_ok(identifier: str) -> None:
    """找回成功 → 清掉该账号的计数。"""
    clear(f"forgot:acct:{client_ip()}:{(identifier or '-').lower()}")

