"""课程视频字幕：把管理员上传的 SRT / VTT 统一成 WebVTT 输出。

浏览器 <track> 和安卓 ExoPlayer 都能直接吃 WebVTT；SRT 虽然 ExoPlayer 也认，
但两边格式统一后，网站和 App 的字幕表现才不会各走各的。

只有「转格式」这一件事放在这里，上传/鉴权/落库仍由各蓝图负责。
"""
from __future__ import annotations

import os
import re

from flask import Response

# SRT 时间轴：00:00:01,234 --> 00:00:03,456（分隔符逗号或点都接受）
_SRT_CUE = re.compile(
    r"^\s*(\d{1,3}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*"
    r"(\d{1,3}):(\d{2}):(\d{2})[,.](\d{1,3})\s*(.*)$"
)
_INDEX_LINE = re.compile(r"^\s*\d+\s*$")

SUBTITLE_EXT = {".vtt", ".srt"}


def read_text(path: str) -> str:
    """读字幕文件。字幕多半是 UTF-8，但从 Windows 过来的常带 BOM 或是 GBK。"""
    with open(path, "rb") as f:
        raw = f.read()
    for enc in ("utf-8-sig", "utf-8", "gbk", "utf-16"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _ms(part: str) -> str:
    """毫秒补齐到 3 位：SRT 是毫秒，VTT 也用毫秒，只差分隔符。"""
    return (part + "000")[:3]


def to_vtt(text: str) -> str:
    """SRT / VTT 文本 → WebVTT 文本。已经是 VTT 的原样返回。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    stripped = text.lstrip()
    if stripped.upper().startswith("WEBVTT"):
        return stripped

    out = ["WEBVTT", ""]
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _SRT_CUE.match(line)
        if m:
            hh, mm, ss, ms = m.group(1), m.group(2), m.group(3), m.group(4)
            h2, m2, s2, ms2 = m.group(5), m.group(6), m.group(7), m.group(8)
            rest = m.group(9).strip()
            out.append(
                f"{int(hh):02d}:{mm}:{ss}.{_ms(ms)} --> "
                f"{int(h2):02d}:{m2}:{s2}.{_ms(ms2)}"
                + (f" {rest}" if rest else "")
            )
            i += 1
            continue
        # SRT 的序号行（纯数字，且下一行是时间轴）要丢掉
        if _INDEX_LINE.match(line):
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if _SRT_CUE.match(nxt):
                i += 1
                continue
        out.append(line)
        i += 1

    # 结尾保证有换行，部分播放器对末尾缺换行很敏感
    body = "\n".join(out).rstrip() + "\n"
    return body


def vtt_response(path: str) -> Response:
    """把磁盘上的字幕文件转成 WebVTT 响应。"""
    vtt = to_vtt(read_text(path))
    resp = Response(vtt, mimetype="text/vtt")
    # 字幕会被播放器按秒对齐读取，缓存一天没问题；换文件时文件名也换了
    resp.headers["Cache-Control"] = "private, max-age=86400"
    return resp


def save_subtitle(file_storage, file_dir: str, prefix: str = "sub_"):
    """保存上传的字幕文件，返回 (存储名, 原始名)。"""
    import secrets

    original = os.path.basename(file_storage.filename or "subtitle.vtt")
    ext = os.path.splitext(original)[1].lower()
    if ext not in SUBTITLE_EXT:
        ext = ".vtt"
    stored = f"{prefix}{secrets.token_hex(8)}{ext}"
    file_storage.save(os.path.join(file_dir, stored))
    return stored, original
