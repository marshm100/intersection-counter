import sys
import os

# Ensure the project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uvicorn
from backend.app import app
uvicorn.run(app, host="127.0.0.1", port=5000)
