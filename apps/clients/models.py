import secrets
import uuid

from django.db import models
from django.utils import timezone

from apps.tenants.models import TenantModel


class PortalClientUser(TenantModel):
    """The injured person. Passwordless: invite link -> OTP -> JWT.
    Never a role on a staff user."""

    class Status(models.TextChoices):
        INVITED = "invited"
        ACTIVE = "active"
        DISABLED = "disabled"

    class Language(models.TextChoices):
        EN = "en", "English"
        ES = "es", "Spanish"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20, blank=True)  # E.164
    email = models.EmailField(blank=True)
    preferred_language = models.CharField(
        max_length=5, choices=Language.choices, default=Language.EN
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.INVITED)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["firm", "phone"],
                condition=~models.Q(phone=""),
                name="uniq_client_phone_per_firm",
            )
        ]

    def __str__(self):
        return self.name


class OtpCode(TenantModel):
    """One-time 6-digit login code. Demo mode uses a fixed code."""

    client = models.ForeignKey(PortalClientUser, on_delete=models.CASCADE, related_name="otps")
    code = models.CharField(max_length=6)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @classmethod
    def issue(cls, client, ttl_minutes=10, code=None):
        return cls.objects_unscoped.create(
            firm_id=client.firm_id,
            client=client,
            code=code or f"{secrets.randbelow(1_000_000):06d}",
            expires_at=timezone.now() + timezone.timedelta(minutes=ttl_minutes),
        )

    @property
    def is_valid(self):
        return self.used_at is None and self.expires_at > timezone.now()


class ConsentLog(TenantModel):
    """Append-only. TCPA gate: no outbound SMS before a granted row exists."""

    class Channel(models.TextChoices):
        SMS = "sms"
        EMAIL = "email"
        PORTAL = "portal"

    client = models.ForeignKey(
        PortalClientUser, on_delete=models.CASCADE, related_name="consents"
    )
    channel = models.CharField(max_length=10, choices=Channel.choices)
    granted = models.BooleanField()
    consent_text_version = models.CharField(max_length=20, default="v1")
    source = models.CharField(max_length=40, default="portal")  # portal | sms_stop | staff
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
