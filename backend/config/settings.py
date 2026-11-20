"""
Django settings for the LuminaStay backend.

All secrets and environment-specific values are read from backend/.env
(see .env.example). Nothing sensitive is hard-coded here.
"""

from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_ALLOWED_HOSTS=(list, ['localhost', '127.0.0.1']),
    CORS_ALLOWED_ORIGINS=(list, []),
    DB_HOST=(str, 'localhost'),
    DB_PORT=(int, 5432),
    JWT_ACCESS_MINUTES=(int, 60),
    JWT_REFRESH_DAYS=(int, 7),
    BACKEND_PUBLIC_URL=(str, 'http://localhost:8001'),
    AI_PROVIDER=(str, ''),
    OPENAI_API_KEY=(str, ''),
    OPENAI_MODEL=(str, 'gpt-5.4-mini'),
    OPENAI_EMBEDDING_MODEL=(str, 'text-embedding-3-small'),
    ANTHROPIC_API_KEY=(str, ''),
    AI_MODEL=(str, 'claude-opus-5-5'),
    AI_EFFORT=(str, 'medium'),
    AI_RATE_ANON=(str, '10/min'),
    AI_RATE_USER=(str, '30/min'),
)
environ.Env.read_env(BASE_DIR / '.env')

SECRET_KEY = env('DJANGO_SECRET_KEY')
DEBUG = env('DJANGO_DEBUG')
ALLOWED_HOSTS = env('DJANGO_ALLOWED_HOSTS')


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Third party
    'rest_framework',
    'rest_framework_simplejwt',
    'corsheaders',
    'django_filters',
    # Local
    'accounts',
    'hotels',
    'bookings',
    'assistant',
    'dashboards',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# Database — PostgreSQL, credentials from .env

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': env('DB_NAME'),
        'USER': env('DB_USER'),
        'PASSWORD': env('DB_PASSWORD'),
        'HOST': env('DB_HOST'),
        'PORT': env('DB_PORT'),
    }
}


# Auth

AUTH_USER_MODEL = 'accounts.User'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# Internationalization

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Dhaka'
USE_I18N = True
USE_TZ = True


# Static files

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Uploaded files (hotel photos). Served by Django only in DEBUG; use a web server or object storage in production.
MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'
BACKEND_PUBLIC_URL = env('BACKEND_PUBLIC_URL')  # base for absolute photo URLs outside a request
HOTEL_PHOTO_MAX_BYTES = 5 * 1024 * 1024
HOTEL_PHOTO_MAX_COUNT = 20
DATA_UPLOAD_MAX_MEMORY_SIZE = 6 * 1024 * 1024

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# Django REST Framework

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticatedOrReadOnly',
    ],
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    # Only the AI chat endpoint is throttled (it costs money per request)
    'DEFAULT_THROTTLE_RATES': {
        'assistant_anon': env('AI_RATE_ANON'),
        'assistant_user': env('AI_RATE_USER'),
    },
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=env('JWT_ACCESS_MINUTES')),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=env('JWT_REFRESH_DAYS')),
    'AUTH_HEADER_TYPES': ('Bearer',),
}


# AI travel assistant. Provider is OpenAI or Anthropic (Claude), picked by AI_PROVIDER or,
# if unset, by whichever API key is configured (OpenAI first). Without a key the chat
# falls back to rule-based database search. The SDKs read their keys from the environment.

AI_PROVIDER = env('AI_PROVIDER') or (
    'openai' if env('OPENAI_API_KEY') else 'anthropic' if env('ANTHROPIC_API_KEY') else ''
)
AI_ASSISTANT_ENABLED = AI_PROVIDER in ('openai', 'anthropic')
OPENAI_MODEL = env('OPENAI_MODEL')
OPENAI_EMBEDDING_MODEL = env('OPENAI_EMBEDDING_MODEL')
SEMANTIC_SEARCH_ENABLED = bool(env('OPENAI_API_KEY'))
AI_MODEL = env('AI_MODEL')
AI_EFFORT = env('AI_EFFORT')


# CORS — allow the Vite frontend

CORS_ALLOWED_ORIGINS = env('CORS_ALLOWED_ORIGINS')

# In development Vite may pick another port (5174, 5175, ...) when 5173 is busy
if DEBUG:
    CORS_ALLOWED_ORIGIN_REGEXES = [r'^http://(localhost|127\.0\.0\.1):\d+$']
