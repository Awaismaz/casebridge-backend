"""JWT authentication with audience separation.

Two principals, two audiences:
  - firm staff   -> aud=firm-staff   (StaffUser)
  - portal client -> aud=portal-client (PortalClientUser)

The moment a token is verified, the firm id is stamped into the tenant
ContextVar so every subsequent ORM query in the request is firm-scoped.
"""

from django.conf import settings
from rest_framework import authentication, exceptions, permissions
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from apps.tenants.context import set_current_firm_id


def tokens_for_staff(user):
    refresh = RefreshToken.for_user(user)
    for t in (refresh, refresh.access_token):
        t["aud"] = settings.JWT_AUD_STAFF
        t["firm_id"] = str(user.firm_id) if user.firm_id else None
        t["name"] = user.get_full_name()
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


def tokens_for_client(client):
    refresh = RefreshToken()
    refresh["client_id"] = str(client.id)
    refresh["aud"] = settings.JWT_AUD_CLIENT
    refresh["firm_id"] = str(client.firm_id)
    refresh["name"] = client.name
    access = refresh.access_token
    for claim in ("client_id", "aud", "firm_id", "name"):
        access[claim] = refresh[claim]
    return {"access": str(access), "refresh": str(refresh)}


class PortalClientPrincipal:
    """Duck-typed request.user for portal clients."""

    is_authenticated = True
    is_staff_principal = False
    is_client_principal = True

    def __init__(self, client):
        self.client = client
        self.id = client.id
        self.firm_id = client.firm_id
        self.name = client.name

    def __str__(self):
        return f"client:{self.id}"


class AudienceJWTAuthentication(authentication.BaseAuthentication):
    def authenticate(self, request):
        header = request.META.get("HTTP_AUTHORIZATION", "")
        if not header.startswith("Bearer "):
            return None
        raw = header.split(" ", 1)[1].strip()
        try:
            token = AccessToken(raw)
        except (InvalidToken, TokenError) as exc:
            raise exceptions.AuthenticationFailed("Invalid or expired token") from exc

        aud = token.get("aud")
        if aud == settings.JWT_AUD_STAFF:
            from apps.accounts.models import StaffUser

            try:
                user = StaffUser.objects.get(id=token["user_id"], is_active=True)
            except StaffUser.DoesNotExist:
                raise exceptions.AuthenticationFailed("Staff user not found")
            user.is_staff_principal = True
            user.is_client_principal = False
            set_current_firm_id(user.firm_id)
            return (user, token)

        if aud == settings.JWT_AUD_CLIENT:
            from apps.clients.models import PortalClientUser

            try:
                client = PortalClientUser.objects_unscoped.get(
                    id=token["client_id"], status=PortalClientUser.Status.ACTIVE
                )
            except PortalClientUser.DoesNotExist:
                raise exceptions.AuthenticationFailed("Client not found")
            set_current_firm_id(client.firm_id)
            return (PortalClientPrincipal(client), token)

        raise exceptions.AuthenticationFailed("Unknown token audience")


class IsFirmStaff(permissions.BasePermission):
    """Staff endpoints: a portal-client token must NEVER pass this."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and getattr(request.user, "is_staff_principal", False)
            and getattr(request.user, "firm_id", None)
        )


class IsPortalClient(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and getattr(request.user, "is_client_principal", False))
