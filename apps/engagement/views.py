"""Engagement endpoints: NPS surveys, growth signals (referral/review/household),
structured update templates, and the 'proactive bad news' send flow."""

from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.authentication import IsFirmStaff, IsPortalClient
from apps.billing.models import ValueEvent
from apps.cases.models import PortalCase
from apps.messaging.models import Message, Notification, Thread

from .models import GrowthSignal, NpsSurvey, UpdateTemplate


# ---------------------------------------------------------------------------
# NPS — client side
# ---------------------------------------------------------------------------

@api_view(["GET"])
@permission_classes([IsPortalClient])
def my_pending_survey(request):
    survey = (
        NpsSurvey.objects.filter(client_id=request.user.id, responded_at__isnull=True)
        .order_by("-sent_at")
        .first()
    )
    if survey is None:
        return Response({"survey": None})
    return Response({"survey": {"id": survey.id, "trigger": survey.trigger, "sent_at": survey.sent_at.isoformat()}})


@api_view(["POST"])
@permission_classes([IsPortalClient])
def respond_survey(request, survey_id):
    survey = NpsSurvey.objects.filter(id=survey_id, client_id=request.user.id).first()
    if survey is None:
        return Response({"detail": "Not found."}, status=404)
    score = request.data.get("score")
    if score is None or not (0 <= int(score) <= 10):
        return Response({"detail": "score must be 0-10."}, status=400)
    survey.score = int(score)
    survey.comment = (request.data.get("comment") or "")[:2000]
    survey.responded_at = timezone.now()
    survey.save()
    ValueEvent.objects_unscoped.create(
        firm_id=survey.firm_id, module="portal", event_type="nps_response",
        actor_type="client", metadata={"score": survey.score, "category": survey.category},
    )
    # Promoters at settlement → suggest a review/referral to staff
    if survey.category == "promoter":
        for kind in ("review", "referral"):
            GrowthSignal.objects_unscoped.get_or_create(
                firm_id=survey.firm_id, case=survey.case, kind=kind,
                defaults={"detail": f"High NPS ({survey.score}) — good moment to ask."},
            )
    return Response({"ok": True, "category": survey.category})


# ---------------------------------------------------------------------------
# NPS — staff side
# ---------------------------------------------------------------------------

@api_view(["GET"])
@permission_classes([IsFirmStaff])
def nps_dashboard(request):
    surveys = NpsSurvey.objects.select_related("case", "client").all()
    responded = [s for s in surveys if s.score is not None]
    promoters = sum(1 for s in responded if s.category == "promoter")
    detractors = sum(1 for s in responded if s.category == "detractor")
    nps = round(100 * (promoters - detractors) / len(responded)) if responded else None
    return Response(
        {
            "nps": nps,
            "responses": len(responded),
            "sent": surveys.count(),
            "promoters": promoters,
            "passives": len(responded) - promoters - detractors,
            "detractors": detractors,
            "recent": [
                {
                    "id": s.id,
                    "client_name": s.client.name,
                    "case_title": s.case.title,
                    "score": s.score,
                    "category": s.category,
                    "comment": s.comment,
                    "responded_at": s.responded_at.isoformat() if s.responded_at else None,
                }
                for s in sorted(responded, key=lambda s: s.responded_at or timezone.now(), reverse=True)[:15]
            ],
        }
    )


# ---------------------------------------------------------------------------
# Growth signals
# ---------------------------------------------------------------------------

@api_view(["GET"])
@permission_classes([IsFirmStaff])
def growth_signals(request):
    items = (
        GrowthSignal.objects.select_related("case", "case__client")
        .exclude(status="dismissed")
        .order_by("-created_at")[:50]
    )
    return Response(
        {
            "signals": [
                {
                    "id": g.id,
                    "kind": g.kind,
                    "status": g.status,
                    "detail": g.detail,
                    "case_id": str(g.case_id),
                    "case_title": g.case.title,
                    "client_name": g.case.client.name,
                    "created_at": g.created_at.isoformat(),
                }
                for g in items
            ]
        }
    )


@api_view(["POST"])
@permission_classes([IsFirmStaff])
def growth_action(request, signal_id):
    g = GrowthSignal.objects.filter(id=signal_id).first()
    if g is None:
        return Response({"detail": "Not found."}, status=404)
    action = request.data.get("action")
    if action in ("sent", "converted", "dismissed"):
        g.status = action
        g.actioned_by = request.user
        g.save()
        return Response({"ok": True, "status": g.status})
    return Response({"detail": "action must be sent|converted|dismissed"}, status=400)


# ---------------------------------------------------------------------------
# Structured update templates + 'bad news' send
# ---------------------------------------------------------------------------

@api_view(["GET"])
@permission_classes([IsFirmStaff])
def templates(request):
    tpls = UpdateTemplate.objects.all()
    return Response(
        {
            "templates": [
                {"id": t.id, "kind": t.kind, "title": t.title, "body": t.body}
                for t in tpls
            ]
        }
    )


@api_view(["POST"])
@permission_classes([IsFirmStaff])
def send_update(request):
    """Send a structured proactive update to the client (portal message +
    notification). Powers the 'bad news' protocol — delivering delays/setbacks
    with a consistent, empathetic script instead of silence."""
    case = PortalCase.objects.filter(id=request.data.get("case_id")).first()
    if case is None:
        return Response({"detail": "Case not found."}, status=404)
    body = (request.data.get("body") or "").strip()
    kind = request.data.get("kind", "milestone")
    if not body:
        return Response({"detail": "body required."}, status=400)
    thread, _ = Thread.objects.get_or_create(case=case, defaults={"firm_id": case.firm_id})
    msg = Message.objects_unscoped.create(
        firm_id=case.firm_id, thread=thread, sender_type="staff",
        sender_staff=request.user, sender_name=request.user.get_full_name(), body=body,
    )
    Notification.objects_unscoped.create(
        firm_id=case.firm_id, case=case, kind="message",
        title=f"Update from {request.user.get_full_name()}", body=body[:200],
    )
    case.last_firm_touch_at = timezone.now()
    case.save(update_fields=["last_firm_touch_at"])
    case.escalations.filter(status="open").update(status="resolved", resolved_at=timezone.now())
    ValueEvent.objects_unscoped.create(
        firm_id=case.firm_id, module="portal", event_type="structured_update_sent",
        actor_type="staff", metadata={"kind": kind},
    )
    return Response({"ok": True, "message_id": str(msg.id)}, status=201)
