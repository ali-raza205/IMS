# Copy this file to local_settings.py (same folder) on each machine and fill in the values.
# local_settings.py is not in git, so passwords stay on the machine and a `git pull` never overwrites it.

DEBUG = False  # True only on a development machine

SECRET_KEY = 'replace-with-a-long-random-string'
# Generate one with:
#   python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"

ALLOWED_HOSTS = ['192.168.0.64', 'localhost']

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'PDMA_IMS_DB',
        'USER': 'postgres',
        'PASSWORD': 'database-password',
        'HOST': '192.168.0.44',
        'PORT': '5432',
    }
}

# Folder for uploaded transaction pictures and receipts (default: IMS\media). Back it up with the database.
# MEDIA_ROOT = r'D:\IMS_media'

# Address, port and worker threads serve.py uses.
WAITRESS_HOST = '192.168.0.64'
WAITRESS_PORT = 8009
WAITRESS_THREADS = 4
