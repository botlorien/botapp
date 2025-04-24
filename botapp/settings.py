import os
import json
from dotenv import load_dotenv

load_dotenv()
DEBUG = os.getenv('BOTAPP_DEBUG', 'False').lower() == 'true'

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
print(f"BASE_DIR: {BASE_DIR}")
print(f"DEBUG: {DEBUG}")

SECRET_KEY = os.getenv("BOTAPP_SECRET_KEY", 'chave-super-secreta-para-dev')

if not DEBUG and SECRET_KEY == 'chave-super-secreta-para-dev':
    raise Exception("SECRET_KEY fraco em produção!")

ALLOWED_HOSTS = os.getenv("BOTAPP_ALLOWED_HOSTS", '*').split(',')
PORT_ADMIN = os.getenv("BOTAPP_PORT_ADMIN", 8000)
DATABASE_SCHEMA = os.getenv("PG_BOTAPP_SCHEMA", 'botapp_schema')

if not DEBUG:
    CSRF_TRUSTED_ORIGINS = os.getenv("BOTAPP_CSRF_TRUSTED_ORIGINS", "").split(',')


INSTALLED_APPS = [
    'whitenoise.runserver_nostatic',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rangefilter',
    'rest_framework',
    'botapp',
]

ROOT_URLCONF = 'botapp.urls'


# settings.py
DATABASES: str | dict | None = os.getenv('BOTAPP_DATABASES')
if DATABASES:
    try:
        # NUNCA use eval com input externo!
        DATABASES = json.loads(DATABASES)  # ✅ mais seguro
    except json.JSONDecodeError:
        print("DATABASES inválido")

        DATABASES = None
if not DATABASES:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ.get('PG_BOTAPP_DBNAME'),      # nome do banco
            'USER':  os.environ.get('PG_BOTAPP_USER'),        # seu usuário do Postgres
            'PASSWORD':  os.environ.get('PG_BOTAPP_PASSWORD'),      # sua senha
            'HOST':  os.environ.get('PG_BOTAPP_HOST'),          # ou IP do servidor
            'PORT':  os.environ.get('PG_BOTAPP_PORT'),               # porta padrão do Postgres
            'OPTIONS': {
                'options': f'-c search_path={DATABASE_SCHEMA}'
            }
        }
    }

MIDDLEWARE = [
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'botapp.middleware.rate_limit_middleware.RateLimitMiddleware',
    #'botapp.middleware.csp.CSPMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.BasicAuthentication',
    ],
}


DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.getenv('BOTAPP_EMAIL_HOST')
EMAIL_PORT = os.getenv('BOTAPP_EMAIL_PORT', 587)  # Porta padrão para TLS
EMAIL_HOST_USER = os.getenv('BOTAPP_EMAIL_USER')
EMAIL_HOST_PASSWORD = os.getenv('BOTAPP_EMAIL_PASSWORD')
EMAIL_USE_TLS = os.getenv('BOTAPP_EMAIL_USE_TLS', 'True') == 'True'
DEFAULT_FROM_EMAIL = os.getenv('BOTAPP_DEFAULT_FROM_EMAIL', EMAIL_HOST_USER)

if not DEBUG:
    SECURE_HSTS_SECONDS = 3600
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'  # ou SAMEORIGIN se usar iframe internamente


STATIC_URL = '/static/'

STATICFILES_DIRS = [
    os.path.join(BASE_DIR, "static"),
]

STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/bots/'
LOGOUT_REDIRECT_URL = '/accounts/login/'
