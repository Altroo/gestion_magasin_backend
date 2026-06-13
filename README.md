# Gestion Magasin Backend

Django REST API for a store operations platform for catalog, stock, store inventory, purchases, sales, cash register, promotions, expenses, attendance, reporting, users, notifications, and multi-store workflows.

This is a production-oriented business backend. It models real operational workflows, authenticated staff access, API filtering, document/report generation, realtime notification plumbing, and testable domain behavior.

## What It Shows

- Backend ownership for a complete internal business application.
- Django REST API design across related business modules.
- PostgreSQL data modeling for operational records and audit/history needs.
- Auth, permissions, SSO subject handling, filters, dashboards, exports, and realtime events.
- Testable backend code with pytest tooling instead of only manual checks.

## Main Modules

- account
- attendance
- catalog
- finance
- reporting
- sales
- stock
- store
- notification
- ws

## Key Capabilities

- Django REST API for articles, stores, stock, inventory, stock transfers, purchases, sales, caisse, promotions, expenses, attendance, and reporting.
- Multi-store operational model with store tabs, stock status, reporting endpoints, and user/permission flows.
- JWT/session auth, SSO subject support, django-filter, django-axes, and production-ready CORS/static/runtime setup.
- ReportLab/OpenPyXL support for reporting and export-oriented documents.
- Realtime notifications and websocket runtime through Channels, Daphne, Redis, and Celery-ready dependencies.
- pytest/pytest-django stack with async/cov/xdist support.

## Stack

- Python, Django 6, Django REST Framework
- PostgreSQL, django-filter, django-simple-history
- SimpleJWT, dj-rest-auth, django-axes, CORS
- Redis, Channels, channels-redis, Daphne, Celery-ready runtime
- Gunicorn, WhiteNoise, Pillow/OpenCV where media handling is needed
- pytest, pytest-django, pytest-cov, pytest-asyncio, pytest-xdist

## Related Repository

- Frontend: [Altroo/gestion_magasin_frontend](https://github.com/Altroo/gestion_magasin_frontend)

## Product Screenshots

Redacted production UI screens powered by this API. Sensitive names, amounts, dates, and records are blurred.

![Store operations dashboard](docs/screenshots/gestion-magasin-dashboard.png)

![Cash register workflow](docs/screenshots/gestion-magasin-caisse.png)

![Stock management](docs/screenshots/gestion-magasin-stock.png)

## Local Setup

Create local-only environment variables for Django settings, database, Redis, media/static storage, CORS, and allowed hosts. Do not commit `.env` files or production credentials.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 8006
```

On Windows, activate with `.venv\Scripts\activate`.

## Tests

```bash
python -m pytest
python -m pytest --cov
```

## Portfolio Note

The repository is public for portfolio review. Screenshots are redacted, and sensitive production values are intentionally hidden.
