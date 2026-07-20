import uuid

from django.db import models
from django.utils import timezone

from apps.tenants.models import Firm, TenantModel

# Canonical inbound event types emitted by any CMS adapter (Filevine/Litify/Clio
# or the ZLG PM emitter). Downstream apply logic is identical regardless of source.
EVENT_TYPES = [
    ("case.upserted", "Case upserted"),
    ("client.upserted", "Client upserted"),
    ("document.added", "Document added"),
    ("contact.logged", "Contact logged"),
    ("appointment.upcoming", "Appointment upcoming"),
    ("case.closed", "Case closed"),
]


class ConnectorConfig(models.Model):
    """Per-firm connector settings. HMAC shared secret authenticates inbound
    events; stage_map translates a CMS's own stage codes to our canonical ladder."""

    firm = models.OneToOneField(Firm, on_delete=models.CASCADE, related_name="connector")
    source = models.CharField(max_length=40, default="pm")  # pm | filevine | litify | clio
    enabled = models.BooleanField(default=False)
    shared_secret = models.CharField(max_length=128, blank=True)
    stage_map = models.JSONField(default=dict, blank=True)  # {"2MM": "records", ...}
    last_event_at = models.DateTimeField(null=True, blank=True)
    last_reconcile_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.firm.name} · {self.source}"


class InboundEvent(TenantModel):
    """Raw inbound event landed idempotently; applied by a worker, never inline."""

    class Status(models.TextChoices):
        RECEIVED = "received"
        APPLIED = "applied"
        FAILED = "failed"
        DEAD = "dead"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    idempotency_key = models.CharField(max_length=120)
    event_type = models.CharField(max_length=30, choices=EVENT_TYPES)
    source = models.CharField(max_length=40, default="pm")
    payload = models.JSONField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.RECEIVED)
    error = models.CharField(max_length=500, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    received_at = models.DateTimeField(default=timezone.now)
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-received_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["firm", "idempotency_key"], name="uniq_inbound_idempotency_per_firm"
            )
        ]

    def __str__(self):
        return f"{self.event_type} · {self.status}"
