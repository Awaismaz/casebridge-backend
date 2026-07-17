import uuid

from django.db import models
from django.utils import timezone

from apps.accounts.models import StaffUser
from apps.cases.models import PortalCase
from apps.tenants.models import TenantModel

DOC_TYPES = [
    ("medical_record", "Medical Record"),
    ("medical_bill", "Medical Bill"),
    ("police_report", "Police Report"),
    ("demand_letter", "Demand Letter"),
    ("insurance_corr", "Insurance Correspondence"),
    ("other", "Other"),
]


class DocRecord(TenantModel):
    """Module B: an ingested document moving through the pipeline
    ingest -> ocr -> classify -> extract -> review -> publish."""

    class Status(models.TextChoices):
        QUEUED = "queued"
        OCR = "ocr"
        CLASSIFIED = "classified"
        EXTRACTED = "extracted"
        IN_REVIEW = "in_review"
        PUBLISHED = "published"
        FAILED = "failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey(PortalCase, on_delete=models.CASCADE, related_name="docs")
    filename = models.CharField(max_length=300)
    doc_type = models.CharField(max_length=20, choices=DOC_TYPES, default="other")
    classification_confidence = models.FloatField(default=0.0)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.QUEUED)
    page_count = models.PositiveIntegerField(default=1)
    summary = models.TextField(blank=True)
    extracted_text = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.filename


class ExtractedFact(TenantModel):
    """A key fact pulled from a document. Corrections (original vs corrected)
    are the accuracy eval set AND the time-saved evidence."""

    class FactType(models.TextChoices):
        DATE = "date"
        PROVIDER = "provider"
        PARTY = "party"
        AMOUNT = "amount"
        DIAGNOSIS = "diagnosis"
        DEADLINE_CANDIDATE = "deadline_candidate"

    class ReviewStatus(models.TextChoices):
        PENDING = "pending"
        ACCEPTED = "accepted"
        CORRECTED = "corrected"
        REJECTED = "rejected"

    doc = models.ForeignKey(DocRecord, on_delete=models.CASCADE, related_name="facts")
    fact_type = models.CharField(max_length=20, choices=FactType.choices)
    label = models.CharField(max_length=200)
    value = models.JSONField()  # {"text": ..., "date": ..., "amount": ...}
    original_value = models.JSONField(null=True, blank=True)  # set when corrected
    page_ref = models.PositiveIntegerField(default=1)
    confidence = models.FloatField(default=0.0)
    review_status = models.CharField(
        max_length=10, choices=ReviewStatus.choices, default=ReviewStatus.PENDING
    )
    reviewed_by = models.ForeignKey(
        StaffUser, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["page_ref", "id"]


class TimelineEntry(TenantModel):
    """Published case timeline (from confirmed facts + stage events)."""

    case = models.ForeignKey(PortalCase, on_delete=models.CASCADE, related_name="timeline")
    date = models.DateField()
    title = models.CharField(max_length=250)
    description = models.CharField(max_length=500, blank=True)
    source_doc = models.ForeignKey(
        DocRecord, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    entry_type = models.CharField(max_length=30, default="fact")  # fact | stage | deadline

    class Meta:
        ordering = ["date"]
