from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from nutrition.views import (
    AdvancedAnalyticsAPIView,
    CurrentUserAPIView,
    CustomTokenObtainPairAPIView,
    DailySummaryAPIView,
    FoodFavoriteDeleteAPIView,
    FoodFavoriteListCreateAPIView,
    FoodItemFuzzySearchAPIView,
    FoodItemListAPIView,
    FoodRecentAPIView,
    MealLogBulkCreateAPIView,
    MealLogDetailAPIView,
    MealLogQuickCreateAPIView,
    MealLogListCreateAPIView,
    NutritionTrendsAPIView,
    RegisterAPIView,
    UserNutritionTargetAPIView,
)

urlpatterns = [
    path("auth/register/", RegisterAPIView.as_view(), name="auth-register"),
    path("auth/token/", CustomTokenObtainPairAPIView.as_view(), name="auth-token-obtain-pair"),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="auth-token-refresh"),
    path("auth/me/", CurrentUserAPIView.as_view(), name="auth-me"),
    path("foods/", FoodItemListAPIView.as_view(), name="food-item-list"),
    path("foods/search/", FoodItemFuzzySearchAPIView.as_view(), name="food-item-fuzzy-search"),
    path("foods/recent/", FoodRecentAPIView.as_view(), name="food-item-recent"),
    path("foods/favorites/", FoodFavoriteListCreateAPIView.as_view(), name="food-favorite-list-create"),
    path("foods/favorites/<int:food_item_id>/", FoodFavoriteDeleteAPIView.as_view(), name="food-favorite-delete"),
    path("logs/", MealLogListCreateAPIView.as_view(), name="meal-log-list-create"),
    path("logs/quick/", MealLogQuickCreateAPIView.as_view(), name="meal-log-quick-create"),
    path("logs/bulk/", MealLogBulkCreateAPIView.as_view(), name="meal-log-bulk-create"),
    path("logs/<int:pk>/", MealLogDetailAPIView.as_view(), name="meal-log-detail"),
    path("logs/daily-summary/", DailySummaryAPIView.as_view(), name="meal-log-daily-summary"),
    path("profile/targets/", UserNutritionTargetAPIView.as_view(), name="profile-targets"),
    path("analytics/trends/", NutritionTrendsAPIView.as_view(), name="nutrition-trends"),
    path("analytics/advanced/", AdvancedAnalyticsAPIView.as_view(), name="nutrition-advanced-analytics"),
]
