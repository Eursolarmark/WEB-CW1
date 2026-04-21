# MacroTracker API

Nutrition and meal tracking backend built with Django + DRF.

Detailed API reference: [API_Documentation.md](./API_Documentation.md)  
PDF version: [API_Documentation.pdf](./API_Documentation.pdf)

## What This Project Delivers

- JWT authentication with refresh rotation and blacklist support
- Login with username **or** email
- Minimal auth endpoints: register, token, token refresh, me
- Rich meal logging workflow:
  - standard create/list/update/delete
  - quick log by food name
  - bulk create in one request
  - unit conversion input (`unit` + `unit_quantity`)
- Better daily UX:
  - fuzzy food search by approximate name
  - recent foods
  - favorite foods
  - personal nutrition targets
- Advanced API quality features:
  - endpoint-level throttling (auth/food/write/analytics)
  - response caching (`X-Cache: HIT|MISS`)
  - idempotency for selected write endpoints (`Idempotency-Key`)
  - unified error envelope with request tracing (`X-Request-ID`)

## Tech Stack

- Python 3.12+
- Django 6
- Django REST Framework
- SimpleJWT
- drf-spectacular
- SQLite (default, easy local run)

## Quick Start

```powershell
cd <project_root>

python -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

python manage.py migrate
python manage.py check
python manage.py runserver 127.0.0.1:8000
```

Open local docs:

- Swagger UI: `http://127.0.0.1:8000/api/docs/swagger/`
- ReDoc: `http://127.0.0.1:8000/api/docs/redoc/`
- OpenAPI schema: `http://127.0.0.1:8000/api/schema/`

## Environment Notes

The project reads these optional environment variables:

- `DJANGO_DEBUG` (default `true`)
- `DJANGO_SECRET_KEY` (required when `DJANGO_DEBUG=false`)
- `DJANGO_ALLOWED_HOSTS`
- `DJANGO_CSRF_TRUSTED_ORIGINS`

Default timezone is `Asia/Shanghai`.

## USDA Dataset Import

Dataset source:

- https://www.kaggle.com/datasets/barkataliarbab/usda-fooddata-central-foundation-foods-2025

Required CSV files:

- `food.csv`
- `food_nutrient.csv`
- `nutrient.csv`

Import commands:

```powershell
# Preview only
python manage.py import_food_items --dry-run --source USDA_2025

# Replace existing FoodItem data and import
python manage.py import_food_items --truncate --source USDA_2025
```

If CSV files are elsewhere:

```powershell
python manage.py import_food_items --usda-dir "C:\path\to\dataset_folder" --truncate --source USDA_2025
```

## API Modules

- Auth: `/api/auth/...`
- Food catalog + fuzzy search + favorites + recent: `/api/foods/...`
- Meal logs + summary: `/api/logs/...`
- Profile targets: `/api/profile/targets/`
- Analytics: `/api/analytics/...`

See complete payload examples and endpoint behavior in [API_Documentation.md](./API_Documentation.md).

## Testing

Run full suite:

```powershell
python manage.py test
```

Test coverage focus areas:

- auth and session lifecycle
- food filters and validation
- meal log CRUD + quick/bulk workflows
- cache and rate-limit behavior
- user experience endpoints (favorites/targets)

## Common Local Issue

If you see missing-table errors:

```powershell
python manage.py migrate
```

If local DB is corrupted and you want a clean rebuild:

```powershell
Remove-Item .\db.sqlite3 -Force
python manage.py migrate
```
