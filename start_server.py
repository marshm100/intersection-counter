import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uvicorn
uvicorn.run("backend.app:app", host="127.0.0.1", port=5000, reload=True)
