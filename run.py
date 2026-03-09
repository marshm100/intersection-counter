import threading
import time
import uvicorn
import webview

PORT = 5000

def _start_server():
    uvicorn.run("backend.app:app", host="127.0.0.1", port=PORT, reload=False)

if __name__ == "__main__":
    threading.Thread(target=_start_server, daemon=True).start()
    time.sleep(1.2)  # give uvicorn time to bind
    webview.create_window(
        "Intersection Counter",
        f"http://127.0.0.1:{PORT}",
        width=1400,
        height=900,
        min_size=(800, 600),
    )
    webview.start()
