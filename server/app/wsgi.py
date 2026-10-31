"""gunicorn 入口：wsgi:app

本地开发直接跑：  python wsgi.py
"""
import os

from core import app, create_app

create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), debug=True)
