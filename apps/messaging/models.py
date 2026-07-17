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

    class Meta:
        ordering = ["created_at"]


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
