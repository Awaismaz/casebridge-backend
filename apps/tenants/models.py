import uuid

from django.db import models

from .context import get_current_firm_id


class Firm(models.Model):
    """A tenant. ZLG is just a Firm row with billing_exempt=True."""

    class Status(models.TextChoices):
        ACTIVE = "active"
        SUSPENDED = "suspended"
        CHURNED = "churned"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=80, unique=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    billing_exempt = models.BooleanField(default=False)
    # branding, stage labels, escalation threshold days, quiet hours, ...
    settings = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    @property
    def escalation_threshold_days(self) -> int:
        return int(self.settings.get("escalation_threshold_days", 7))


class UnscopedTenantQueriesError(Exception):
    """Raised when tenant-scoped data is queried with no firm in context."""


class TenantManager(models.Manager):
    """Default manager for tenant models: silently scopes to the current firm
    and refuses to run when no firm context is set. Use `objects_unscoped`
    (workers/admin only) to cross tenants deliberately."""

    def get_queryset(self):
        firm_id = get_current_firm_id()
        if firm_id is None:
            raise UnscopedTenantQueriesError(
                f"{self.model.__name__} queried without firm context. "
                "Use objects_unscoped or firm_context() if this is intentional."
            )
        return super().get_queryset().filter(firm_id=firm_id)


class TenantModel(models.Model):
    """Abstract base: every business table carries firm_id."""

    firm = models.ForeignKey(Firm, on_delete=models.CASCADE, related_name="+")

    objects = TenantManager()
    objects_unscoped = models.Manager()

    class Meta:
        abstract = True
        base_manager_name = "objects_unscoped"

    def save(self, *args, **kwargs):
        # Auto-stamp the firm from context on first save when not set.
        if self.firm_id is None:
            firm_id = get_current_firm_id()
            if firm_id is None:
                raise UnscopedTenantQueriesError(
                    f"Saving {type(self).__name__} without firm in context."
                )
            self.firm_id = firm_id
        super().save(*args, **kwargs)
