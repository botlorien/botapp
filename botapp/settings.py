import os
from dotenv import load_dotenv

load_dotenv()
DEBUG = True

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SECRET_KEY = os.getenv("BOTAPP_SECRET_KEY", 'chave-super-secreta-para-dev')
ALLOWED_HOSTS = eval(os.getenv("BOTAPP_ALLOWED_HOSTS", "['*']"))
PORT_ADMIN = os.getenv("BOTAPP_PORT_ADMIN", 8000)
DATABASE_SCHEMA = os.getenv("PG_BOTAPP_SCHEMA", 'botapp_schema')


INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rangefilter',
    'botapp',
]

ROOT_URLCONF = 'botapp.urls'


# settings.py
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',  # ❗ ESTA LINHA ESTAVA FALTANDO
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
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',  # ✅ ESSENCIAL!
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],  # ou você pode adicionar seus templates personalizados aqui
        'APP_DIRS': True,  # ✅ ESSENCIAL para o admin funcionar
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',  # ✅ NECESSÁRIO pro admin funcionar
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]


DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

STATIC_URL = '/static/'

STATICFILES_DIRS = [
    os.path.join(BASE_DIR, "static"),
]

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.getenv('BOTAPP_EMAIL_HOST')
EMAIL_PORT = os.getenv('BOTAPP_EMAIL_PORT', 587)  # Porta padrão para TLS
EMAIL_HOST_USER = os.getenv('BOTAPP_EMAIL_USER')
EMAIL_HOST_PASSWORD = os.getenv('BOTAPP_EMAIL_PASSWORD')
EMAIL_USE_TLS = os.getenv('BOTAPP_EMAIL_USE_TLS', 'True') == 'True'
DEFAULT_FROM_EMAIL = os.getenv('BOTAPP_DEFAULT_FROM_EMAIL', EMAIL_HOST_USER)