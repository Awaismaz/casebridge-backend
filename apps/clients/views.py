"""Client-portal endpoints (aud=portal-client only)."""

from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.authentication import IsPortalClient
from apps.billing.models import ValueEvent
from apps.cases.models import CANONICAL_STAGES, STAGE_ORDER, PortalCase
from apps.cases.serializers import portal_case_bundle
from apps.evidence.models import CustodyEvent, EvidenceFile
from apps.messaging.models import Message, Notification, Thread

from .models import ConsentLog


def _client_case(request):
    """The client's most recent open case (MVP: one active case per client)."""
    return (
        PortalCase.objects.filter(client_id=request.user.id)
        .order_by("-opened_at")
        .select_related("point_of_contact", "attorney", "firm")
        .first()
    )


@api_view(["GET"])
@permission_classes([IsPortalClient])
def my_case(request):
    case = _client_case(request)
    if case is None:
        return Response({"detail": "No case found."}, status=404)
    return Response(portal_case_bundle(case))


@api_view(["GET", "POST"])
@permission_classes([IsPortalClient])
def my_messages(request):
    case = _client_case(request)
    if case is None:
        return Response({"detail": "No case found."}, status=404)
    thread, _ = Thread.objects.get_or_create(case=case, defaults={"firm_id": case.firm_id})

    if request.method == "POST":
        body = (request.data.get("body") or "").strip()
        if not body:
            return Response({"detail": "Message body required."}, status=400)
        msg = Message.objects_unscoped.create(
            firm_id=case.firm_id,
            thread=thread,
            sender_type=Message.SenderType.CLIENT,
            sender_name=request.user.name,
            body=body,
        )
        ValueEvent.objects_unscoped.create(
            firm_id=case.firm_id,
            module="portal",
            event_type="client_message_sent",
            actor_type="client",
        )
        return Response(_msg_json(msg), status=201)

    Message.objects.filter(
        thread=thread, read_by_client_at__isnull=True
    ).exclude(sender_type=Message.SenderType.CLIENT).update(read_by_client_at=timezone.now())
    msgs = thread.messages.all()
    return Response({"thread_id": str(thread.id), "messages": [_msg_json(m) for m in msgs]})


def _msg_json(m):
    return {
        "id": str(m.id),
        "sender_type": m.sender_type,
        "sender_name": m.sender_name
        or (m.sender_staff.get_full_name() if m.sender_staff else ""),
        "body": m.body,
        "channel": m.channel,
        "created_at": m.created_at.isoformat(),
    }


@api_view(["GET", "POST"])
@permission_classes([IsPortalClient])
def my_files(request):
    case = _client_case(request)
    if case is None:
        return Response({"detail": "No case found."}, status=404)

    if request.method == "POST":
        filename = (request.data.get("filename") or "").strip()
        if not filename:
            return Response({"detail": "filename required."}, status=400)
        f = EvidenceFile.objects_unscoped.create(
            firm_id=case.firm_id,
            case=case,
            uploader_type=EvidenceFile.UploaderType.CLIENT,
            uploader_name=request.user.name,
            filename=filename,
            mime_type=request.data.get("mime_type", ""),
            size_bytes=int(request.data.get("size_bytes") or 0),
            status=EvidenceFile.Status.AVAILABLE,  # demo: skip scan pipeline
            s3_key=f"firm/{case.firm_id}/case/{case.id}/{filename}",
        )
        CustodyEvent.objects_unscoped.create(
            firm_id=case.firm_id, file=f, action="uploaded", actor=request.user.name
        )
        ValueEvent.objects_unscoped.create(
            firm_id=case.firm_id,
            module="portal",
            event_type="evidence_uploaded",
            actor_type="client",
        )
        return Response(_file_json(f), status=201)

    return Response({"files": [_file_json(f) for f in case.files.all()]})


def _file_json(f):
    return {
        "id": str(f.id),
        "filename": f.filename,
        "mime_type": f.mime_type,
        "size_bytes": f.size_bytes,
        "status": f.status,
        "uploader_type": f.uploader_type,
        "uploader_name": f.uploader_name,
        "created_at": f.created_at.isoformat(),
    }


@api_view(["GET"])
@permission_classes([IsPortalClient])
def my_notifications(request):
    case = _client_case(request)
    if case is None:
        return Response({"notifications": []})
    items = case.notifications.all()[:50]
    return Response(
        {
            "notifications": [
                {
                    "id": n.id,
                    "kind": n.kind,
                    "title": n.title,
                    "body": n.body,
                    "read": n.read_at is not None,
                    "created_at": n.created_at.isoformat(),
                }
                for n in items
            ]
        }
    )


@api_view(["POST"])
@permission_classes([IsPortalClient])
def mark_notifications_read(request):
    case = _client_case(request)
    if case is not None:
        case.notifications.filter(read_at__isnull=True).update(read_at=timezone.now())
    return Response({"ok": True})


@api_view(["POST"])
@permission_classes([IsPortalClient])
def grant_consent(request):
    client = request.user.client
    channel = request.data.get("channel", "sms")
    granted = bool(request.data.get("granted", True))
    ConsentLog.objects_unscoped.create(
        firm_id=client.firm_id,
        client=client,
        channel=channel,
        granted=granted,
        source="portal",
        ip_address=request.META.get("REMOTE_ADDR"),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:300],
    )
    return Response({"ok": True, "channel": channel, "granted": granted})


@api_view(["GET"])
@permission_classes([IsPortalClient])
def stage_reference(request):
    """The canonical ladder with plain-language explainers for the tracker."""
    explainers = {
        "intake": "We're setting up your case, gathering the basics, and making sure you get the care you need.",
        "treatment": "Focus on getting better. We track your treatment while you heal — your only job is to follow your doctors' plan.",
        "records": "We're collecting your medical records and bills from every provider to document the full impact of your injury.",
        "demand": "We're preparing a demand package that tells your story and presents the evidence to the insurance company.",
        "negotiation": "We're negotiating with the insurance company to get you the compensation you deserve.",
        "litigation": "Your case is in litigation. We're fighting for you in court — we'll guide you through every step.",
        "settlement": "Great news — we're finalizing your settlement, resolving liens, and preparing your disbursement.",
        "closed": "Your case is complete. Funds have been disbursed. We're here if you ever need us again.",
    }
    return Response(
        {
            "stages": [
                {"key": k, "label": label, "explainer": explainers.get(k, ""), "order": i}
                for i, (k, label) in enumerate(CANONICAL_STAGES)
            ],
            "order": STAGE_ORDER,
        }
    )
