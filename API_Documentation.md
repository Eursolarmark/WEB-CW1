# MacroTracker API Documentation

Last updated: April 21, 2026  
Project: `MacroTracker_API_Submission3`  
API style: REST (JSON)  
Auth: JWT Bearer (SimpleJWT)

## 1. Overview

MacroTracker API is a nutrition tracking backend with:

- account registration and JWT login
- food catalog query and favorite management
- meal logging (CRUD) with automatic macro calculation
- analytics endpoints for daily summary, trends, and advanced insights

This document is written to match current implementation and assessment requirements:

- all endpoints are listed
- parameters and response formats are documented
- request/response examples are provided
- authentication and error model are explicitly documented

## 2. Base URL and Content Type

Local base URL:

```text
http://127.0.0.1:8000
```

Primary content type:

```text
application/json
```

## 3. Authentication

Protected endpoints require:

```text
Authorization: Bearer <access_token>
```

Token endpoints:

- `POST /api/auth/token/` to obtain `access` + `refresh`
- `POST /api/auth/token/refresh/` to refresh access token

JWT policy (from settings):

- access token lifetime: 15 minutes
- refresh token lifetime: 7 days
- refresh rotation: enabled
- blacklist after rotation: enabled

## 4. Global Behavior

### 4.1 Standard Error Envelope

Errors are wrapped in a unified format:

```json
{
  "code": "validation_error|authentication_failed|permission_denied|resource_not_found|method_not_allowed|rate_limited|internal_error",
  "message": "Human-readable summary",
  "details": {
    "field_or_detail": ["specific issue"]
  },
  "request_id": "trace-id",
  "timestamp": "ISO-8601 datetime"
}
```

### 4.2 Global Headers

- `X-Request-ID`: request trace id
- `X-Cache`: present on cached GET endpoints (`HIT` or `MISS`)
- `X-Idempotent-Replay`: `true` when a POST response is replayed from idempotency cache

### 4.3 Idempotency

Send:

```text
Idempotency-Key: <client-unique-key>
```

Supported endpoints:

- `POST /api/foods/favorites/`
- `POST /api/logs/`

Behavior:

- same user + method + path + key returns cached response
- cache TTL is 1 hour
- 5xx responses are not cached

### 4.4 Caching

Cached endpoints:

- `GET /api/foods/` (120s)
- `GET /api/logs/daily-summary/` (180s)
- `GET /api/analytics/trends/` (180s)
- `GET /api/analytics/advanced/` (180s)

Any meal log write (create/update/delete) bumps analytics cache version for the current user.

### 4.5 Throttling

Configured rates:

- `anon`: `100/hour`
- `user_burst`: `300/minute`
- `auth`: `30/minute`
- `food_lookup`: `240/minute`
- `meal_write`: `60/minute`
- `analytics`: `90/minute`

## 5. Data Conventions

- Decimal values are serialized as strings (for precision), e.g. `"150.00"`.
- `MealLog` nutrition totals (`actual_kcal`, `actual_protein`, etc.) are computed server-side.
- `MealLog` only accepts canonical `food_item` IDs from `FoodItem`.

Enums:

- `meal_type`: `breakfast | lunch | dinner | snack`
- `diet_type`: `high_protein | keto | vegan | vegetarian | omnivore | other`

## 6. Pagination

List endpoints using pagination:

- `GET /api/foods/`
- `GET /api/logs/`

Pagination shape:

```json
{
  "count": 123,
  "next": "http://.../api/.../?page=2",
  "previous": null,
  "results": []
}
```

Defaults:

- default `page_size`: 20
- max `page_size`: 100
- query params: `page`, `page_size`

## 7. Endpoint Reference

### 7.1 Auth

#### POST `/api/auth/register/`

Create a new user account.

Request:

```json
{
  "username": "alice",
  "email": "alice@example.com",
  "password": "StrongPass123!",
  "password_confirm": "StrongPass123!"
}
```

Success `201 Created`:

```json
{
  "id": 1,
  "username": "alice",
  "email": "alice@example.com"
}
```

#### POST `/api/auth/token/`

Obtain JWT pair. `username` field accepts username or email.

Request:

```json
{
  "username": "alice@example.com",
  "password": "StrongPass123!"
}
```

Success `200 OK`:

```json
{
  "refresh": "<refresh_token>",
  "access": "<access_token>"
}
```

#### POST `/api/auth/token/refresh/`

Refresh access token.

Request:

```json
{
  "refresh": "<refresh_token>"
}
```

Success `200 OK`:

```json
{
  "access": "<new_access_token>"
}
```

#### GET `/api/auth/me/`

Get current authenticated user.

Success `200 OK`:

```json
{
  "id": 1,
  "username": "alice",
  "email": "alice@example.com"
}
```

### 7.2 Foods

#### GET `/api/foods/`

List/query food catalog.

Query params (all optional):

- `q`: case-insensitive name search
- `diet_type`: enum value
- `kcal_min`, `kcal_max`
- `protein_min`, `protein_max`
- `carbs_min`, `carbs_max`
- `fat_min`, `fat_max`
- `ordering`:  
  `name|-name|per_100g_kcal|-per_100g_kcal|per_100g_protein|-per_100g_protein|per_100g_carbs|-per_100g_carbs|per_100g_fat|-per_100g_fat`

Success `200 OK`:

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 298,
      "name": "Chicken Breast",
      "diet_type": "high_protein",
      "per_100g_kcal": "165.00",
      "per_100g_protein": "31.00",
      "per_100g_carbs": "0.00",
      "per_100g_fat": "3.60",
      "source": "USDA_2025"
    }
  ]
}
```

#### GET `/api/foods/favorites/`

List current user's favorite foods.

Success `200 OK`:

```json
[
  {
    "id": 2,
    "food_item": 298,
    "food_item_name": "Chicken Breast",
    "created_at": "2026-04-21T09:20:00Z"
  }
]
```

#### POST `/api/foods/favorites/`

Add a favorite food.

Request:

```json
{
  "food_item": 298
}
```

Success `201 Created`:

```json
{
  "id": 2,
  "food_item": 298,
  "food_item_name": "Chicken Breast",
  "created_at": "2026-04-21T09:20:00Z"
}
```

#### DELETE `/api/foods/favorites/{food_item_id}/`

Delete favorite by food id.

- success: `204 No Content`
- if not found: `404 Not Found`

### 7.3 Meal Logs

#### GET `/api/logs/`

List current user's meal logs.

Query params (all optional):

- date filters: `date` or `start_date` + `end_date`
- meal filter: `meal_type` or CSV `meal_types` (e.g. `breakfast,dinner`)
- nutrient filters: `kcal_min|max`, `protein_min|max`, `carbs_min|max`, `fat_min|max`
- `ordering`:  
  `intake_date|-intake_date|created_at|-created_at|actual_kcal|-actual_kcal|actual_protein|-actual_protein|actual_carbs|-actual_carbs|actual_fat|-actual_fat`

Success `200 OK`:

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 11,
      "user": 1,
      "intake_date": "2026-04-21",
      "meal_type": "lunch",
      "food_item": 298,
      "food_item_name": "Chicken Breast",
      "intake_weight_grams": "150.00",
      "actual_kcal": "247.50",
      "actual_protein": "46.50",
      "actual_carbs": "0.00",
      "actual_fat": "5.40",
      "created_at": "2026-04-21T09:30:00Z",
      "updated_at": "2026-04-21T09:30:00Z"
    }
  ]
}
```

#### POST `/api/logs/`

Create one meal log.

Required fields:

- `intake_date`
- `meal_type`
- `food_item`
- `intake_weight_grams`

Request:

```json
{
  "intake_date": "2026-04-21",
  "meal_type": "lunch",
  "food_item": 298,
  "intake_weight_grams": "150.00"
}
```

Success `201 Created`:

```json
{
  "id": 11,
  "user": 1,
  "intake_date": "2026-04-21",
  "meal_type": "lunch",
  "food_item": 298,
  "food_item_name": "Chicken Breast",
  "intake_weight_grams": "150.00",
  "actual_kcal": "247.50",
  "actual_protein": "46.50",
  "actual_carbs": "0.00",
  "actual_fat": "5.40",
  "created_at": "2026-04-21T09:30:00Z",
  "updated_at": "2026-04-21T09:30:00Z"
}
```

#### GET `/api/logs/{id}/`

Retrieve one log (owner-only).

Success `200 OK`: same shape as log object above.

#### PUT `/api/logs/{id}/`

Replace/update one log (owner-only).

Request:

```json
{
  "intake_date": "2026-04-21",
  "meal_type": "dinner",
  "food_item": 298,
  "intake_weight_grams": "200.00"
}
```

Success `200 OK`: updated log object with recalculated nutrition totals.

#### DELETE `/api/logs/{id}/`

Delete one log (owner-only).

- success: `204 No Content`
- if not found: `404 Not Found`

### 7.4 Daily Summary

#### GET `/api/logs/daily-summary/?date=YYYY-MM-DD`

Return daily aggregate totals.

Required query param:

- `date` (ISO date)

Success `200 OK`:

```json
{
  "date": "2026-04-21",
  "log_count": 2,
  "total_kcal": "460.00",
  "total_protein": "64.40",
  "total_carbs": "28.20",
  "total_fat": "7.50"
}
```

### 7.5 Analytics

#### GET `/api/analytics/trends/`

N-day trend view.

Query params:

- `end_date` (optional, default today)
- `days` (optional, default 7, range 1..31)
- `target_kcal` (optional, default `2000.00`)

Success `200 OK` (shortened):

```json
{
  "period": {
    "start_date": "2026-04-15",
    "end_date": "2026-04-21",
    "days": 7,
    "days_with_logs": 3
  },
  "target_kcal_per_day": "2000.00",
  "daily": [
    {
      "date": "2026-04-21",
      "log_count": 2,
      "total_kcal": "1750.00",
      "total_protein": "130.00",
      "total_carbs": "160.00",
      "total_fat": "60.00",
      "kcal_deficit": "250.00"
    }
  ],
  "average": {
    "kcal": "950.00",
    "protein": "66.00",
    "carbs": "90.00",
    "fat": "35.00",
    "kcal_deficit": "1050.00",
    "deficit_interpretation": "average_deficit"
  },
  "insights": {
    "average_status": "below_target",
    "average_kcal_gap": "1050.00",
    "logging_consistency_percent": "42.86",
    "summary": "Average intake is below target by 1050.00 kcal/day."
  }
}
```

#### GET `/api/analytics/advanced/`

Advanced analytics bundle.

Query params:

- `start_date` (optional; default `end_date - 29 days`)
- `end_date` (optional; default today)
- `target_kcal` (optional; default `2000.00`)
- `adherence_tolerance_pct` (optional; default `10.00`)

Success `200 OK` (shortened):

```json
{
  "period": {
    "start_date": "2026-03-23",
    "end_date": "2026-04-21",
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
      "total_protein": "650.00",
      "total_carbs": "900.00",
      "total_fat": "260.00",
      "kcal_share_percent": "40.00"
    }
  ],
  "weekly_trend": [],
  "monthly_trend": [],
  "daily_trend": []
}
```

## 8. Status Codes

- `200 OK`: successful read/update operation
- `201 Created`: successful resource creation
- `204 No Content`: successful deletion
- `400 Bad Request`: validation/parameter errors
- `401 Unauthorized`: missing/invalid credentials
- `403 Forbidden`: permission denied
- `404 Not Found`: resource missing or not owned by user
- `405 Method Not Allowed`: unsupported method (e.g. `PATCH` on `/api/logs/{id}/`)
- `429 Too Many Requests`: throttled
- `500 Internal Server Error`: unexpected server error (wrapped by unified error envelope)

## 9. Documentation and Schema Links

- Swagger UI: `http://127.0.0.1:8000/api/docs/swagger/`
- ReDoc: `http://127.0.0.1:8000/api/docs/redoc/`
- OpenAPI schema: `http://127.0.0.1:8000/api/schema/`
- This Markdown file: `API_Documentation.md`
- PDF version: `API_Documentation.pdf`

