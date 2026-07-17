import uuid

from django.db import models
from django.utils import timezone

from apps.accounts.models import StaffUser
from apps.clients.models import PortalClientUser
from apps.tenants.models import TenantModel

# Canonical 8-step PI ladder. Per-connector config maps CMS stage codes
# (e.g. zlate's .5V/1NT/2MM/...) onto these.
CANONICAL_STAGES = [
    ("intake", "Getting Started"),
    ("treatment", "Medical Treatment"),
    ("records", "Gathering Records"),
    ("demand", "Demand Preparation"),
    ("negotiation", "Negotiation"),
    ("litigation", "Litigation"),
    ("settlement", "Settlement"),
    ("closed", "Case Closed"),
]
STAGE_ORDER = [s[0] for s in CANONICAL_STAGES]


class PortalCase(TenantModel):
    """The portal's own case record. Standalone-first: every field is
    manageable manually; the CMS connector only accelerates data entry."""

    class Status(models.TextChoices):
        OPEN = "open"
        CLOSED = "closed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client = models.ForeignKey(
        PortalClientUser, on_delete=models.CASCADE, related_name="cases"
    )
    title = models.CharField(max_length=250)  # e.g. "MVA — I-35 collision"
    case_type = models.CharField(max_length=80, default="Motor Vehicle Accident")
    external_source = models.CharField(max_length=40, blank=True)  # "" = manual
    external_id = models.CharField(max_length=80, blank=True)
    canonical_stage = models.CharField(
        max_length=20, choices=CANONICAL_STAGES, default="intake"
    )
    stage_label_raw = models.CharField(max_length=80, blank=True)  # CMS's own label
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    point_of_contact = models.ForeignKey(
        StaffUser, null=True, blank=True, on_delete=models.SET_NULL, related_name="poc_cases"
    )
    attorney = models.ForeignKey(
        StaffUser, null=True, blank=True, on_delete=models.SET_NULL, related_name="attorney_cases"
    )
    date_of_incident = models.DateField(null=True, blank=True)
    opened_at = models.DateTimeField(default=timezone.now)
    last_firm_touch_at = models.DateTimeField(default=timezone.now)
    next_step_note = models.CharField(max_length=300, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["firm", "external_source", "external_id"],
                condition=~models.Q(external_id=""),
                name="uniq_case_external_ref_per_firm",
            )
        ]
        ordering = ["-opened_at"]

    def __str__(self):
        return self.title

    @property
    def stage_index(self) -> int:
        return STAGE_ORDER.index(self.canonical_stage)

    @property
    def days_since_touch(self) -> int:
        return (timezone.now() - self.last_firm_touch_at).days


class CaseStageEvent(TenantModel):
    """History of stage moves — powers the tracker timeline + notifications."""

    case = models.ForeignKey(PortalCase, on_delete=models.CASCADE, related_name="stage_events")
    from_stage = models.CharField(max_length=20, blank=True)
    to_stage = models.CharField(max_length=20, choices=CANONICAL_STAGES)
    note = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at"]
