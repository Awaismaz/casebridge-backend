# CaseBridge Backend

Multitenant SaaS backend for **CaseBridge** — Client Portal + Smart Document
Reader for personal-injury law firms. Django 5.2 + DRF, deployed as a Render
Web Service. Frontend lives at [Awaismaz/casebridge](https://github.com/Awaismaz/casebridge)
(Base44 app).

See `NEW_PROJECT_CONTEXT.md` in the ZindaLaw workspace for the full product
plan. Key design rules honored here:

- **Multitenant from day one** — every business table carries `firm_id`;
  the default manager refuses unscoped queries (`apps/tenants`). Leak tests
  in `apps/tenants/tests.py` are the CI gate.
- **Client identity is a separate table** (`PortalClientUser`), passwordless
  (OTP), with an append-only `ConsentLog` (TCPA gate).
- **Audience-separated JWTs** — staff tokens (`aud=firm-staff`) vs client
  tokens (`aud=portal-client`); a client token can never open a staff endpoint.
- **Module gating** via `ModuleEntitlement` (stripe | comp | trial).

## Local dev

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py seed_demo
.venv/bin/python manage.py runserver  # http://localhost:8000
.venv/bin/python manage.py test       # leak tests
```

## Demo personas (DEMO_MODE=true)

| Persona | Login |
|---|---|
| Staff — Sarah Mitchell, Senior Case Manager | `demo.staff@casebridge.app` / `demo1234` |
| Client — Jordan Avery | `demo.client@casebridge.app`, OTP `246810` |
| One-call demo login | `POST /api/v1/auth/demo/ {"role": "staff"|"client"}` |

## API surface (v1)

- `POST /api/v1/auth/staff/login/` · `client/request-otp/` · `client/verify-otp/` · `demo/` · `refresh/`
- `GET /api/v1/me/` — profile + entitlements (either audience)
- Portal (client tokens): `portal/case/` · `portal/messages/` · `portal/files/` ·
  `portal/notifications/` · `portal/consent/` · `portal/stages/`
- Console (staff tokens): `console/dashboard/` · `console/cases/` ·
  `console/cases/{id}/` · `console/cases/{id}/messages/` · `console/inbox/` ·
  `console/escalations/` · `console/review-queue/` · `console/docs/{id}/` ·
  `console/facts/{id}/review/` · `console/search/` · `console/settings/`

## Render deployment

- **Build**: `./build.sh` (installs, collectstatic, migrate, seeds demo data once)
- **Start**: `gunicorn casebridge.wsgi:application`
- **Env vars**: `SECRET_KEY`, `DATABASE_URL` (Render Postgres), `ALLOWED_HOSTS`,
  `CORS_ALLOWED_ORIGINS` (Base44 app origin), `DEMO_MODE`, `PYTHON_VERSION`
