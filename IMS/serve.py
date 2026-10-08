"""
Production entry point: serves the IMS Django app with Waitress.

Usage:
    python serve.py

Host, port and threads come from WAITRESS_HOST, WAITRESS_PORT and WAITRESS_THREADS in
IMS/local_settings.py. Environment variables of the same name override them:
    WAITRESS_HOST     (default 0.0.0.0)
    WAITRESS_PORT     (default 8000)
    WAITRESS_THREADS  (default 8)

The process id is written to serve.pid so update.bat can restart the server after a git pull.
"""

import os
from pathlib import Path

from waitress import serve

from IMS.wsgi import application
from django.conf import settings

PID_FILE = Path(__file__).resolve().parent / 'serve.pid'

if __name__ == '__main__':
    host = os.environ.get('WAITRESS_HOST', getattr(settings, 'WAITRESS_HOST', '0.0.0.0'))
    port = int(os.environ.get('WAITRESS_PORT', getattr(settings, 'WAITRESS_PORT', 8000)))
    threads = int(os.environ.get('WAITRESS_THREADS', getattr(settings, 'WAITRESS_THREADS', 8)))

    PID_FILE.write_text(str(os.getpid()))
    print(f'Serving IMS on http://{host}:{port} with {threads} threads (pid {os.getpid()})')
    try:
        serve(application, host=host, port=port, threads=threads)
    finally:
        PID_FILE.unlink(missing_ok=True)
