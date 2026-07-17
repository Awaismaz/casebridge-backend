from django.contrib import admin
from django.urls import path

from apps.accounts import views as auth_views
from apps.cases import views as console_views
from apps.clients import views as portal_views
from apps.docintel import views as docintel_views

urlpatterns = [
    path("admin/", admin.site.urls),
    # Health
    path("api/v1/health/", auth_views.health),
    # Auth
    path("api/v1/auth/staff/login/", auth_views.staff_login),
    path("api/v1/auth/client/request-otp/", auth_views.client_request_otp),
    path("api/v1/auth/client/verify-otp/", auth_views.client_verify_otp),
    path("api/v1/auth/demo/", auth_views.demo_login),
    path("api/v1/auth/refresh/", auth_views.refresh_token),
    path("api/v1/me/", auth_views.me),
    # Client portal (aud=portal-client)
    path("api/v1/portal/case/", portal_views.my_case),
    path("api/v1/portal/messages/", portal_views.my_messages),
    path("api/v1/portal/files/", portal_views.my_files),
    path("api/v1/portal/notifications/", portal_views.my_notifications),
    path("api/v1/portal/notifications/read/", portal_views.mark_notifications_read),
    path("api/v1/portal/consent/", portal_views.grant_consent),
    path("api/v1/portal/stages/", portal_views.stage_reference),
    # Firm console (aud=firm-staff)
    path("api/v1/console/dashboard/", console_views.dashboard),
    path("api/v1/console/cases/", console_views.case_list),
    path("api/v1/console/cases/<uuid:case_id>/", console_views.case_detail),
    path("api/v1/console/cases/<uuid:case_id>/messages/", console_views.case_messages),
    path("api/v1/console/inbox/", console_views.inbox),
    path("api/v1/console/escalations/", console_views.escalations),
    path("api/v1/console/escalations/<int:esc_id>/action/", console_views.escalation_action),
    path("api/v1/console/settings/", console_views.firm_settings),
    # Module B review queue
    path("api/v1/console/review-queue/", docintel_views.review_queue),
    path("api/v1/console/docs/<uuid:doc_id>/", docintel_views.doc_detail),
    path("api/v1/console/docs/<uuid:doc_id>/publish/", docintel_views.doc_publish),
    path("api/v1/console/facts/<int:fact_id>/review/", docintel_views.fact_review),
    path("api/v1/console/search/", docintel_views.search),
]
