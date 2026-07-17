import uuid

from django.db import models
from django.utils import timezone

from apps.cases.models import PortalCase
from apps.tenants.models import TenantModel


class EvidenceFile(TenantModel):
    """Metadata for a client- or staff-uploaded file. Binary lives in S3
    (presigned multipart, keys namespaced firm/{firm_id}/case/{case_id}/...).
    MVP demo: metadata only, presign endpoint stubbed."""

    class Status(models.TextChoices):
        PENDING = "pending"
        UPLOADED = "uploaded"
        SCANNING = "scanning"
        AVAILABLE = "available"
        QUARANTINED = "quarantined"

    class UploaderType(models.TextChoices):
        CLIENT = "client"
        STAFF = "staff"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey(PortalCase, on_delete=models.CASCADE, related_name="files")
    uploader_type = models.CharField(max_length=10, choices=UploaderType.choices)
    uploader_name = models.CharField(max_length=200, blank=True)
    filename = models.CharField(max_length=300)
    mime_type = models.CharField(max_length=100, blank=True)
    size_bytes = models.BigIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True)
    s3_key = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.filename


class CustodyEvent(TenantModel):
    """Append-only chain of custody for every evidence file."""

    class Action(models.TextChoices):
        UPLOADED = "uploaded"
        SCANNED = "scanned"
        VIEWED = "viewed"
        DOWNLOADED = "downloaded"
        EXPORTED = "exported"

    file = models.ForeignKey(EvidenceFile, on_delete=models.CASCADE, related_name="custody")
    action = models.CharField(max_length=15, choices=Action.choices)
    actor = models.CharField(max_length=200)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
