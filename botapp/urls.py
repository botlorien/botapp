from django.contrib import admin
from django.urls import path, include
from . import views
from django.contrib.auth.views import LoginView
from django.contrib.auth import views as auth_views
from django.conf.urls.static import static
from django.conf import settings
from django.views.generic.base import RedirectView
from rest_framework.routers import DefaultRouter
from .rest_views import BotViewSet, TaskViewSet, TaskLogViewSet
from django.conf import settings

router = DefaultRouter()
router.register(r'bots', BotViewSet)
router.register(r'tasks', TaskViewSet)
router.register(r'tasklog', TaskLogViewSet)


urlpatterns = [
    path('', RedirectView.as_view(url='/bots/', permanent=False), name='root_redirect'),
    path('api/', include(router.urls)),
    path('admin/', admin.site.urls),
    path('bots/', views.bot_list, name='bot_list'),
    path('bots/<int:bot_id>/', views.bot_detail, name='bot_detail'),
    path('log/<int:log_id>/', views.log_detail, name='log_detail'),
    path('bot/<int:bot_id>/toggle-status/', views.toggle_bot_status, name='toggle_bot_status'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('accounts/login/', LoginView.as_view(), name='login'),
    path('accounts/logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('accounts/password_reset/', auth_views.PasswordResetView.as_view(), name='password_reset'),
    path('accounts/password_reset/done/', auth_views.PasswordResetDoneView.as_view(), name='password_reset_done'),
    path('accounts/reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('accounts/reset/done/', auth_views.PasswordResetCompleteView.as_view(), name='password_reset_complete'),
]
# Servir arquivos estáticos durante o desenvolvimento
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)