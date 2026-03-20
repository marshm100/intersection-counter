import subprocess
import sys
import time
import webview

PORT = 5000

if __name__ == "__main__":
    creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "backend.app:app",
            "--host", "127.0.0.1",
            "--port", str(PORT),
        ],
        creationflags=creation_flags,
    )
    try:
        time.sleep(1.5)  # give uvicorn time to bind before opening window
        webview.create_window(
            "Intersection Counter",
            f"http://127.0.0.1:{PORT}",
            width=1400,
            height=900,
            min_size=(800, 600),
        )
        webview.start()
    finally:
        proc.terminate()
        proc.wait()
