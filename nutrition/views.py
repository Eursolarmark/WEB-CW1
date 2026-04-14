from datetime import timedelta

from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from nutrition.models import FoodItem, MealLog
from nutrition.pagination import StandardResultsSetPagination
from nutrition.serializers import (
    AdvancedAnalyticsQuerySerializer,
    AdvancedAnalyticsResponseSerializer,
    DailySummaryResponseSerializer,
    DailySummaryQuerySerializer,
    FoodItemListQuerySerializer,
    FoodItemSerializer,
    MealLogListQuerySerializer,
    MealLogSerializer,
    RegisterSerializer,
    TrendsResponseSerializer,
    TrendsQuerySerializer,
)
from nutrition.services import NutritionAnalyticsService


class RegisterAPIView(generics.CreateAPIView):
    """
    /api/auth/register/
    - POST: Create a user account
    """

    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]


class MealLogListCreateAPIView(generics.ListCreateAPIView):
    """
    /api/logs/
    - POST: Create a meal log entry
    - GET: List meal logs (optional filter by intake_date via ?date=YYYY-MM-DD)
    """

    serializer_class = MealLogSerializer
    queryset = MealLog.objects.select_related("food_item").all()
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        queryset = super().get_queryset().filter(user=self.request.user)
        query_serializer = MealLogListQuerySerializer(data=self.request.query_params)
        query_serializer.is_valid(raise_exception=True)
        date_value = query_serializer.validated_data.get("date")
        if date_value:
            queryset = queryset.filter(intake_date=date_value)
        return queryset

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class FoodItemListAPIView(generics.ListAPIView):
    """
    /api/foods/
    - GET: List available food items to retrieve valid food_item IDs.
    Optional query params:
      - q: case-insensitive search in name
      - diet_type: filter by enum value (e.g. vegan/high_protein)
    """

    serializer_class = FoodItemSerializer
    queryset = FoodItem.objects.all().order_by("name")
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        queryset = super().get_queryset()
        query_serializer = FoodItemListQuerySerializer(data=self.request.query_params)
        query_serializer.is_valid(raise_exception=True)
        q = query_serializer.validated_data.get("q")
        diet_type = query_serializer.validated_data.get("diet_type")

        if q:
            queryset = queryset.filter(name__icontains=q.strip())
        if diet_type:
            queryset = queryset.filter(diet_type=diet_type.strip())
        return queryset


class MealLogDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    """
    /api/logs/{id}/
    - PUT/PATCH: Update meal log
    - DELETE: Remove meal log
    """

    serializer_class = MealLogSerializer
    queryset = MealLog.objects.select_related("food_item").all()
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return super().get_queryset().filter(user=self.request.user)


class DailySummaryAPIView(APIView):
    """
    /api/logs/daily-summary/?date=YYYY-MM-DD
    Return total kcal/protein/carbs/fat for the given date.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[DailySummaryQuerySerializer],
        responses={200: DailySummaryResponseSerializer},
    )
    def get(self, request, *args, **kwargs):
        query_serializer = DailySummaryQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)

        payload = NutritionAnalyticsService.get_daily_summary(
            user=request.user,
            target_date=query_serializer.validated_data["date"]
        )
        return Response(payload, status=status.HTTP_200_OK)


class NutritionTrendsAPIView(APIView):
    """
    /api/analytics/trends/
    Optional query params:
      - end_date=YYYY-MM-DD (default: today)
      - days=7 (default: 7, allowed 1-31)
      - target_kcal=2000 (default: 2000)
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[TrendsQuerySerializer],
        responses={200: TrendsResponseSerializer},
    )
    def get(self, request, *args, **kwargs):
        query_serializer = TrendsQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)

        end_date = query_serializer.validated_data.get("end_date", timezone.localdate())
        days = query_serializer.validated_data["days"]
        target_kcal = query_serializer.validated_data["target_kcal"]

        payload = NutritionAnalyticsService.get_7day_trends(
            user=request.user,
            end_date=end_date,
            days=days,
            target_kcal=target_kcal,
        )
        return Response(payload, status=status.HTTP_200_OK)


class AdvancedAnalyticsAPIView(APIView):
    """
    /api/analytics/advanced/
    Provides advanced insights:
      - macro ratio percentages
      - target achievement
      - meal type breakdown
      - weekly/monthly trends
      - daily trend with 7-day moving average
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[AdvancedAnalyticsQuerySerializer],
        responses={200: AdvancedAnalyticsResponseSerializer},
    )
    def get(self, request, *args, **kwargs):
        query_serializer = AdvancedAnalyticsQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)

        end_date = query_serializer.validated_data.get("end_date", timezone.localdate())
        start_date = query_serializer.validated_data.get("start_date", end_date - timedelta(days=29))
        target_kcal = query_serializer.validated_data["target_kcal"]
        adherence_tolerance_pct = query_serializer.validated_data["adherence_tolerance_pct"]

        payload = NutritionAnalyticsService.get_advanced_analytics(
            user=request.user,
            start_date=start_date,
            end_date=end_date,
            target_kcal=target_kcal,
            adherence_tolerance_pct=adherence_tolerance_pct,
        )
        return Response(payload, status=status.HTTP_200_OK)
