FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    TZ=Asia/Shanghai \
    DATA_DIR=/data

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./

VOLUME ["/data"]
EXPOSE 8000

# 单进程多线程：SQLite 场景下比多进程简单可靠，小站足够用
# timeout 调大：不限上传大小后，传大视频/安装包可能要好几分钟，不能被 120s 掐断
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "8", \
     "--timeout", "1800", "--access-logfile", "-", "wsgi:app"]
