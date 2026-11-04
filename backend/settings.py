from pathlib import Path
import os
import dj_database_url
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

DEBUG = os.getenv('DEBUG', 'False') == 'True'

SECRET_KEY = os.getenv('SECRET_KEY')
if not SECRET_KEY:
    if not DEBUG:
        raise RuntimeError('SECRET_KEY environment variable is required when DEBUG is off')
    SECRET_KEY = 'dev-only-insecure-key'

ALLOWED_HOSTS = [h.strip() for h in os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',') if h.strip()]
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.getenv('CSRF_TRUSTED_ORIGINS', '').split(',') if o.strip()]

INSTALLED_APPS = [
    'corsheaders',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'inot',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'backend.urls'

TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [],
    'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.request',
        'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
    ]},
}]

WSGI_APPLICATION = 'backend.wsgi.application'

DATABASES = {
    'default': dj_database_url.config(
        default=f'sqlite:///{BASE_DIR / "db.sqlite3"}',
        conn_max_age=600,
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'ro'
TIME_ZONE = 'Europe/Bucharest'
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}

_cors = os.getenv('CORS_ALLOWED_ORIGINS', 'http://localhost:8000,http://127.0.0.1:8000,http://localhost:5500,http://127.0.0.1:5500')
CORS_ALLOWED_ORIGINS = [o.strip() for o in _cors.split(',') if o.strip()]

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (),
    'DEFAULT_PERMISSION_CLASSES': ('rest_framework.permissions.AllowAny',),
    'DEFAULT_RENDERER_CLASSES': ('rest_framework.renderers.JSONRenderer',),
}

# Email (Resend, ca la med487)
EMAIL_BACKEND = 'anymail.backends.resend.EmailBackend'
ANYMAIL = {'RESEND_API_KEY': os.getenv('RESEND_API_KEY', '')}
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'onboarding@resend.dev')
EMAIL_ADMIN = os.getenv('EMAIL_ADMIN', '')
EMAIL_TIMEOUT = 10
if DEBUG and not os.getenv('RESEND_API_KEY'):
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# Cache local, necesar pentru limitarea cererilor (rate limit)
CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
RATELIMIT_USE_CACHE = 'default'

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_CONTENT_TYPE_NOSNIFF = True
