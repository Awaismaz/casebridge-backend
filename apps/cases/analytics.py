"""Console analytics endpoints: response-time SLA, case-manager workload,
sentiment review queue, and on-demand case narrative."""

from datetime import timedelta

from django.db.models import Count
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.authentication import IsFirmStaff
from apps.accounts.models import StaffUser
from apps.billing.models import ValueEvent
from apps.messaging.models import Message

from .models import PortalCase
from .serializers import case_summary_json


def _avg_first_response_hours(firm_id, since):
    """Average hours between a client message and the next staff reply in the
    same thread, over the window."""
    client_msgs = (
        Message.objects.filter(sender_type="client", created_at__gte=since)
        .select_related("thread")
        .order_by("created_at")
    )
    deltas = []
    for cm in client_msgs:
        reply = (
            Message.objects.filter(
                thread_id=cm.thread_id, sender_type="staff", created_at__gt=cm.created_at
            )
            .order_by("created_at")
            .first()
        )
        if reply:
            deltas.append((reply.created_at - cm.created_at).total_seconds() / 3600.0)
    if not deltas:
        return None
    return round(sum(deltas) / len(deltas), 1)


@api_view(["GET"])
@permission_classes([IsFirmStaff])
def sla_metrics(request):
    """Response-time SLA: median/avg first response, % within target, trend."""
    firm = request.user.firm
    now = timezone.now()
    target_hours = int(firm.settings.get("response_target_hours", 24))
    since = now - timedelta(days=30)

    avg = _avg_first_response_hours(firm.id, since)
    # Within-target rate
    client_msgs = Message.objects.filter(sender_type="client", created_at__gte=since)
    total, within = 0, 0
    for cm in client_msgs.select_related("thread"):
        reply = (
            Message.objects.filter(
                thread_id=cm.thread_id, sender_type="staff", created_at__gt=cm.created_at
            )
            .order_by("created_at")
            .first()
        )
        if reply:
            total += 1
            if (reply.created_at - cm.created_at).total_seconds() / 3600.0 <= target_hours:
                within += 1
    return Response(
        {
            "avg_first_response_hours": avg,
            "target_hours": target_hours,
            "within_target_pct": round(100 * within / total) if total else None,
            "responded": total,
            "window_days": 30,
        }
    )


@api_view(["GET"])
@permission_classes([IsFirmStaff])
def workload(request):
    """Active client/case load per case manager + cadence compliance."""
    now = timezone.now()
    threshold = request.user.firm.escalation_threshold_days
    # Scope to THIS firm's staff — StaffUser is not a TenantModel, so filter explicitly.
    staff = StaffUser.objects.filter(
        firm=request.user.firm, is_active=True
    ).exclude(role="admin")
    rows = []
    for u in staff:
        cases = PortalCase.objects.filter(point_of_contact=u, status="open")
        total = cases.count()
        if total == 0 and u.role == "intake":
            # still show intake specialists with 0
            pass
        out = sum(1 for c in cases if c.days_since_touch > threshold)
        rows.append(
            {
                "id": u.id,
                "name": u.get_full_name() or u.email,
                "title": u.title,
                "role": u.role,
                "avatar_color": u.avatar_color,
                "active_cases": total,
                "out_of_cadence": out,
                "in_cadence_pct": round(100 * (total - out) / total) if total else 100,
            }
        )
    rows.sort(key=lambda r: r["active_cases"], reverse=True)
    return Response({"managers": rows, "cadence_threshold_days": threshold})


@api_view(["GET"])
@permission_classes([IsFirmStaff])
def sentiment_queue(request):
    """Client messages flagged negative, awaiting manager review."""
    msgs = (
        Message.objects.filter(sender_type="client", sentiment_flagged=True, sentiment_reviewed_at__isnull=True)
        .select_related("thread", "thread__case", "thread__case__client")
        .order_by("-created_at")[:50]
    )
    items = []
    for m in msgs:
        case = m.thread.case
        items.append(
            {
                "message_id": str(m.id),
                "case_id": str(case.id),
                "case_title": case.title,
                "client_name": case.client.name,
                "body": m.body,
                "sentiment": m.sentiment,
                "created_at": m.created_at.isoformat(),
            }
        )
    return Response({"flagged": items})


@api_view(["POST"])
@permission_classes([IsFirmStaff])
def sentiment_reviewed(request, message_id):
    m = Message.objects.filter(id=message_id).first()
    if m is None:
        return Response({"detail": "Not found."}, status=404)
    m.sentiment_reviewed_at = timezone.now()
    m.save(update_fields=["sentiment_reviewed_at"])
    return Response({"ok": True})


@api_view(["GET", "POST"])
@permission_classes([IsFirmStaff])
def case_narrative(request, case_id):
    """GET the stored narrative; POST regenerates it from the case timeline."""
    from casebridge import ai

    from apps.cases.models import CANONICAL_STAGES
    from apps.docintel.models import CaseNarrative

    case = PortalCase.objects.filter(id=case_id).select_related("client").first()
    if case is None:
        return Response({"detail": "Case not found."}, status=404)
    narrative, _ = CaseNarrative.objects.get_or_create(case=case, defaults={"firm_id": case.firm_id})

    if request.method == "POST":
        events = [
            {"date": t.date.isoformat(), "title": t.title, "description": t.description}
            for t in case.timeline.all()
        ]
        result = ai.generate_narrative(
            case.title, dict(CANONICAL_STAGES)[case.canonical_stage], events
        )
        narrative.text = result["text"]
        narrative.ai_generated = result["ai"]
        narrative.version += 1
        narrative.generated_at = timezone.now()
        narrative.save()
        ValueEvent.objects_unscoped.create(
            firm_id=case.firm_id, module="reader", event_type="narrative_generated",
            actor_type="staff", metadata={"ai": result["ai"]},
        )

    return Response(
        {
            "text": narrative.text,
            "version": narrative.version,
            "ai_generated": narrative.ai_generated,
            "generated_at": narrative.generated_at.isoformat() if narrative.generated_at else None,
        }
    )
