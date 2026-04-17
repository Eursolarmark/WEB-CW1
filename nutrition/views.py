from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from nutrition.cache_utils import (
    ANALYTICS_CACHE_TIMEOUT_SECONDS,
    FOOD_LIST_CACHE_TIMEOUT_SECONDS,
    build_analytics_cache_key,
    build_food_list_cache_key,
    bump_analytics_cache_version,
)
from nutrition.models import FoodItem, MealLog
from nutrition.pagination import StandardResultsSetPagination
from nutrition.serializers import (
    AdvancedAnalyticsQuerySerializer,
    AdvancedAnalyticsResponseSerializer,
    CustomTokenObtainPairSerializer,
    CurrentUserSerializer,
    DailySummaryResponseSerializer,
    DailySummaryQuerySerializer,
    FoodItemListQuerySerializer,
    FoodItemSerializer,
    LogoutSerializer,
    MealLogListQuerySerializer,
    MealLogSerializer,
    RegisterSerializer,
    TrendsResponseSerializer,
    TrendsQuerySerializer,
)
from nutrition.services import NutritionAnalyticsService
from nutrition.throttles import (
    AnalyticsRateThrottle,
    BurstUserRateThrottle,
    FoodLookupRateThrottle,
    MealWriteRateThrottle,
)


def _query_params_to_cache_dict(query_params) -> dict:
    normalized = {}
    for key, values in query_params.lists():
        normalized[key] = values[0] if len(values) == 1 else values
    return normalized


class RegisterAPIView(generics.CreateAPIView):
    """
    /api/auth/register/
    - POST: Create a user account
    """

    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]


class CustomTokenObtainPairAPIView(TokenObtainPairView):
    """JWT login endpoint supporting username or email identifier."""

    serializer_class = CustomTokenObtainPairSerializer
    permission_classes = [AllowAny]


class CurrentUserAPIView(APIView):
    """Return profile of currently authenticated user."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: CurrentUserSerializer})
    def get(self, request, *args, **kwargs):
        serializer = CurrentUserSerializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)


class LogoutAPIView(APIView):
    """Blacklist refresh token to terminate session."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=LogoutSerializer, responses={205: None})
    def post(self, request, *args, **kwargs):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(status=status.HTTP_205_RESET_CONTENT)


@extend_schema_view(
    get=extend_schema(parameters=[MealLogListQuerySerializer]),
)
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

    def get_throttles(self):
        if self.request.method.upper() == "POST":
            return [BurstUserRateThrottle(), MealWriteRateThrottle()]
        return super().get_throttles()

    def get_queryset(self):
        queryset = super().get_queryset().filter(user=self.request.user)
        query_serializer = MealLogListQuerySerializer(data=self.request.query_params)
        query_serializer.is_valid(raise_exception=True)
        params = query_serializer.validated_data

        start_date = params.get("start_date")
        end_date = params.get("end_date")
        meal_type = params.get("meal_type")
        meal_types_list = params.get("meal_types_list")

        if start_date:
            queryset = queryset.filter(intake_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(intake_date__lte=end_date)
        if meal_type:
            queryset = queryset.filter(meal_type=meal_type)
        if meal_types_list:
            queryset = queryset.filter(meal_type__in=meal_types_list)

        field_map = {
            "kcal_min": "actual_kcal__gte",
            "kcal_max": "actual_kcal__lte",
            "protein_min": "actual_protein__gte",
            "protein_max": "actual_protein__lte",
            "carbs_min": "actual_carbs__gte",
            "carbs_max": "actual_carbs__lte",
            "fat_min": "actual_fat__gte",
            "fat_max": "actual_fat__lte",
        }
        for param_key, orm_filter in field_map.items():
            param_value = params.get(param_key)
            if param_value is not None:
                queryset = queryset.filter(**{orm_filter: param_value})

        queryset = queryset.order_by(params.get("ordering", "-intake_date"), "-created_at")
        return queryset

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
        bump_analytics_cache_version(self.request.user.id)


@extend_schema_view(
    get=extend_schema(parameters=[FoodItemListQuerySerializer]),
)
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
    throttle_classes = [BurstUserRateThrottle, FoodLookupRateThrottle]

    def get_queryset(self):
        queryset = super().get_queryset()
        query_serializer = FoodItemListQuerySerializer(data=self.request.query_params)
        query_serializer.is_valid(raise_exception=True)
        params = query_serializer.validated_data
        q = params.get("q")
        diet_type = params.get("diet_type")

        if q:
            queryset = queryset.filter(name__icontains=q.strip())
        if diet_type:
            queryset = queryset.filter(diet_type=diet_type.strip())
        if params.get("kcal_min") is not None:
            queryset = queryset.filter(per_100g_kcal__gte=params["kcal_min"])
        if params.get("kcal_max") is not None:
            queryset = queryset.filter(per_100g_kcal__lte=params["kcal_max"])
        if params.get("protein_min") is not None:
            queryset = queryset.filter(per_100g_protein__gte=params["protein_min"])
        if params.get("protein_max") is not None:
            queryset = queryset.filter(per_100g_protein__lte=params["protein_max"])
        if params.get("carbs_min") is not None:
            queryset = queryset.filter(per_100g_carbs__gte=params["carbs_min"])
        if params.get("carbs_max") is not None:
            queryset = queryset.filter(per_100g_carbs__lte=params["carbs_max"])
        if params.get("fat_min") is not None:
            queryset = queryset.filter(per_100g_fat__gte=params["fat_min"])
        if params.get("fat_max") is not None:
            queryset = queryset.filter(per_100g_fat__lte=params["fat_max"])
        queryset = queryset.order_by(params.get("ordering", "name"))
        return queryset

    def list(self, request, *args, **kwargs):
        cache_key = build_food_list_cache_key(
            user_id=request.user.id,
            params=_query_params_to_cache_dict(request.query_params),
        )
        cached_payload = cache.get(cache_key)
        if cached_payload is not None:
            response = Response(cached_payload, status=status.HTTP_200_OK)
            response["X-Cache"] = "HIT"
            return response

        response = super().list(request, *args, **kwargs)
        cache.set(cache_key, response.data, timeout=FOOD_LIST_CACHE_TIMEOUT_SECONDS)
        response["X-Cache"] = "MISS"
        return response


class MealLogDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    """
    /api/logs/{id}/
    - PUT/PATCH: Update meal log
    - DELETE: Remove meal log
    """

    serializer_class = MealLogSerializer
    queryset = MealLog.objects.select_related("food_item").all()
    permission_classes = [IsAuthenticated]

    def get_throttles(self):
        if self.request.method.upper() in {"PUT", "PATCH", "DELETE"}:
            return [BurstUserRateThrottle(), MealWriteRateThrottle()]
        return super().get_throttles()

    def get_queryset(self):
        return super().get_queryset().filter(user=self.request.user)

    def perform_update(self, serializer):
        serializer.save()
        bump_analytics_cache_version(self.request.user.id)

    def perform_destroy(self, instance):
        instance.delete()
        bump_analytics_cache_version(self.request.user.id)


class DailySummaryAPIView(APIView):
    """
    /api/logs/daily-summary/?date=YYYY-MM-DD
    Return total kcal/protein/carbs/fat for the given date.
    """

    permission_classes = [IsAuthenticated]
    throttle_classes = [BurstUserRateThrottle, AnalyticsRateThrottle]

    @extend_schema(
        parameters=[DailySummaryQuerySerializer],
        responses={200: DailySummaryResponseSerializer},
    )
    def get(self, request, *args, **kwargs):
        query_serializer = DailySummaryQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        query_params = query_serializer.validated_data
        cache_key = build_analytics_cache_key(
            endpoint="daily_summary",
            user_id=request.user.id,
            params=query_params,
        )
        cached_payload = cache.get(cache_key)
        if cached_payload is not None:
            response = Response(cached_payload, status=status.HTTP_200_OK)
            response["X-Cache"] = "HIT"
            return response

        payload = NutritionAnalyticsService.get_daily_summary(
            user=request.user,
            target_date=query_params["date"],
        )
        cache.set(cache_key, payload, timeout=ANALYTICS_CACHE_TIMEOUT_SECONDS)
        response = Response(payload, status=status.HTTP_200_OK)
        response["X-Cache"] = "MISS"
        return response


class NutritionTrendsAPIView(APIView):
    """
    /api/analytics/trends/
    Optional query params:
      - end_date=YYYY-MM-DD (default: today)
      - days=7 (default: 7, allowed 1-31)
      - target_kcal=2000 (default: 2000)
    """

    permission_classes = [IsAuthenticated]
    throttle_classes = [BurstUserRateThrottle, AnalyticsRateThrottle]

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
        cache_key = build_analytics_cache_key(
            endpoint="trends",
            user_id=request.user.id,
            params={
                "end_date": end_date,
                "days": days,
                "target_kcal": target_kcal,
            },
        )
        cached_payload = cache.get(cache_key)
        if cached_payload is not None:
            response = Response(cached_payload, status=status.HTTP_200_OK)
            response["X-Cache"] = "HIT"
            return response

        payload = NutritionAnalyticsService.get_7day_trends(
            user=request.user,
            end_date=end_date,
            days=days,
            target_kcal=target_kcal,
        )
        cache.set(cache_key, payload, timeout=ANALYTICS_CACHE_TIMEOUT_SECONDS)
        response = Response(payload, status=status.HTTP_200_OK)
        response["X-Cache"] = "MISS"
        return response


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
    throttle_classes = [BurstUserRateThrottle, AnalyticsRateThrottle]

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
        cache_key = build_analytics_cache_key(
            endpoint="advanced",
            user_id=request.user.id,
            params={
                "start_date": start_date,
                "end_date": end_date,
                "target_kcal": target_kcal,
                "adherence_tolerance_pct": adherence_tolerance_pct,
            },
        )
        cached_payload = cache.get(cache_key)
        if cached_payload is not None:
            response = Response(cached_payload, status=status.HTTP_200_OK)
            response["X-Cache"] = "HIT"
            return response

        payload = NutritionAnalyticsService.get_advanced_analytics(
            user=request.user,
            start_date=start_date,
            end_date=end_date,
            target_kcal=target_kcal,
            adherence_tolerance_pct=adherence_tolerance_pct,
        )
        cache.set(cache_key, payload, timeout=ANALYTICS_CACHE_TIMEOUT_SECONDS)
        response = Response(payload, status=status.HTTP_200_OK)
        response["X-Cache"] = "MISS"
        return response
