from __future__ import annotations

import hashlib
from datetime import date, datetime
from decimal import Decimal

from django.core.cache import cache

FOOD_LIST_CACHE_TIMEOUT_SECONDS = 120
ANALYTICS_CACHE_TIMEOUT_SECONDS = 180
_ANALYTICS_VERSION_PREFIX = "analytics:version"


def _normalize_param_value(value) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, list):
        return ",".join(_normalize_param_value(item) for item in value)
    return str(value)


def _hash_params(params: dict) -> str:
    normalized_items = sorted((str(key), _normalize_param_value(value)) for key, value in params.items())
    raw = "&".join(f"{key}={value}" for key, value in normalized_items)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_food_list_cache_key(user_id: int, params: dict) -> str:
    digest = _hash_params(params)
    return f"foods:list:user:{user_id}:query:{digest}"


def get_analytics_cache_version(user_id: int) -> int:
    key = f"{_ANALYTICS_VERSION_PREFIX}:{user_id}"
    version = cache.get(key)
    if version is None:
        cache.set(key, 1, timeout=None)
        return 1
    return int(version)


def bump_analytics_cache_version(user_id: int) -> int:
    key = f"{_ANALYTICS_VERSION_PREFIX}:{user_id}"
    try:
        return int(cache.incr(key))
    except ValueError:
        cache.set(key, 2, timeout=None)
        return 2


def build_analytics_cache_key(endpoint: str, user_id: int, params: dict) -> str:
    version = get_analytics_cache_version(user_id)
    digest = _hash_params(params)
    return f"analytics:{endpoint}:user:{user_id}:v:{version}:query:{digest}"
