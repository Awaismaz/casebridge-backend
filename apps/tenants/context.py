"""Per-request tenant context.

The current firm id is carried in a ContextVar set by TenantContextMiddleware
(from the authenticated principal's firm) and read by TenantManager. Workers
and management commands that legitimately cross tenants use `firm_context`
or the `objects_unscoped` manager explicitly.
"""

from contextlib import contextmanager
from contextvars import ContextVar

_current_firm_id: ContextVar = ContextVar("current_firm_id", default=None)


def get_current_firm_id():
    return _current_firm_id.get()


def set_current_firm_id(firm_id):
    return _current_firm_id.set(firm_id)


@contextmanager
def firm_context(firm_id):
    """Explicitly scope a block to one firm (workers, seeds, admin tasks)."""
    token = _current_firm_id.set(firm_id)
    try:
        yield
    finally:
        _current_firm_id.reset(token)
