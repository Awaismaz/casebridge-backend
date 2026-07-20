from django.contrib import admin
from django.urls import path

from apps.accounts import views as auth_views
from apps.cases import analytics as analytics_views
from apps.cases import views as console_views
from apps.clients import views as portal_views
from apps.connectors import views as connector_views
from apps.docintel import views as docintel_views
from apps.engagement import views as engagement_views

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
    path("api/v1/portal/language/", portal_views.set_language),
    path("api/v1/portal/stages/", portal_views.stage_reference),
    path("api/v1/portal/survey/", engagement_views.my_pending_survey),
    path("api/v1/portal/survey/<int:survey_id>/respond/", engagement_views.respond_survey),
    # Firm console (aud=firm-staff)
    path("api/v1/console/dashboard/", console_views.dashboard),
    path("api/v1/console/cases/", console_views.case_list),
    path("api/v1/console/cases/<uuid:case_id>/", console_views.case_detail),
    path("api/v1/console/cases/<uuid:case_id>/messages/", console_views.case_messages),
    path("api/v1/console/cases/<uuid:case_id>/narrative/", analytics_views.case_narrative),
    path("api/v1/console/inbox/", console_views.inbox),
    path("api/v1/console/escalations/", console_views.escalations),
    path("api/v1/console/escalations/<int:esc_id>/action/", console_views.escalation_action),
    path("api/v1/console/settings/", console_views.firm_settings),
    # Console analytics
    path("api/v1/console/sla/", analytics_views.sla_metrics),
    path("api/v1/console/workload/", analytics_views.workload),
    path("api/v1/console/sentiment/", analytics_views.sentiment_queue),
    path("api/v1/console/sentiment/<uuid:message_id>/reviewed/", analytics_views.sentiment_reviewed),
    # Module B — Document Reader
    path("api/v1/console/review-queue/", docintel_views.review_queue),
    path("api/v1/console/docs/<uuid:doc_id>/", docintel_views.doc_detail),
    path("api/v1/console/docs/<uuid:doc_id>/publish/", docintel_views.doc_publish),
    path("api/v1/console/facts/<int:fact_id>/review/", docintel_views.fact_review),
    path("api/v1/console/search/", docintel_views.search),
    path("api/v1/console/analyze/", docintel_views.analyze_text),
    # Engagement — NPS, growth, templates, structured updates
    path("api/v1/console/nps/", engagement_views.nps_dashboard),
    path("api/v1/console/growth/", engagement_views.growth_signals),
    path("api/v1/console/growth/<int:signal_id>/action/", engagement_views.growth_action),
    path("api/v1/console/templates/", engagement_views.templates),
    path("api/v1/console/send-update/", engagement_views.send_update),
    # Connector (CMS sync)
    path("api/v1/connector/events/", connector_views.inbound_events),
    path("api/v1/console/connector/", connector_views.connector_status),
]
