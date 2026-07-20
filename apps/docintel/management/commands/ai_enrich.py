"""Backfill embeddings (and optionally summaries) on documents so semantic
search works. Safe to run repeatedly; only fills what's missing. Uses OpenAI
when OPENAI_API_KEY is set, otherwise the deterministic fallback embedding."""

from django.core.management.base import BaseCommand

from casebridge import ai

from apps.docintel.models import DocRecord
from apps.tenants.context import firm_context
from apps.tenants.models import Firm


class Command(BaseCommand):
    help = "Backfill document embeddings for semantic search."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Re-embed all docs.")

    def handle(self, *args, **options):
        force = options["force"]
        n = 0
        for firm in Firm.objects.all():
            with firm_context(firm.id):
                qs = DocRecord.objects.all()
                if not force:
                    qs = qs.filter(embedding__isnull=True)
                for d in qs:
                    text = f"{d.filename} {d.summary} {d.extracted_text}"
                    d.embedding = ai.embed(text)
                    d.save(update_fields=["embedding"])
                    n += 1
        mode = "OpenAI" if ai.is_enabled() else "fallback"
        self.stdout.write(self.style.SUCCESS(f"Embedded {n} documents ({mode})."))
