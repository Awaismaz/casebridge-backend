from django.conf import settings
from django.contrib.auth import authenticate
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.billing.models import ModuleEntitlement
from apps.clients.models import OtpCode, PortalClientUser
from apps.tenants.context import firm_context

from .authentication import tokens_for_client, tokens_for_staff
from .models import StaffUser

DEMO_FIRM_SLUG = "zinda-law-group"
DEMO_OTP_CODE = "246810"


def staff_profile(user):
    return {
        "id": user.id,
        "type": "staff",
        "name": user.get_full_name() or user.email,
        "email": user.email,
        "title": user.title,
        "role": user.role,
        "firm": {
            "id": str(user.firm_id),
            "name": user.firm.name,
            "slug": user.firm.slug,
            "settings": user.firm.settings,
        }
        if user.firm_id
        else None,
        "entitlements": [
            e.module
            for e in ModuleEntitlement.objects_unscoped.filter(
                firm_id=user.firm_id, active=True
            )
        ]
        if user.firm_id
        else [],
    }


def client_profile(client):
    return {
        "id": str(client.id),
        "type": "client",
        "name": client.name,
        "email": client.email,
        "phone": client.phone,
        "preferred_language": client.preferred_language,
        "firm": {
            "id": str(client.firm_id),
            "name": client.firm.name,
            "slug": client.firm.slug,
            "settings": client.firm.settings,
        },
        "has_sms_consent": client.consents.filter(channel="sms", granted=True)
        .order_by("-created_at")
        .exists(),
    }


@api_view(["POST"])
@permission_classes([AllowAny])
def staff_login(request):
    email = (request.data.get("email") or "").strip().lower()
    password = request.data.get("password") or ""
    user = authenticate(request, username=email, password=password)
    if user is None or user.firm_id is None:
        return Response(
            {"detail": "Invalid email or password."}, status=status.HTTP_401_UNAUTHORIZED
        )
    with firm_context(user.firm_id):
        return Response({"tokens": tokens_for_staff(user), "profile": staff_profile(user)})


@api_view(["POST"])
@permission_classes([AllowAny])
def client_request_otp(request):
    """Passwordless step 1: client identifies by phone or email; we issue a
    one-time code. Real deployment sends via Twilio/SES — demo returns it."""
    identifier = (request.data.get("identifier") or "").strip().lower()
    if not identifier:
        return Response({"detail": "Identifier required."}, status=400)
    client = (
        PortalClientUser.objects_unscoped.filter(email__iexact=identifier).first()
        or PortalClientUser.objects_unscoped.filter(phone=identifier).first()
    )
    if client is None:
        # Do not leak which identifiers exist
        return Response({"sent": True})
    otp = OtpCode.issue(client, code=DEMO_OTP_CODE if settings.DEMO_MODE else None)
    payload = {"sent": True}
    if settings.DEMO_MODE:
        payload["demo_code"] = otp.code
    return Response(payload)


@api_view(["POST"])
@permission_classes([AllowAny])
def client_verify_otp(request):
    identifier = (request.data.get("identifier") or "").strip().lower()
    code = (request.data.get("code") or "").strip()
    client = (
        PortalClientUser.objects_unscoped.filter(email__iexact=identifier).first()
        or PortalClientUser.objects_unscoped.filter(phone=identifier).first()
    )
    if client is None:
        return Response({"detail": "Invalid code."}, status=401)
    otp = (
        OtpCode.objects_unscoped.filter(client=client, code=code)
        .order_by("-created_at")
        .first()
    )
    if otp is None or not otp.is_valid:
        return Response({"detail": "Invalid or expired code."}, status=401)
    otp.used_at = timezone.now()
    otp.save(update_fields=["used_at"])
    if client.status == PortalClientUser.Status.INVITED:
        client.status = PortalClientUser.Status.ACTIVE
        client.save(update_fields=["status"])
    with firm_context(client.firm_id):
        return Response(
            {"tokens": tokens_for_client(client), "profile": client_profile(client)}
        )


@api_view(["POST"])
@permission_classes([AllowAny])
def demo_login(request):
    """Demo persona login against seeded data. Enabled by DEMO_MODE."""
    if not settings.DEMO_MODE:
        return Response({"detail": "Demo mode is disabled."}, status=403)
    role = request.data.get("role")
    if role == "staff":
        user = StaffUser.objects.filter(
            firm__slug=DEMO_FIRM_SLUG, email="demo.staff@casebridge.app"
        ).first()
        if user is None:
            return Response({"detail": "Demo data not seeded."}, status=503)
        with firm_context(user.firm_id):
            return Response(
                {"tokens": tokens_for_staff(user), "profile": staff_profile(user)}
            )
    if role == "client":
        client = PortalClientUser.objects_unscoped.filter(
            firm__slug=DEMO_FIRM_SLUG, email="demo.client@casebridge.app"
        ).first()
        if client is None:
            return Response({"detail": "Demo data not seeded."}, status=503)
        with firm_context(client.firm_id):
            return Response(
                {"tokens": tokens_for_client(client), "profile": client_profile(client)}
            )
    return Response({"detail": "role must be 'staff' or 'client'."}, status=400)


@api_view(["POST"])
@permission_classes([AllowAny])
def refresh_token(request):
    raw = request.data.get("refresh") or ""
    try:
        refresh = RefreshToken(raw)
    except TokenError:
        return Response({"detail": "Invalid refresh token."}, status=401)
    access = refresh.access_token
    for claim in ("aud", "firm_id", "client_id", "name"):
        if claim in refresh:
            access[claim] = refresh[claim]
    return Response({"access": str(access)})


@api_view(["GET"])
def me(request):
    user = request.user
    if getattr(user, "is_client_principal", False):
        return Response(client_profile(user.client))
    return Response(staff_profile(user))


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    return Response({"status": "ok", "service": "casebridge-backend"})
