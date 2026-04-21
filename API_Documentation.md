# MacroTracker API Documentation

## 1. Overview

MacroTracker API is a per-user nutrition tracking backend.
It supports authentication, food lookup, meal logging, personalization, and analytics.

Base URL (local):

```text
http://127.0.0.1:8000
```

Primary content type:

```text
application/json
```

## 2. Authentication and Global Headers

Protected endpoints require:

```text
Authorization: Bearer <access_token>
```

JWT policy:

- `access` lifetime: 15 minutes
- `refresh` lifetime: 7 days
- refresh rotation: enabled
- blacklist after rotation: enabled

Global response headers:

- `X-Request-ID`: request trace ID (generated or echoed)
- `X-Cache`: only on cached GET endpoints (`HIT` or `MISS`)
- `X-Idempotent-Replay`: present with `true` when a write response is replayed from idempotency cache

## 3. Cross-Cutting Behavior

### 3.1 Idempotency for Write Endpoints

You can send:

```text
Idempotency-Key: <client-generated-unique-key>
```

Supported endpoints:

- `POST /api/foods/favorites/`
- `POST /api/logs/`

Behavior:

- Duplicate request with same key/user/method/path returns cached response.
- Replay response includes `X-Idempotent-Replay: true`.
- Idempotency cache TTL is 1 hour.

### 3.2 Caching

Cached endpoints:

- `GET /api/foods/` (TTL 120s)
- `GET /api/logs/daily-summary/` (TTL 180s)
- `GET /api/analytics/trends/` (TTL 180s)
- `GET /api/analytics/advanced/` (TTL 180s)

Meal-log writes bump user analytics cache version, so analytics cache is invalidated after create/update/delete.

### 3.3 Throttling

Configured rates:

- `anon`: `100/hour`
- `user_burst`: `300/minute`
- `auth`: `30/minute`
- `food_lookup`: `240/minute`
- `meal_write`: `60/minute`
- `analytics`: `90/minute`

### 3.4 Unified Error Envelope

Handled errors return this shape:

```json
{
  "code": "validation_error|authentication_failed|permission_denied|resource_not_found|method_not_allowed|rate_limited|internal_error",
  "message": "Human-readable summary",
  "details": {
    "field_or_detail": ["specific details"]
  },
  "request_id": "<trace_id>",
  "timestamp": "ISO-8601 datetime"
}
```

## 4. Core Data Rules

### 4.1 Food Source Rule

`MealLog` only accepts `food_item` (official food catalog item).

### 4.2 Weight Input Rule

Meal log create endpoints require:

- `intake_weight_grams`

## 5. Endpoint Reference

Pagination for list endpoints (when applicable):

- default `page_size`: 20
- max `page_size`: 100
- query params: `page`, `page_size`

---

## 5.1 Auth Endpoints

### POST `/api/auth/register/`

Create account.

Request:

```json
{
  "username": "alice",
  "email": "alice@example.com",
  "password": "StrongPass123!",
  "password_confirm": "StrongPass123!"
}
```

Success: `201 Created`

```json
{
  "id": 1,
  "username": "alice",
  "email": "alice@example.com"
}
```

### POST `/api/auth/token/`

Obtain JWT pair. `username` field accepts username **or** email.

Request:

```json
{
  "username": "alice@example.com",
  "password": "StrongPass123!"
}
```

Success: `200 OK`

```json
{
  "refresh": "<refresh_token>",
  "access": "<access_token>"
}
```

### POST `/api/auth/token/refresh/`

Request:

```json
{
  "refresh": "<refresh_token>"
}
```

Success: `200 OK`

```json
{
  "access": "<new_access_token>"
}
```

### GET `/api/auth/me/`

Return current authenticated user.

Success: `200 OK`

```json
{
  "id": 1,
  "username": "alice",
  "email": "alice@example.com"
}
```

---

## 5.2 Food Catalog and Favorites

### GET `/api/foods/`

List food catalog items.

Query params:

- `q`
- `diet_type` in `high_protein|keto|vegan|vegetarian|omnivore|other`
- `kcal_min`, `kcal_max`
- `protein_min`, `protein_max`
- `carbs_min`, `carbs_max`
- `fat_min`, `fat_max`
- `ordering` in `name|-name|per_100g_kcal|-per_100g_kcal|per_100g_protein|-per_100g_protein|per_100g_carbs|-per_100g_carbs|per_100g_fat|-per_100g_fat`

Success: `200 OK`

```json
{
  "count": 295,
  "next": null,
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

### GET `/api/foods/favorites/`

List favorites.

Success: `200 OK`

```json
[
  {
    "id": 2,
    "food_item": 298,
    "food_item_name": "Hummus, Commercial",
    "created_at": "2026-04-17T10:10:00Z"
  }
]
```

### POST `/api/foods/favorites/`

Create favorite.

Request:

```json
{
  "food_item": 298
}
```

Success: `201 Created`

### DELETE `/api/foods/favorites/{food_item_id}/`

Delete favorite by `food_item_id`.

- success: `204 No Content`
- not found: `404 Not Found`

---

## 5.3 Meal Logs

### GET `/api/logs/`

List current user logs.

Query params:

- date range: `date` or `start_date` + `end_date`
- meal filter: `meal_type` or CSV `meal_types` (e.g. `breakfast,dinner`)
- nutrient range: `kcal_min|max`, `protein_min|max`, `carbs_min|max`, `fat_min|max`
- ordering: `intake_date|-intake_date|created_at|-created_at|actual_kcal|-actual_kcal|actual_protein|-actual_protein|actual_carbs|-actual_carbs|actual_fat|-actual_fat`

### POST `/api/logs/`

Create one log.

Request (grams mode):

```json
{
  "intake_date": "2026-04-17",
  "meal_type": "lunch",
  "food_item": 298,
  "intake_weight_grams": "150.00"
}
```

### GET `/api/logs/{id}/`

Retrieve single log (owner only).

### PUT `/api/logs/{id}/`

Update log (owner only).

### DELETE `/api/logs/{id}/`

Delete log (owner only), returns `204 No Content`.

### GET `/api/logs/daily-summary/?date=YYYY-MM-DD`

Return totals for one day.

Success: `200 OK`

```json
{
  "date": "2026-04-17",
  "log_count": 2,
  "total_kcal": "460.00",
  "total_protein": "64.40",
  "total_carbs": "28.20",
  "total_fat": "7.50"
}
```

---

## 5.4 Analytics

### GET `/api/analytics/trends/`

N-day trend summary.

Query params:

- `end_date` (optional, default today)
- `days` (optional, default 7, range 1..31)
- `target_kcal` (optional)

If `target_kcal` is omitted, it defaults to `2000.00`.

Success: `200 OK` (shortened)

```json
{
  "period": {
    "start_date": "2026-04-11",
    "end_date": "2026-04-17",
    "days": 7,
    "days_with_logs": 3
  },
  "target_kcal_per_day": "2000.00",
  "daily": [
    {
      "date": "2026-04-17",
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

### GET `/api/analytics/advanced/`

Advanced analytics bundle.

Query params:

- `start_date` (optional; default `end_date - 29 days`)
- `end_date` (optional; default today)
- `target_kcal` (optional; defaults to `2000.00`)
- `adherence_tolerance_pct` (optional; default `10.00`)

Success: `200 OK` (shortened)

```json
{
  "period": {
    "start_date": "2026-03-19",
    "end_date": "2026-04-17",
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

## 6. Common Status Codes

- `200 OK`: successful read/update/operation
- `201 Created`: resource created
- `204 No Content`: successful delete
- `400 Bad Request`: validation or request parameter issues
- `401 Unauthorized`: missing/invalid auth credentials
- `403 Forbidden`: permission denied
- `404 Not Found`: resource not found or not owned by user
- `405 Method Not Allowed`: unsupported HTTP method
- `429 Too Many Requests`: throttled
- `500 Internal Server Error`: unhandled server exception wrapped by standard error model

## 7. Interactive Docs and Schema

- Swagger UI: `http://127.0.0.1:8000/api/docs/swagger/`
- ReDoc: `http://127.0.0.1:8000/api/docs/redoc/`
- OpenAPI schema: `http://127.0.0.1:8000/api/schema/`
