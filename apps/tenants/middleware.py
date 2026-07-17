"""Sets the tenant ContextVar from the authenticated principal.

DRF authenticates after Django middleware runs, so this middleware wraps the
whole request in a fresh context and the JWT authentication class (see
apps.accounts.authentication) stamps the firm id the moment the token is
verified. This middleware's job is to guarantee the var is RESET between
requests so one request's firm can never bleed into the next.
"""

from .context import set_current_firm_id


class TenantContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        set_current_firm_id(None)
        try:
            return self.get_response(request)
        finally:
            set_current_firm_id(None)
