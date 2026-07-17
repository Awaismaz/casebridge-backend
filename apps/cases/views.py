"""Firm-console endpoints (aud=firm-staff only)."""

from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.authentication import IsFirmStaff
from apps.billing.models import ValueEvent
from apps.docintel.models import DocRecord
from apps.messaging.models import EscalationEvent, Message, Notification, Thread

from .models import CANONICAL_STAGES, STAGE_ORDER, CaseStageEvent, PortalCase
from .serializers import case_summary_json, portal_case_bundle, stage_history_json


@api_view(["GET"])
@permission_classes([IsFirmStaff])
def dashboard(request):
    firm = request.user.firm
    now = timezone.now()
    cases = PortalCase.objects.filter(status="open").select_related(
        "client", "point_of_contact", "attorney"
    )
    threshold = firm.escalation_threshold_days

    stage_counts = {
        row["canonical_stage"]: row["n"]
        for row in cases.values("canonical_stage").annotate(n=Count("id"))
    }
    out_of_cadence = [c for c in cases if c.days_since_touch > threshold]
    open_escalations = EscalationEvent.objects.filter(status="open").count()

    # Response time: staff replies within the last 30 days
    week_ago = now - timedelta(days=7)
    client_msgs = Message.objects.filter(
        sender_type="client", created_at__gte=now - timedelta(days=30)
    ).count()
    docs_this_week = DocRecord.objects.filter(created_at__gte=week_ago).count()
    docs_review = DocRecord.objects.filter(status="in_review").count()
    uploads_week = ValueEvent.objects.filter(
        event_type="evidence_uploaded", created_at__gte=week_ago
    ).count()

    return Response(
        {
            "kpis": {
                "open_cases": cases.count(),
                "in_cadence": cases.count() - len(out_of_cadence),
                "out_of_cadence": len(out_of_cadence),
                "cadence_threshold_days": threshold,
                "open_escalations": open_escalations,
                "client_messages_30d": client_msgs,
                "docs_ingested_7d": docs_this_week,
                "docs_awaiting_review": docs_review,
                "evidence_uploads_7d": uploads_week,
            },
            "stage_distribution": [
                {"stage": key, "label": label, "count": stage_counts.get(key, 0)}
                for key, label in CANONICAL_STAGES
            ],
            "attention": [
                case_summary_json(c)
                for c in sorted(
                    out_of_cadence, key=lambda c: c.days_since_touch, reverse=True
                )[:8]
            ],
        }
    )


@api_view(["GET"])
@permission_classes([IsFirmStaff])
def case_list(request):
    qs = PortalCase.objects.select_related(
        "client", "point_of_contact", "attorney"
    ).all()
    stage = request.GET.get("stage")
    if stage in STAGE_ORDER:
        qs = qs.filter(canonical_stage=stage)
    status_f = request.GET.get("status")
    if status_f in ("open", "closed"):
        qs = qs.filter(status=status_f)
    search = request.GET.get("q")
    if search:
        qs = qs.filter(
            Q(title__icontains=search) | Q(client__name__icontains=search)
        )
    return Response({"cases": [case_summary_json(c) for c in qs[:200]]})


@api_view(["GET", "PATCH"])
@permission_classes([IsFirmStaff])
def case_detail(request, case_id):
    try:
        case = PortalCase.objects.select_related(
            "client", "point_of_contact", "attorney"
        ).get(id=case_id)
    except PortalCase.DoesNotExist:
        return Response({"detail": "Case not found."}, status=404)

    if request.method == "PATCH":
        moved = False
        new_stage = request.data.get("canonical_stage")
        if new_stage and new_stage in STAGE_ORDER and new_stage != case.canonical_stage:
            CaseStageEvent.objects_unscoped.create(
                firm_id=case.firm_id,
                case=case,
                from_stage=case.canonical_stage,
                to_stage=new_stage,
                note=request.data.get("stage_note", ""),
            )
            Notification.objects_unscoped.create(
                firm_id=case.firm_id,
                case=case,
                kind="stage_move",
                title=f"Your case moved to {dict(CANONICAL_STAGES)[new_stage]}",
                body=request.data.get("stage_note", ""),
            )
            case.canonical_stage = new_stage
            moved = True
        if "next_step_note" in request.data:
            case.next_step_note = request.data["next_step_note"]
        if "status" in request.data and request.data["status"] in ("open", "closed"):
            case.status = request.data["status"]
        case.last_firm_touch_at = timezone.now()
        case.save()
        # Touching a case resolves its open escalations
        case.escalations.filter(status="open").update(
            status="resolved", resolved_at=timezone.now()
        )
        if moved:
            ValueEvent.objects_unscoped.create(
                firm_id=case.firm_id,
                module="portal",
                event_type="stage_moved",
                actor_type="staff",
            )

    bundle = portal_case_bundle(case)
    bundle["stage_history"] = stage_history_json(case)
    # Console extras: files + docs summary
    bundle["files"] = [
        {
            "id": str(f.id),
            "filename": f.filename,
            "status": f.status,
            "uploader_type": f.uploader_type,
            "uploader_name": f.uploader_name,
            "size_bytes": f.size_bytes,
            "created_at": f.created_at.isoformat(),
        }
        for f in case.files.all()
    ]
    bundle["docs"] = [
        {
            "id": str(d.id),
            "filename": d.filename,
            "doc_type": d.doc_type,
            "status": d.status,
            "confidence": d.classification_confidence,
            "created_at": d.created_at.isoformat(),
        }
        for d in case.docs.all()
    ]
    return Response(bundle)


@api_view(["GET", "POST"])
@permission_classes([IsFirmStaff])
def case_messages(request, case_id):
    try:
        case = PortalCase.objects.get(id=case_id)
    except PortalCase.DoesNotExist:
        return Response({"detail": "Case not found."}, status=404)
    thread, _ = Thread.objects.get_or_create(case=case, defaults={"firm_id": case.firm_id})

    if request.method == "POST":
        body = (request.data.get("body") or "").strip()
        if not body:
            return Response({"detail": "Message body required."}, status=400)
        msg = Message.objects_unscoped.create(
            firm_id=case.firm_id,
            thread=thread,
            sender_type=Message.SenderType.STAFF,
            sender_staff=request.user,
            sender_name=request.user.get_full_name(),
            body=body,
        )
        case.last_firm_touch_at = timezone.now()
        case.save(update_fields=["last_firm_touch_at"])
        case.escalations.filter(status="open").update(
            status="resolved", resolved_at=timezone.now()
        )
        Notification.objects_unscoped.create(
            firm_id=case.firm_id,
            case=case,
            kind="message",
            title=f"New message from {request.user.get_full_name()}",
            body=body[:200],
        )
        ValueEvent.objects_unscoped.create(
            firm_id=case.firm_id,
            module="portal",
            event_type="staff_message_sent",
            actor_type="staff",
        )
        return Response(_msg_json(msg), status=201)

    Message.objects.filter(thread=thread, read_by_staff_at__isnull=True).exclude(
        sender_type=Message.SenderType.STAFF
    ).update(read_by_staff_at=timezone.now())
    return Response(
        {
            "thread_id": str(thread.id),
            "case": case_summary_json(case),
            "messages": [_msg_json(m) for m in thread.messages.all()],
        }
    )


def _msg_json(m):
    return {
        "id": str(m.id),
        "sender_type": m.sender_type,
        "sender_name": m.sender_name,
        "body": m.body,
        "channel": m.channel,
        "created_at": m.created_at.isoformat(),
    }


@api_view(["GET"])
@permission_classes([IsFirmStaff])
def inbox(request):
    """All case threads, latest message first, unread counts."""
    threads = Thread.objects.select_related(
        "case", "case__client", "case__point_of_contact"
    ).all()
    items = []
    for t in threads:
        last = t.messages.order_by("-created_at").first()
        if last is None:
            continue
        unread = t.messages.filter(
            read_by_staff_at__isnull=True, sender_type="client"
        ).count()
        items.append(
            {
                "thread_id": str(t.id),
                "case_id": str(t.case_id),
                "case_title": t.case.title,
                "client_name": t.case.client.name,
                "stage": t.case.canonical_stage,
                "last_message": {
                    "body": last.body[:150],
                    "sender_type": last.sender_type,
                    "sender_name": last.sender_name,
                    "created_at": last.created_at.isoformat(),
                },
                "unread_count": unread,
                "days_since_touch": t.case.days_since_touch,
            }
        )
    items.sort(key=lambda i: i["last_message"]["created_at"], reverse=True)
    return Response({"threads": items})


@api_view(["GET"])
@permission_classes([IsFirmStaff])
def escalations(request):
    items = EscalationEvent.objects.select_related(
        "case", "case__client", "case__point_of_contact"
    ).exclude(status="resolved")
    return Response(
        {
            "escalations": [
                {
                    "id": e.id,
                    "case": case_summary_json(e.case),
                    "days_without_touch": e.days_without_touch,
                    "status": e.status,
                    "created_at": e.created_at.isoformat(),
                }
                for e in items
            ]
        }
    )


@api_view(["POST"])
@permission_classes([IsFirmStaff])
def escalation_action(request, esc_id):
    try:
        esc = EscalationEvent.objects.get(id=esc_id)
    except EscalationEvent.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    action = request.data.get("action")
    if action == "acknowledge":
        esc.status = "acknowledged"
        esc.acknowledged_by = request.user
    elif action == "resolve":
        esc.status = "resolved"
        esc.resolved_at = timezone.now()
        esc.case.last_firm_touch_at = timezone.now()
        esc.case.save(update_fields=["last_firm_touch_at"])
    else:
        return Response({"detail": "action must be acknowledge|resolve"}, status=400)
    esc.save()
    return Response({"ok": True, "status": esc.status})


@api_view(["GET", "PATCH"])
@permission_classes([IsFirmStaff])
def firm_settings(request):
    firm = request.user.firm
    if request.method == "PATCH":
        incoming = request.data.get("settings", {})
        if isinstance(incoming, dict):
            firm.settings = {**firm.settings, **incoming}
            firm.save(update_fields=["settings"])
    from apps.billing.models import ModuleEntitlement

    return Response(
        {
            "firm": {
                "id": str(firm.id),
                "name": firm.name,
                "slug": firm.slug,
                "billing_exempt": firm.billing_exempt,
                "settings": firm.settings,
            },
            "entitlements": [
                {"module": e.module, "source": e.source, "active": e.active}
                for e in ModuleEntitlement.objects.all()
            ],
        }
    )
