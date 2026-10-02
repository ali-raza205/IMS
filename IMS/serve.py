"""
Production entry point: serves the IMS Django app with Waitress.

Usage:
    python serve.py

Configure with environment variables:
    WAITRESS_HOST     (default 0.0.0.0)
    WAITRESS_PORT     (default 8000)
    WAITRESS_THREADS  (default 8)
"""

import os

from waitress import serve

from IMS.wsgi import application

if __name__ == '__main__':
    host = os.environ.get('WAITRESS_HOST', '0.0.0.0')
    port = int(os.environ.get('WAITRESS_PORT', '8000'))
    threads = int(os.environ.get('WAITRESS_THREADS', '8'))

    print(f'Serving IMS on http://{host}:{port} with {threads} threads')
    serve(application, host=host, port=port, threads=threads)
