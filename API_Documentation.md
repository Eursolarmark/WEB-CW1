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
- blacklist after rotation/logout: enabled

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
- `POST /api/custom-foods/`
- `POST /api/recipes/`
- `POST /api/logs/`
- `POST /api/logs/quick/`
- `POST /api/logs/bulk/`

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

For `MealLog` and `RecipeItem`, exactly one source must be provided:

- `food_item` **or** `custom_food`

Providing both or neither is invalid.

### 4.2 Weight Input Rule

Meal log create endpoints support either:

- direct grams: `intake_weight_grams`
- unit conversion: `unit` + `unit_quantity`

Supported units and conversion:

- `g`, `gram`, `grams` -> 1g
- `piece` -> 50g
- `cup` -> 240g
- `tbsp` -> 15g

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

### POST `/api/auth/logout/`

Blacklist refresh token.

Request:

```json
{
  "refresh": "<refresh_token>"
}
```

Success: `205 Reset Content`

### POST `/api/auth/password/change/`

Request:

```json
{
  "old_password": "StrongPass123!",
  "new_password": "NewStrongPass123!",
  "new_password_confirm": "NewStrongPass123!"
}
```

Success: `200 OK`

### POST `/api/auth/password/reset/request/`

Request:

```json
{
  "email": "alice@example.com"
}
```

Success: `200 OK`

```json
{
  "message": "If the email exists, reset instructions are prepared."
}
```

In `DEBUG=true`, response also includes `uid` and `token` for coursework/development testing.

### POST `/api/auth/password/reset/confirm/`

Request:

```json
{
  "uid": "<uid>",
  "token": "<reset_token>",
  "new_password": "AnotherStrongPass123!",
  "new_password_confirm": "AnotherStrongPass123!"
}
```

Success: `200 OK`

### GET `/api/auth/sessions/`

List active (non-blacklisted) refresh-token sessions.

Success: `200 OK`

```json
{
  "sessions": [
    {
      "jti": "<token-jti>",
      "created_at": "2026-04-17T10:30:00Z",
      "expires_at": "2026-04-24T10:30:00Z"
    }
  ]
}
```

### POST `/api/auth/sessions/revoke-all/`

Blacklist all outstanding refresh tokens for current user.

Success: `200 OK`

```json
{
  "revoked_sessions": 3
}
```

### DELETE `/api/auth/account/`

Delete current user account.

Request:

```json
{
  "password": "StrongPass123!"
}
```

Success: `204 No Content`

### GET `/api/auth/export/`

Export key user data.

Success: `200 OK`

```json
{
  "user": {"id": 1, "username": "alice", "email": "alice@example.com"},
  "nutrition_target": {
    "target_kcal": "2000.00",
    "target_protein": "120.00",
    "target_carbs": "220.00",
    "target_fat": "67.00",
    "updated_at": "2026-04-17T11:00:00Z"
  },
  "favorites": [],
  "custom_food_items": [],
  "meal_logs": []
}
```

---

## 5.2 Food Catalog, Recent, Favorites

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

### GET `/api/foods/recent/`

List foods recently logged by current user.

Query params:

- `limit` (optional, default 20, range 1..100)

Success: `200 OK`

```json
[
  {
    "food_item": 298,
    "food_item_name": "Hummus, Commercial",
    "last_used_at": "2026-04-17T10:00:00Z",
    "use_count": 4
  }
]
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

## 5.3 Custom Foods

### GET `/api/custom-foods/`

List current user custom foods.

### POST `/api/custom-foods/`

Create custom food.

Request:

```json
{
  "name": "My Oat Bowl",
  "per_100g_kcal": "150.00",
  "per_100g_protein": "6.00",
  "per_100g_carbs": "24.00",
  "per_100g_fat": "3.00"
}
```

Success: `201 Created`

### GET `/api/custom-foods/{id}/`

Retrieve one custom food (owner only).

### PUT/PATCH `/api/custom-foods/{id}/`

Update custom food (owner only).

### DELETE `/api/custom-foods/{id}/`

Delete custom food (owner only).

---

## 5.4 Recipes

### GET `/api/recipes/`

List current user recipe templates.

### POST `/api/recipes/`

Create recipe.

Request:

```json
{
  "name": "Breakfast Bowl",
  "description": "Demo recipe",
  "items": [
    {"food_item": 298, "weight_grams": "100.00"},
    {"custom_food": 5, "weight_grams": "150.00"}
  ]
}
```

Success: `201 Created`

```json
{
  "id": 1,
  "name": "Breakfast Bowl",
  "description": "Demo recipe",
  "items": [
    {
      "id": 1,
      "food_item": 298,
      "food_item_name": "Hummus, Commercial",
      "custom_food": null,
      "custom_food_name": null,
      "weight_grams": "100.00"
    },
    {
      "id": 2,
      "food_item": null,
      "food_item_name": null,
      "custom_food": 5,
      "custom_food_name": "Custom Yogurt",
      "weight_grams": "150.00"
    }
  ],
  "total_kcal": "239.00",
  "total_protein": "25.00",
  "total_carbs": "34.80",
  "total_fat": "3.60",
  "created_at": "2026-04-17T11:00:00Z",
  "updated_at": "2026-04-17T11:00:00Z"
}
```

### GET `/api/recipes/{id}/`

Retrieve one recipe (owner only).

### PUT/PATCH `/api/recipes/{id}/`

Update recipe (owner only). If `items` is included, existing items are replaced.

### DELETE `/api/recipes/{id}/`

Delete recipe (owner only).

---

## 5.5 Meal Logs

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

Request (unit mode):

```json
{
  "intake_date": "2026-04-17",
  "meal_type": "snack",
  "food_item": 298,
  "unit": "piece",
  "unit_quantity": "2.00"
}
```

`food_item` can be replaced with `custom_food`.

### POST `/api/logs/quick/`

Quick create by `food_name` (matches exact name in `FoodItem`, then user `CustomFoodItem`).

Request:

```json
{
  "food_name": "banana",
  "intake_date": "2026-04-17",
  "meal_type": "snack",
  "unit": "piece",
  "unit_quantity": "1.00"
}
```

On no exact match: `400 Bad Request` with candidate suggestions.

### POST `/api/logs/bulk/`

Bulk create logs (`items` length 1..100).

Request:

```json
{
  "items": [
    {
      "intake_date": "2026-04-17",
      "meal_type": "breakfast",
      "food_item": 298,
      "intake_weight_grams": "100.00"
    },
    {
      "intake_date": "2026-04-17",
      "meal_type": "lunch",
      "custom_food": 5,
      "unit": "cup",
      "unit_quantity": "0.50"
    }
  ]
}
```

Success: `201 Created`

```json
{
  "created": 2,
  "results": [
    {"id": 11, "meal_type": "breakfast", "actual_kcal": "120.00"},
    {"id": 12, "meal_type": "lunch", "actual_kcal": "180.00"}
  ]
}
```

### GET `/api/logs/{id}/`

Retrieve single log (owner only).

### PUT/PATCH `/api/logs/{id}/`

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

## 5.6 Profile Targets

### GET `/api/profile/targets/`

Get current user nutrition target.

### PUT `/api/profile/targets/`

Update target.

Request:

```json
{
  "target_kcal": "2100.00",
  "target_protein": "140.00",
  "target_carbs": "220.00",
  "target_fat": "70.00"
}
```

Success: `200 OK`

```json
{
  "target_kcal": "2100.00",
  "target_protein": "140.00",
  "target_carbs": "220.00",
  "target_fat": "70.00",
  "updated_at": "2026-04-17T11:22:00Z"
}
```

---

## 5.7 Analytics

### GET `/api/analytics/trends/`

N-day trend summary.

Query params:

- `end_date` (optional, default today)
- `days` (optional, default 7, range 1..31)
- `target_kcal` (optional)

If `target_kcal` is omitted:

- uses `/api/profile/targets/` -> `target_kcal` when available
- falls back to `2000.00`

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
- `target_kcal` (optional; profile target default then `2000.00`)
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
- `205 Reset Content`: logout success
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
