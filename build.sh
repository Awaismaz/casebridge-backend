#!/usr/bin/env bash
# Render build script
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --noinput
python manage.py migrate

# Seed demo data when the demo firm is absent (idempotent guard)
python - <<'PY'
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "casebridge.settings")
django.setup()

from apps.tenants.models import Firm  # noqa: E402

if not Firm.objects.filter(slug="zinda-law-group").exists():
    from django.core.management import call_command

    call_command("seed_demo")
else:
    print("Demo data present; skipping seed.")
PY
