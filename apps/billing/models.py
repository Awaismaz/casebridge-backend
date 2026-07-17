from django.db import models
from django.utils import timezone

from apps.tenants.models import Firm, TenantModel

MODULES = [
    ("portal", "Client Portal"),
    ("reader", "Smart Document Reader"),
]


class ModuleEntitlement(TenantModel):
    """The single gate the app reads. Source: stripe | comp | trial.
    ZLG gets comped rows; paying firms get stripe rows."""

    class Source(models.TextChoices):
        STRIPE = "stripe"
        COMP = "comp"
        TRIAL = "trial"

    module = models.CharField(max_length=10, choices=MODULES)
    source = models.CharField(max_length=10, choices=Source.choices)
    active = models.BooleanField(default=True)
    granted_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["firm", "module"], name="uniq_module_per_firm")
        ]

    @classmethod
    def firm_has(cls, firm_id, module: str) -> bool:
        return cls.objects_unscoped.filter(
            firm_id=firm_id, module=module, active=True
        ).exists()


class ValueEvent(TenantModel):
    """Append-only instrumentation: every moment the product saves time or
    prevents a call. Powers success metrics from day one."""

    module = models.CharField(max_length=10, choices=MODULES)
    event_type = models.CharField(max_length=50)  # message_sent, doc_accepted, ...
    actor_type = models.CharField(max_length=10, default="staff")  # staff | client | system
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
