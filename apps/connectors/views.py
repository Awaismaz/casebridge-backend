"""Connector endpoints: the inbound 'mailbox' + a staff-facing status view."""

from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.accounts.authentication import IsFirmStaff
from apps.tenants.models import Firm

from .models import ConnectorConfig, InboundEvent
from .service import apply_event, land_event, verify_signature


@api_view(["POST"])
@permission_classes([AllowAny])
def inbound_events(request):
    """POST /api/v1/connector/events/ — the mailbox. Auth by firm slug header +
    HMAC signature over the raw body. Lands the event idempotently and applies
    it (synchronously here; a Celery worker in production)."""
    firm_slug = request.headers.get("X-CaseBridge-Firm", "")
    signature = request.headers.get("X-CaseBridge-Signature", "")
    firm = Firm.objects.filter(slug=firm_slug).first()
    if firm is None:
        return Response({"detail": "Unknown firm."}, status=404)
    config = ConnectorConfig.objects.filter(firm=firm).first()
    if config is None or not config.enabled:
        return Response({"detail": "Connector disabled for this firm."}, status=403)
    if not verify_signature(config.shared_secret, request.body, signature):
        return Response({"detail": "Bad signature."}, status=401)

    data = request.data
    event_type = data.get("event_type")
    idem = data.get("idempotency_key") or ""
    if not event_type or not idem:
        return Response({"detail": "event_type and idempotency_key required."}, status=400)

    event, created = land_event(
        firm, event_type, idem, config.source, data.get("payload", {})
    )
    if not created:
        return Response({"status": event.status, "duplicate": True})
    try:
        apply_event(event)
    except Exception as exc:  # noqa: BLE001
        return Response({"status": "failed", "error": str(exc)}, status=202)
    return Response({"status": event.status, "id": str(event.id)}, status=201)


@api_view(["GET", "PATCH"])
@permission_classes([IsFirmStaff])
def connector_status(request):
    """Staff view: connector config + recent inbound events + health."""
    firm = request.user.firm
    config, _ = ConnectorConfig.objects.get_or_create(firm=firm)

    if request.method == "PATCH":
        if "enabled" in request.data:
            config.enabled = bool(request.data["enabled"])
        if "source" in request.data:
            config.source = request.data["source"]
        if "stage_map" in request.data and isinstance(request.data["stage_map"], dict):
            config.stage_map = request.data["stage_map"]
        config.save()

    events = InboundEvent.objects.all()[:25]
    counts = {
        "applied": InboundEvent.objects.filter(status="applied").count(),
        "failed": InboundEvent.objects.filter(status="failed").count(),
        "dead": InboundEvent.objects.filter(status="dead").count(),
    }
    return Response(
        {
            "config": {
                "source": config.source,
                "enabled": config.enabled,
                "has_secret": bool(config.shared_secret),
                "stage_map": config.stage_map,
                "last_event_at": config.last_event_at.isoformat() if config.last_event_at else None,
                "last_reconcile_at": config.last_reconcile_at.isoformat()
                if config.last_reconcile_at
                else None,
            },
            "counts": counts,
            "recent_events": [
                {
                    "id": str(e.id),
                    "event_type": e.event_type,
                    "status": e.status,
                    "source": e.source,
                    "received_at": e.received_at.isoformat(),
                    "error": e.error,
                }
                for e in events
            ],
        }
    )
