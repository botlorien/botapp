import os
import json
import logging
from dotenv import load_dotenv

load_dotenv()
DEBUG = os.getenv('BOTAPP_DEBUG', 'False').lower() == 'true'

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
logging.getLogger('botapp.settings').debug(
    "loaded settings BASE_DIR=%s DEBUG=%s", BASE_DIR, DEBUG,
)

SECRET_KEY = os.getenv("BOTAPP_SECRET_KEY", 'chave-super-secreta-para-dev')

# Check de SECRET_KEY só faz sentido no dashboard (contexto web com sessions,
# CSRF, tokens assinados). RPAs em modo standalone fazem django.setup() para
# usar o ORM e herdam este settings — mas não tocam em nada que dependa do
# SECRET_KEY, então forçar a env só quebra pipeline à toa e espalha a chave
# do dashboard por N robôs, aumentando o blast radius sem ganho de segurança.
#
# Opt-in: o dashboard define BOTAPP_ENFORCE_SECRET_KEY=true no .env.prod.
# Consumidores-biblioteca (RPAs) simplesmente não setam, e aceitam o default
# com um warning no boot quando DEBUG=False.
_ENFORCE_SECRET_KEY = os.getenv("BOTAPP_ENFORCE_SECRET_KEY", "false").lower() == "true"
if SECRET_KEY == 'chave-super-secreta-para-dev':
    if _ENFORCE_SECRET_KEY:
        raise RuntimeError(
            "BOTAPP_SECRET_KEY não pode usar o valor default quando "
            "BOTAPP_ENFORCE_SECRET_KEY=true. Defina a env BOTAPP_SECRET_KEY "
            "no dashboard."
        )
    if not DEBUG:
        logging.getLogger('botapp.settings').warning(
            "BOTAPP_SECRET_KEY usando default em DEBUG=False. Inócuo em modo "
            "SDK/standalone (RPAs não usam sessions/CSRF). No dashboard web, "
            "defina BOTAPP_SECRET_KEY e BOTAPP_ENFORCE_SECRET_KEY=true."
        )

ALLOWED_HOSTS = os.getenv("BOTAPP_ALLOWED_HOSTS", '*').split(',')
PORT_ADMIN = os.getenv("BOTAPP_PORT_ADMIN", 8000)
DATABASE_SCHEMA = os.getenv("PG_BOTAPP_SCHEMA", 'botapp_schema')

if not DEBUG:
    CSRF_TRUSTED_ORIGINS = os.getenv("BOTAPP_CSRF_TRUSTED_ORIGINS", "*").split(',')
    # Não `raise` para não quebrar deploys existentes que dependem do default
    # wildcard — mas alerta visível no boot para o operador configurar.
    # Host-header poisoning: ALLOWED_HOSTS='*' permite reset-password links
    # apontando para domínio do atacante. Em CSRF_TRUSTED_ORIGINS, '*' anula
    # a proteção contra POSTs cross-origin forjados.
    _security_logger = logging.getLogger('botapp.settings')
    if '*' in ALLOWED_HOSTS:
        _security_logger.warning(
            "SEGURANÇA: BOTAPP_ALLOWED_HOSTS='*' em produção (DEBUG=False). "
            "Defina explicitamente os hosts permitidos (ex.: 'botapp.exemplo.com,outro.exemplo.com')."
        )
    if '*' in CSRF_TRUSTED_ORIGINS:
        _security_logger.warning(
            "SEGURANÇA: BOTAPP_CSRF_TRUSTED_ORIGINS='*' em produção. "
            "Defina origens explícitas (ex.: 'https://botapp.exemplo.com')."
        )


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
    # Token auth em paralelo ao Basic. Migration aditiva: cria tabela
    # authtoken_token sem afetar schema existente. Permite migração
    # gradual dos SDKs (Python e Go) sem deprecar Basic imediatamente.
    'rest_framework.authtoken',
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
        # Token vem antes de Basic — quando o cliente enviar Authorization
        # header com formato 'Token <...>', o DRF usa TokenAuthentication;
        # 'Basic <base64>' cai no BasicAuthentication. Ordem não quebra
        # clientes existentes — apenas prioriza o método mais seguro.
        # Classe vive em rest_framework.authentication (não em authtoken/).
        # O app 'rest_framework.authtoken' em INSTALLED_APPS provê apenas o
        # model Token + migrations + admin; a classe de autenticação que
        # valida o header 'Authorization: Token <...>' está aqui:
        'rest_framework.authentication.TokenAuthentication',
        'rest_framework.authentication.BasicAuthentication',
    ],
}


DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.getenv('BOTAPP_EMAIL_HOST')
EMAIL_PORT = os.getenv('BOTAPP_EMAIL_PORT', 587)
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
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')


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

LANGUAGE_CODE = os.getenv('BOTAPP_LANGUAGE_CODE', 'pt-br')     # idioma (legendas, validações de formulários, etc.)
TIME_ZONE = os.getenv('BOTAPP_TIME_ZONE', 'America/Cuiaba')  # fuso-horário para o Brasil
USE_I18N = os.getenv('BOTAPP_USE_I18N', 'True').lower() == 'true'  # internacionalização (i18n)
USE_TZ = os.getenv('BOTAPP_USE_TZ', 'True').lower() == 'true'  # timezone (tz) — default True para notifiers usarem datetimes aware

if not DEBUG:
    CACHES = os.getenv('BOTAPP_CACHES')
    if CACHES:
        try:
            CACHES = json.loads(CACHES)
        except json.JSONDecodeError:
            print("CACHE inválido")

    if not CACHES:
        CACHES: dict = {
            'default': {
                'BACKEND': 'django.core.cache.backends.redis.RedisCache',
                'LOCATION': os.getenv("BOTAPP_REDIS_URL",'redis://botapp_redis:6379/1'),
            }
        }

# LOGGING — apenas afeta modo standalone (quando este settings.py é DJANGO_SETTINGS_MODULE).
# Em modo plugin, o projeto hospedeiro é dono do logging; o SDK só emite via
# getLogger('botapp.*') e um NullHandler adicionado em botapp/__init__.py garante
# que não haja erro caso o host não configure handler algum.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '[%(asctime)s] %(levelname)s %(name)s: %(message)s',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'standard',
        },
    },
    'loggers': {
        'botapp': {
            'handlers': ['console'],
            'level': os.getenv("BOTAPP_LOGGING_LEVEL", 'INFO'),
            'propagate': False,
        },
        'django': {
            'handlers': ['console'],
            'level': os.getenv("BOTAPP_DJANGO_LOG_LEVEL", 'WARNING'),
            'propagate': False,
        },
        'django.request': {
            'handlers': ['console'],
            'level': 'ERROR',
            'propagate': False,
        },
    },
}
