#!/usr/bin/env python3
"""Start the study tools:  python3 run.py   (add --no-open to keep the browser closed)."""
import sys
import threading
import webbrowser

from app import create_app

app = create_app()

if __name__ == "__main__":
    port = app.config["PORT"]
    url = f"http://localhost:{port}"
    print(f"学习工具已启动: {url}   (Ctrl+C 停止)")
    if "--no-open" not in sys.argv:
        threading.Timer(0.8, webbrowser.open, [url]).start()
    app.run(host="127.0.0.1", port=port, debug=False)
