from django.db import models
from django.utils import timezone

from apps.accounts.models import StaffUser
from apps.cases.models import PortalCase
from apps.clients.models import PortalClientUser
from apps.tenants.models import TenantModel


class NpsSurvey(TenantModel):
    """Satisfaction pulse fired at a milestone. Client answers 0-10 + comment."""

    class Trigger(models.TextChoices):
        STAGE_MOVE = "stage_move"
        SETTLEMENT = "settlement"
        PERIODIC = "periodic"

    case = models.ForeignKey(PortalCase, on_delete=models.CASCADE, related_name="surveys")
    client = models.ForeignKey(PortalClientUser, on_delete=models.CASCADE, related_name="surveys")
    trigger = models.CharField(max_length=15, choices=Trigger.choices, default=Trigger.STAGE_MOVE)
    score = models.PositiveSmallIntegerField(null=True, blank=True)  # 0-10
    comment = models.TextField(blank=True)
    sent_at = models.DateTimeField(default=timezone.now)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-sent_at"]

    @property
    def category(self):
        if self.score is None:
            return "pending"
        if self.score >= 9:
            return "promoter"
        if self.score >= 7:
            return "passive"
        return "detractor"


class GrowthSignal(TenantModel):
    """Referral asks, review requests, and household-expansion flags — the
    growth motion, triggered at high-satisfaction points."""

    class Kind(models.TextChoices):
        REFERRAL = "referral"
        REVIEW = "review"
        HOUSEHOLD = "household"

    class Status(models.TextChoices):
        SUGGESTED = "suggested"
        SENT = "sent"
        CONVERTED = "converted"
        DISMISSED = "dismissed"

    case = models.ForeignKey(PortalCase, on_delete=models.CASCADE, related_name="growth_signals")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.SUGGESTED)
    detail = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    actioned_by = models.ForeignKey(
        StaffUser, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-created_at"]


class UpdateTemplate(TenantModel):
    """Structured 'bad news' / proactive-update templates so delays are
    delivered with a consistent, empathetic script instead of silence."""

    class Kind(models.TextChoices):
        DELAY = "delay"
        SETBACK = "setback"
        MILESTONE = "milestone"
        REQUEST = "request"

    kind = models.CharField(max_length=12, choices=Kind.choices)
    title = models.CharField(max_length=120)
    body = models.TextField()
    is_default = models.BooleanField(default=True)

    class Meta:
        ordering = ["kind"]
