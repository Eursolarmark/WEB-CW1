# MacroTracker API

Nutrition and meal tracking backend built with Django + DRF.

Detailed API examples: [API_Documentation.md](./API_Documentation.md)
Version notes: [CHANGELOG.md](./CHANGELOG.md)

## Quick Start (Most Common)

Requirements:
- Python `3.12+`
- `pip`

From project root:

```powershell
cd <project_root>

python -m venv .venv
.\.venv\Scripts\Activate.ps1
# If activation is blocked by policy:
# Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

python manage.py migrate
python manage.py check
python manage.py runserver 127.0.0.1:8000
```

Open:
- Swagger: `http://127.0.0.1:8000/api/docs/swagger/`
- ReDoc: `http://127.0.0.1:8000/api/docs/redoc/`

## Conda Quick Start (If venv/py launcher fails)

```powershell
conda create -n macrotracker312 python=3.12 -y
conda activate macrotracker312

cd <project_root>
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

python manage.py migrate
python manage.py runserver 127.0.0.1:8000
```

## Import USDA CSV Data
Data from https://www.kaggle.com/datasets/barkataliarbab/usda-fooddata-central-foundation-foods-2025
Required files:
- `food.csv`
- `food_nutrient.csv`
- `nutrient.csv`
I have put them in the folder "dataset"

Default behavior: command auto-detects these files in project root, `data/`, `dataset/`, or `datasets/`.

```powershell
# Preview only
python manage.py import_food_items --dry-run --source USDA_2025

# Real import (replace existing FoodItem data)
python manage.py import_food_items --truncate --source USDA_2025
```

If files are somewhere else:

```powershell
python manage.py import_food_items --usda-dir "C:\path\to\dataset_folder" --truncate --source USDA_2025
```

## Common Issues

`django.db.utils.OperationalError: no such table: nutrition_fooditem`

```powershell
python manage.py migrate
```

If local DB is broken:

```powershell
Remove-Item .\db.sqlite3 -Force
python manage.py migrate
```

## Testing

Run the automated test suite:

```powershell
python manage.py test
```

Current test scope:
- Auth flow (register + JWT token/refresh)
- Food endpoints (list/filter/validation)
- Meal log CRUD and user-level data isolation
- Analytics endpoints and model calculation behavior

## Version Timeline

- `v0.1`: Initial working API with auth, CRUD, and analytics endpoints.
- `v0.2`: Added automated test suite (20 tests) to improve reliability.
- `v1.0`: Planned advanced capabilities (throttling, caching, advanced filters, unified error model).
