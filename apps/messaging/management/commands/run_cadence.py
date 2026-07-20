"""Cadence engine — run on a schedule (Render Cron / Celery beat).

For every firm:
  1. Flag cases untouched past the firm threshold as EscalationEvents.
  2. Fire due scheduled check-ins (client notification) and reschedule them.
  3. Send an NPS pulse when a case reaches settlement/closed (once).

Idempotent: won't double-write open escalations or duplicate surveys.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.cases.models import PortalCase
from apps.engagement.models import NpsSurvey
from apps.messaging.models import EscalationEvent, Notification, ScheduledCheckIn
from apps.tenants.context import firm_context
from apps.tenants.models import Firm


class Command(BaseCommand):
    help = "Run the cadence engine: escalations, scheduled check-ins, NPS pulses."

    def handle(self, *args, **options):
        now = timezone.now()
        esc, checks, surveys = 0, 0, 0

        for firm in Firm.objects.filter(status="active"):
            threshold = firm.escalation_threshold_days
            with firm_context(firm.id):
                open_cases = PortalCase.objects.filter(status="open").select_related("client")

                # 1. Escalations
                for c in open_cases:
                    if c.days_since_touch > threshold and not c.escalations.filter(
                        status__in=["open", "acknowledged"]
                    ).exists():
                        EscalationEvent.objects_unscoped.create(
                            firm_id=firm.id, case=c, days_without_touch=c.days_since_touch,
                        )
                        esc += 1

                # 2. Scheduled check-ins
                default_cadence = int(firm.settings.get("check_in_cadence_days", 14))
                for c in open_cases:
                    ci, _ = ScheduledCheckIn.objects_unscoped.get_or_create(
                        firm_id=firm.id, case=c,
                        defaults={"cadence_days": default_cadence, "next_run_at": now},
                    )
                    if ci.active and ci.next_run_at <= now:
                        Notification.objects_unscoped.create(
                            firm_id=firm.id, case=c, kind="check_in",
                            title="Checking in on you",
                            body="Just making sure you have everything you need. Reply anytime.",
                        )
                        ci.last_run_at = now
                        ci.next_run_at = now + timezone.timedelta(days=ci.cadence_days)
                        ci.save()
                        checks += 1

                # 3. NPS pulse at settlement/closed (once per case)
                for c in open_cases.filter(canonical_stage__in=["settlement", "closed"]):
                    if not NpsSurvey.objects_unscoped.filter(case=c, trigger="settlement").exists():
                        NpsSurvey.objects_unscoped.create(
                            firm_id=firm.id, case=c, client=c.client, trigger="settlement",
                        )
                        surveys += 1

        self.stdout.write(self.style.SUCCESS(
            f"Cadence run: {esc} escalations, {checks} check-ins, {surveys} NPS pulses."
        ))
