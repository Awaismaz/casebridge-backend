from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models

from apps.tenants.models import Firm


class StaffUserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email)
        user = self.model(email=email, username=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self._create_user(email, password, **extra_fields)


class StaffUser(AbstractUser):
    """A law-firm staff member. Clients are NEVER rows here — they live in
    apps.clients.PortalClientUser (separate table, separate token audience)."""

    email = models.EmailField(unique=True)
    firm = models.ForeignKey(
        Firm, null=True, blank=True, on_delete=models.SET_NULL, related_name="staff"
    )
    title = models.CharField(max_length=100, blank=True)  # e.g. "Case Manager"
    phone = models.CharField(max_length=32, blank=True)
    avatar_color = models.CharField(max_length=7, blank=True, default="")

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = StaffUserManager()

    class Role(models.TextChoices):
        ADMIN = "admin"
        ATTORNEY = "attorney"
        CASE_MANAGER = "case_manager"
        INTAKE = "intake"

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.CASE_MANAGER)

    def __str__(self):
        return f"{self.get_full_name() or self.email}"
