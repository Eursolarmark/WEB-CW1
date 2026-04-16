from rest_framework.throttling import UserRateThrottle


class BurstUserRateThrottle(UserRateThrottle):
    scope = "user_burst"


class FoodLookupRateThrottle(UserRateThrottle):
    scope = "food_lookup"


class MealWriteRateThrottle(UserRateThrottle):
    scope = "meal_write"


class AnalyticsRateThrottle(UserRateThrottle):
    scope = "analytics"
