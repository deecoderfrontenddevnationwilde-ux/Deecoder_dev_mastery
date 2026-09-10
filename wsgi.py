"""
PythonAnywhere WSGI entry point.

1. Point your Web app WSGI file to this module, OR paste the path setup below
   into the WSGI file PythonAnywhere generates.

2. Set production secrets in the PythonAnywhere Web tab → Environment variables
   (or in the WSGI file using os.environ.setdefault — never commit real passwords):

     MAIL_SERVER=smtp.gmail.com
     MAIL_PORT=587
     MAIL_USE_TLS=1
     MAIL_USERNAME=deecoderfrontenddevnationwide@gmail.com
     MAIL_FROM=deecoderfrontenddevnationwide@gmail.com
     MAIL_PASSWORD=<Gmail App Password>

   Do NOT put the real App Password in Git. Set it only on the host.

3. Reload the web app after changing environment variables.
"""
import os
import sys
from pathlib import Path

# --- project on sys.path (adjust if your PA path differs) ---
PROJECT_DIR = Path(__file__).resolve().parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

# Optional: set production env here ONLY if the dashboard cannot.
# Prefer the PythonAnywhere "Environment variables" UI.
# Example (leave commented in Git):
# os.environ.setdefault("MAIL_SERVER", "smtp.gmail.com")
# os.environ.setdefault("MAIL_PORT", "587")
# os.environ.setdefault("MAIL_USE_TLS", "1")
# os.environ.setdefault("MAIL_USERNAME", "deecoderfrontenddevnationwide@gmail.com")
# os.environ.setdefault("MAIL_FROM", "deecoderfrontenddevnationwide@gmail.com")
# os.environ.setdefault("MAIL_PASSWORD", "")  # set real value on the server only

# Import after path + env setup so app.py sees production variables
from app import app as application  # noqa: E402  (PythonAnywhere expects `application`)
