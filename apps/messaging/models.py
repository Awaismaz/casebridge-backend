import uuid

from django.db import models
from django.utils import timezone

from apps.accounts.models import StaffUser
from apps.cases.models import PortalCase
from apps.tenants.models import TenantModel


class Thread(TenantModel):
    """One thread per case. All channels (portal/email/SMS) land here."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.OneToOneField(PortalCase, on_delete=models.CASCADE, related_name="thread")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Thread<{self.case.title}>"


class Message(TenantModel):
    class SenderType(models.TextChoices):
        STAFF = "staff"
        CLIENT = "client"
        SYSTEM = "system"

    class Channel(models.TextChoices):
        PORTAL = "portal"
        EMAIL = "email"
        SMS = "sms"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    thread = models.ForeignKey(Thread, on_delete=models.CASCADE, related_name="messages")
    sender_type = models.CharField(max_length=10, choices=SenderType.choices)
    sender_staff = models.ForeignKey(
        StaffUser, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    sender_name = models.CharField(max_length=200, blank=True)
    body = models.TextField()
    channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.PORTAL)
    created_at = models.DateTimeField(default=timezone.now)
    read_by_client_at = models.DateTimeField(null=True, blank=True)
    read_by_staff_at = models.DateTimeField(null=True, blank=True)

    # Sentiment (client messages only): scored by the AI service, flagged for
    # manager review before a frustrated client becomes a review or grievance.
    class Sentiment(models.TextChoices):
        UNSCORED = "unscored"
        POSITIVE = "positive"
        NEUTRAL = "neutral"
        NEGATIVE = "negative"

    sentiment = models.CharField(max_length=10, choices=Sentiment.choices, default=Sentiment.UNSCORED)
    sentiment_flagged = models.BooleanField(default=False)  # negative → needs review
    sentiment_reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]


class Delivery(TenantModel):
    """Per-channel delivery record for an outbound message. In production the
    provider (Twilio/SES) fills status + provider_message_id via webhook; here
    it captures the multi-channel fan-out intent and consent gating."""

    class Channel(models.TextChoices):
        PORTAL = "portal"
        EMAIL = "email"
        SMS = "sms"

    class Status(models.TextChoices):
        QUEUED = "queued"
        SENT = "sent"
        DELIVERED = "delivered"
        SKIPPED = "skipped"  # e.g. no consent
        FAILED = "failed"

    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="deliveries")
    channel = models.CharField(max_length=10, choices=Channel.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED)
    provider_message_id = models.CharField(max_length=120, blank=True)
    detail = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(default=timezone.now)


class ScheduledCheckIn(TenantModel):
    """Cadence engine: the next automatic touchpoint for a case, regardless of
    activity. The run_cadence command fires due check-ins and reschedules them."""

    case = models.OneToOneField(PortalCase, on_delete=models.CASCADE, related_name="check_in")
    cadence_days = models.PositiveIntegerField(default=14)
    next_run_at = models.DateTimeField(default=timezone.now)
    last_run_at = models.DateTimeField(null=True, blank=True)
    active = models.BooleanField(default=True)


class EscalationEvent(TenantModel):
    """Written when a case goes untouched past the firm threshold."""

    class Status(models.TextChoices):
        OPEN = "open"
        ACKNOWLEDGED = "acknowledged"
        RESOLVED = "resolved"

    case = models.ForeignKey(PortalCase, on_delete=models.CASCADE, related_name="escalations")
    days_without_touch = models.PositiveIntegerField()
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.OPEN)
    acknowledged_by = models.ForeignKey(
        StaffUser, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class Notification(TenantModel):
    """Client-facing notifications: stage moves, check-ins, new messages."""

    class Kind(models.TextChoices):
        STAGE_MOVE = "stage_move"
        CHECK_IN = "check_in"
        MESSAGE = "message"
        DOCUMENT = "document"

    case = models.ForeignKey(PortalCase, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=15, choices=Kind.choices)
    title = models.CharField(max_length=200)
    body = models.CharField(max_length=500, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
