# MacroTracker API Documentation

## 1. Overview

MacroTracker API provides nutrition and meal tracking services with per-user data isolation.
All business endpoints are authenticated (JWT bearer token recommended).

Base URL (local):

```text
http://127.0.0.1:8000
```

Content type:

```text
application/json
```

## 2. Authentication

Protected endpoints require:

```text
Authorization: Bearer <access_token>
```

Note:

- JWT is the primary authentication mechanism.
- Session authentication is also enabled for browser-based API exploration.

### 2.1 Register

- Method: `POST`
- URL: `/api/auth/register/`
- Auth required: No

Request body:

```json
{
  "username": "alice",
  "email": "alice@example.com",
  "password": "StrongPass123!",
  "password_confirm": "StrongPass123!"
}
```

Success response (`201 Created`):

```json
{
  "id": 1,
  "username": "alice",
  "email": "alice@example.com"
}
```

### 2.2 Obtain JWT Token Pair

- Method: `POST`
- URL: `/api/auth/token/`
- Auth required: No

Request body:

```json
{
  "username": "alice",
  "password": "StrongPass123!"
}
```

Success response (`200 OK`):

```json
{
  "refresh": "<refresh_token>",
  "access": "<access_token>"
}
```

### 2.3 Refresh Access Token

- Method: `POST`
- URL: `/api/auth/token/refresh/`
- Auth required: No

Request body:

```json
{
  "refresh": "<refresh_token>"
}
```

Success response (`200 OK`):

```json
{
  "access": "<new_access_token>"
}
```

## 3. Data Models

### 3.1 FoodItem

- `id` (int)
- `name` (string, unique)
- `diet_type` (enum): `high_protein`, `keto`, `vegan`, `vegetarian`, `omnivore`, `other`
- `per_100g_kcal` (decimal)
- `per_100g_protein` (decimal)
- `per_100g_carbs` (decimal)
- `per_100g_fat` (decimal)
- `source` (string)

### 3.2 MealLog

- `id` (int)
- `user` (int, owner user ID)
- `intake_date` (date)
- `meal_type` (enum): `breakfast`, `lunch`, `dinner`, `snack`
- `food_item` (int, FK to FoodItem)
- `intake_weight_grams` (decimal, `> 0`)
- `actual_kcal` (decimal, auto-calculated)
- `actual_protein` (decimal, auto-calculated)
- `actual_carbs` (decimal, auto-calculated)
- `actual_fat` (decimal, auto-calculated)
- `created_at` (datetime)
- `updated_at` (datetime)

Auto-calculation formula:

```text
actual_metric = (intake_weight_grams / 100) * per_100g_metric
```

## 4. Endpoints

List endpoints use DRF page-number pagination:

- Default `page_size`: `20`
- Max `page_size`: `100`
- Common query params: `page`, `page_size`

## 4.1 Food Catalog

### GET /api/foods/

- Auth required: Yes
- Description: List food items (for `food_item` ID lookup)

Query params:

- `q` (optional): fuzzy search by food name
- `diet_type` (optional): filter by enum value
- `page` (optional): page number, starts from `1`
- `page_size` (optional): `1..100`

Example:

```text
GET /api/foods/?q=rice&diet_type=vegan
```

Success response (`200 OK`):

```json
{
  "count": 295,
  "next": "http://127.0.0.1:8000/api/foods/?page=2",
  "previous": null,
  "results": [
    {
      "id": 396,
      "name": "Flour, Rice, Brown",
      "diet_type": "vegan",
      "per_100g_kcal": "365.25",
      "per_100g_protein": "7.19",
      "per_100g_carbs": "75.50",
      "per_100g_fat": "3.85",
      "source": "USDA_2025"
    }
  ]
}
```

## 4.2 Meal Logs

### GET /api/logs/

- Auth required: Yes
- Description: List current user's meal logs

Query params:

- `date` (optional): `YYYY-MM-DD`
- `page` (optional): page number, starts from `1`
- `page_size` (optional): `1..100`

Success response (`200 OK`, shortened):

```json
{
  "count": 8,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 9,
      "user": 1,
      "intake_date": "2026-04-13",
      "meal_type": "lunch",
      "food_item": 298,
      "food_item_name": "Hummus, Commercial",
      "intake_weight_grams": "150.00",
      "actual_kcal": "249.90",
      "actual_protein": "11.94",
      "actual_carbs": "20.61",
      "actual_fat": "14.58",
      "created_at": "2026-04-14T10:30:00Z",
      "updated_at": "2026-04-14T10:30:00Z"
    }
  ]
}
```

Validation error example (`400 Bad Request`):

```json
{
  "date": ["Date has wrong format. Use one of these formats instead: YYYY-MM-DD."]
}
```

### POST /api/logs/

- Auth required: Yes
- Description: Create a meal log for current user

Request body:

```json
{
  "intake_date": "2026-04-13",
  "meal_type": "lunch",
  "food_item": 298,
  "intake_weight_grams": "150.00"
}
```

Success response (`201 Created`):

```json
{
  "id": 9,
  "user": 1,
  "intake_date": "2026-04-13",
  "meal_type": "lunch",
  "food_item": 298,
  "food_item_name": "Hummus, Commercial",
  "intake_weight_grams": "150.00",
  "actual_kcal": "249.90",
  "actual_protein": "11.94",
  "actual_carbs": "20.61",
  "actual_fat": "14.58",
  "created_at": "2026-04-14T10:30:00Z",
  "updated_at": "2026-04-14T10:30:00Z"
}
```

Common error (`400 Bad Request`):

```json
{
  "food_item": ["Invalid pk \"999999\" - object does not exist."]
}
```

### GET /api/logs/{id}/

- Auth required: Yes
- Description: Retrieve one meal log (owner only)
- Success: `200 OK`
- Not found / not owner: `404 Not Found`

### PUT /api/logs/{id}/

- Auth required: Yes
- Description: Full update (owner only)
- Success: `200 OK`
- Invalid input: `400 Bad Request`
- Not found / not owner: `404 Not Found`

### PATCH /api/logs/{id}/

- Auth required: Yes
- Description: Partial update (owner only)
- Success: `200 OK`
- Invalid input: `400 Bad Request`
- Not found / not owner: `404 Not Found`

### DELETE /api/logs/{id}/

- Auth required: Yes
- Description: Delete meal log (owner only)
- Success: `204 No Content`
- Not found / not owner: `404 Not Found`

## 4.3 Analytics

### GET /api/logs/daily-summary/

- Auth required: Yes
- Description: Daily nutrient summary for current user

Query params:

- `date` (required): `YYYY-MM-DD`

Success response (`200 OK`):

```json
{
  "date": "2026-04-13",
  "log_count": 2,
  "total_kcal": "460.00",
  "total_protein": "64.40",
  "total_carbs": "28.20",
  "total_fat": "7.50"
}
```

Validation error (`400 Bad Request`):

```json
{
  "date": ["This field is required."]
}
```

### GET /api/analytics/trends/

- Auth required: Yes
- Description: N-day trend (default 7 days) with calorie deficit/surplus

Query params:

- `end_date` (optional): `YYYY-MM-DD`, default today
- `days` (optional): `1..31`, default `7`
- `target_kcal` (optional): default `2000`

Success response (`200 OK`, shortened):

```json
{
  "period": {
    "start_date": "2026-04-07",
    "end_date": "2026-04-13",
    "days": 7,
    "days_with_logs": 2
  },
  "target_kcal_per_day": "2000.00",
  "daily": [
    {
      "date": "2026-04-13",
      "log_count": 1,
      "total_kcal": "330.00",
      "kcal_deficit": "1670.00"
    }
  ],
  "average": {
    "kcal": "102.86",
    "kcal_deficit": "1897.14",
    "deficit_interpretation": "average_deficit"
  }
}
```

### GET /api/analytics/advanced/

- Auth required: Yes
- Description: Advanced analytics bundle

Query params:

- `start_date` (optional): default `end_date - 29 days`
- `end_date` (optional): default today
- `target_kcal` (optional): default `2000`
- `adherence_tolerance_pct` (optional): default `10`

Success response (`200 OK`, shortened):

```json
{
  "period": {
    "start_date": "2026-04-01",
    "end_date": "2026-04-30",
    "days": 30,
    "days_with_logs": 12
  },
  "totals": {
    "kcal": "24500.00",
    "protein": "1320.00",
    "carbs": "2900.00",
    "fat": "780.00",
    "avg_daily_kcal": "816.67"
  },
  "macro_ratio_percent": {
    "protein": "21.55",
    "carbs": "47.35",
    "fat": "31.10"
  },
  "target_achievement": {
    "target_kcal_per_day": "2000.00",
    "adherence_tolerance_pct": "10.00",
    "logged_days": 12,
    "days_met_target": 5,
    "adherence_rate_percent": "41.67",
    "average_kcal_gap": "420.83"
  },
  "meal_type_breakdown": [
    {
      "meal_type": "lunch",
      "log_count": 15,
      "total_kcal": "9800.00",
      "kcal_share_percent": "40.00"
    }
  ],
  "weekly_trend": [
    {
      "week_start": "2026-04-06",
      "logged_days": 4,
      "total_kcal": "7800.00",
      "avg_daily_kcal": "1950.00"
    }
  ],
  "monthly_trend": [
    {
      "month": "2026-04",
      "logged_days": 12,
      "total_kcal": "24500.00",
      "avg_daily_kcal": "2041.67"
    }
  ],
  "daily_trend": [
    {
      "date": "2026-04-13",
      "log_count": 2,
      "total_kcal": "2100.00",
      "kcal_7day_moving_avg": "1988.57"
    }
  ]
}
```

Validation error example (`400 Bad Request`):

```json
{
  "start_date": ["start_date must be earlier than or equal to end_date."]
}
```

## 5. Standard Status Codes

- `200 OK`: Read/update success
- `201 Created`: Resource created
- `204 No Content`: Delete success
- `400 Bad Request`: Validation or parameter error
- `401 Unauthorized`: Missing/invalid authentication
- `404 Not Found`: Resource does not exist or not accessible by current user

## 6. Data Source

Kaggle dataset used:

https://www.kaggle.com/datasets/barkataliarbab/usda-fooddata-central-foundation-foods-2025

Required CSV files:

- `food.csv`
- `food_nutrient.csv`
- `nutrient.csv`

Import command:

```text
python manage.py import_food_items --truncate --source USDA_2025
```

Notes:

- Place the three files in project root or `data/` folder for auto-detection.
- Use `--usda-dir <path>` if files are stored elsewhere.

## 7. Interactive Documentation

- Swagger UI: `http://127.0.0.1:8000/api/docs/swagger/`
- ReDoc: `http://127.0.0.1:8000/api/docs/redoc/`
- Schema endpoint: `http://127.0.0.1:8000/api/schema/`
