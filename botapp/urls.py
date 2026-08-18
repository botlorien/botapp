from django.contrib import admin
from django.urls import path, include
from . import views
from . import ci_views
from . import sso_views
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
    # SSO de entrada por OTT (opt-in via BOTAPP_SSO_SECRET; ver sso_views).
    path('sso/', sso_views.sso_login, name='botapp_sso'),
    path('sw.js', views.sw_js, name='sw_js'),
    path('favicon.ico', views.favicon_ico, name='favicon_ico'),
    path('api/', include(router.urls)),
    path('admin/', admin.site.urls),
    path('bots/', views.bot_list, name='bot_list'),
    path('bots/<int:bot_id>/', views.bot_detail, name='bot_detail'),
    path('log/<int:log_id>/', views.log_detail, name='log_detail'),
    path('bot/<int:bot_id>/toggle-status/', views.toggle_bot_status, name='toggle_bot_status'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('alerts/', views.alert_list, name='alert_list'),
    path('alerts/<int:alert_id>/ack/', views.alert_acknowledge, name='alert_acknowledge'),
    path('alerts/<int:alert_id>/resolve/', views.alert_resolve, name='alert_resolve'),
    path('alerts/unread-count/', views.alerts_unread_count, name='alerts_unread_count'),
    path('maintenance/cleanup-orphans/', views.cleanup_orphans_action, name='cleanup_orphans'),
    path('maintenance/silence-thresholds/', views.silence_thresholds_page, name='silence_thresholds'),
    path('bots/bulk-silence-threshold/', views.bulk_set_silence_threshold, name='bulk_set_silence_threshold'),
    path('explore/', views.explore, name='explore'),

    # ── Integração de CI (só ativa com BOTAPP_CI_ENABLED=true) ─────────────
    path('ci/', ci_views.ci_overview, name='ci_overview'),
    path('ci/connections/', ci_views.connection_list, name='ci_connections'),
    path('ci/connections/<int:connection_id>/test/', ci_views.connection_test,
         name='ci_connection_test'),
    path('ci/connections/<int:connection_id>/sync/', ci_views.connection_sync,
         name='ci_connection_sync'),
    path('ci/projects/', ci_views.project_list, name='ci_projects'),
    path('ci/projects/<int:project_id>/', ci_views.project_detail,
         name='ci_project_detail'),
    path('ci/projects/<int:project_id>/toggle/', ci_views.project_toggle,
         name='ci_project_toggle'),
    path('ci/projects/<int:project_id>/link-bot/', ci_views.project_link_bot,
         name='ci_project_link_bot'),
    path('ci/projects/<int:project_id>/archive/', ci_views.project_archive,
         name='ci_project_archive'),
    path('ci/bots/<int:bot_id>/bind/', ci_views.bind_from_bot,
         name='ci_bind_from_bot'),
    path('ci/pipelines/<int:pipeline_id>/', ci_views.pipeline_detail,
         name='ci_pipeline_detail'),
    path('ci/jobs/<int:job_id>/log/', ci_views.job_log, name='ci_job_log'),
    path('ci/jobs/<int:job_id>/excerpt/', ci_views.job_log_excerpt,
         name='ci_job_excerpt'),
    path('explore/export.csv', views.explore_export_csv, name='explore_export_csv'),
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