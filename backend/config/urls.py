from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.db import connection
from django.http import JsonResponse
from django.urls import include, path


def health(request):
    """Liveness + database check: GET /api/health/"""
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
        return JsonResponse({'status': 'ok', 'database': 'ok'})
    except Exception:
        return JsonResponse({'status': 'error', 'database': 'unreachable'}, status=503)


urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/health/', health, name='health'),
    path('api/auth/', include('accounts.urls')),
    path('api/', include('hotels.urls')),
    path('api/', include('bookings.urls')),
    path('api/ai/', include('assistant.urls')),
    path('api/', include('dashboards.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
