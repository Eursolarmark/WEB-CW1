from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from nutrition.views import (
    AdvancedAnalyticsAPIView,
    CurrentUserAPIView,
    CustomTokenObtainPairAPIView,
    DailySummaryAPIView,
    FoodItemListAPIView,
    LogoutAPIView,
    MealLogDetailAPIView,
    MealLogListCreateAPIView,
    NutritionTrendsAPIView,
    RegisterAPIView,
)

urlpatterns = [
    path("auth/register/", RegisterAPIView.as_view(), name="auth-register"),
    path("auth/token/", CustomTokenObtainPairAPIView.as_view(), name="auth-token-obtain-pair"),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="auth-token-refresh"),
    path("auth/me/", CurrentUserAPIView.as_view(), name="auth-me"),
    path("auth/logout/", LogoutAPIView.as_view(), name="auth-logout"),
    path("foods/", FoodItemListAPIView.as_view(), name="food-item-list"),
    path("logs/", MealLogListCreateAPIView.as_view(), name="meal-log-list-create"),
    path("logs/<int:pk>/", MealLogDetailAPIView.as_view(), name="meal-log-detail"),
    path("logs/daily-summary/", DailySummaryAPIView.as_view(), name="meal-log-daily-summary"),
    path("analytics/trends/", NutritionTrendsAPIView.as_view(), name="nutrition-trends"),
    path("analytics/advanced/", AdvancedAnalyticsAPIView.as_view(), name="nutrition-advanced-analytics"),
]
