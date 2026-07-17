"""Cross-tenant leak tests — the phase-1 CI deliverable.

If any of these fail, tenancy is broken and NOTHING else matters.
"""

from django.test import TestCase

from apps.cases.models import PortalCase
from apps.clients.models import PortalClientUser
from apps.tenants.context import firm_context, set_current_firm_id
from apps.tenants.models import Firm, UnscopedTenantQueriesError


class TenantIsolationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.firm_a = Firm.objects.create(name="Firm A", slug="firm-a")
        cls.firm_b = Firm.objects.create(name="Firm B", slug="firm-b")
        with firm_context(cls.firm_a.id):
            cls.client_a = PortalClientUser.objects_unscoped.create(
                firm=cls.firm_a, name="Client A", email="a@example.com"
            )
            cls.case_a = PortalCase.objects_unscoped.create(
                firm=cls.firm_a, client=cls.client_a, title="Case A"
            )
        with firm_context(cls.firm_b.id):
            cls.client_b = PortalClientUser.objects_unscoped.create(
                firm=cls.firm_b, name="Client B", email="b@example.com"
            )
            cls.case_b = PortalCase.objects_unscoped.create(
                firm=cls.firm_b, client=cls.client_b, title="Case B"
            )

    def tearDown(self):
        set_current_firm_id(None)

    def test_unscoped_query_refused_without_context(self):
        with self.assertRaises(UnscopedTenantQueriesError):
            list(PortalCase.objects.all())

    def test_firm_a_cannot_see_firm_b_cases(self):
        with firm_context(self.firm_a.id):
            titles = list(PortalCase.objects.values_list("title", flat=True))
        self.assertEqual(titles, ["Case A"])

    def test_firm_b_cannot_see_firm_a_clients(self):
        with firm_context(self.firm_b.id):
            names = list(PortalClientUser.objects.values_list("name", flat=True))
        self.assertEqual(names, ["Client B"])

    def test_get_by_id_across_firms_raises(self):
        with firm_context(self.firm_b.id):
            with self.assertRaises(PortalCase.DoesNotExist):
                PortalCase.objects.get(id=self.case_a.id)

    def test_save_without_context_refused(self):
        case = PortalCase(client=self.client_a, title="Orphan")
        with self.assertRaises(UnscopedTenantQueriesError):
            case.save()

    def test_context_resets_between_blocks(self):
        with firm_context(self.firm_a.id):
            self.assertEqual(PortalCase.objects.count(), 1)
        with self.assertRaises(UnscopedTenantQueriesError):
            PortalCase.objects.count()
