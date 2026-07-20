#!/usr/bin/env bash
# Render build script
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --noinput
python manage.py migrate

# Reseed demo data every deploy. seed_demo is idempotent (wipes + recreates only
# the two demo firms), so this keeps the demo dataset current with each build.
python manage.py seed_demo
