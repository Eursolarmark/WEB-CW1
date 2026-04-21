from datetime import timedelta
from difflib import SequenceMatcher
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, Max
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
from nutrition.models import FoodFavorite, FoodItem, MealLog, UserNutritionTarget
from nutrition.pagination import StandardResultsSetPagination
from nutrition.serializers import (
    AdvancedAnalyticsQuerySerializer,
    AdvancedAnalyticsResponseSerializer,
    CustomTokenObtainPairSerializer,
    CurrentUserSerializer,
    DailySummaryResponseSerializer,
    DailySummaryQuerySerializer,
    FoodFavoriteCreateSerializer,
    FoodFavoriteSerializer,
    FoodFuzzySearchQuerySerializer,
    FoodFuzzySearchResponseSerializer,
    FoodItemListQuerySerializer,
    FoodItemSerializer,
    MealLogBulkCreateSerializer,
    MealLogBulkCreateResponseSerializer,
    MealLogListQuerySerializer,
    MealLogSerializer,
    RecentFoodSerializer,
    QuickMealLogSerializer,
    RegisterSerializer,
    UserNutritionTargetSerializer,
    TrendsResponseSerializer,
    TrendsQuerySerializer,
)
from nutrition.services import NutritionAnalyticsService
from nutrition.throttles import (
    AnalyticsRateThrottle,
    AuthRateThrottle,
    BurstUserRateThrottle,
    FoodLookupRateThrottle,
    MealWriteRateThrottle,
)

User = get_user_model()

IDEMPOTENCY_CACHE_TTL_SECONDS = 60 * 60


def _query_params_to_cache_dict(query_params) -> dict:
    normalized = {}
    for key, values in query_params.lists():
        normalized[key] = values[0] if len(values) == 1 else values
    return normalized


def _default_target_kcal_for_user(user) -> Decimal:
    target = getattr(user, "nutrition_target", None)
    return target.target_kcal if target else Decimal("2000")


def _food_name_similarity_score(query: str, candidate_name: str) -> float:
    q = query.strip().lower()
    name = candidate_name.strip().lower()
    if not q or not name:
        return 0.0

    base = SequenceMatcher(None, q, name).ratio()
    bonus = 0.0
    if name.startswith(q):
        bonus += 0.30
    if q in name:
        bonus += 0.20
    query_tokens = [token for token in q.split() if token]
    name_tokens = [token for token in name.replace(",", " ").split() if token]
    if query_tokens and any(token in name for token in query_tokens):
        bonus += 0.10
    if query_tokens and name_tokens:
        token_overlap = len(set(query_tokens) & set(name_tokens)) / max(len(set(query_tokens)), 1)
        bonus += 0.20 * token_overlap
    return base + bonus


def _idempotency_cache_key(request) -> str | None:
    idempotency_key = request.headers.get("Idempotency-Key")
    if not idempotency_key:
        return None
    user_id = getattr(request.user, "id", "anon")
    return f"idempotency:{user_id}:{request.method}:{request.path}:{idempotency_key}"


def _get_idempotency_response(request):
    cache_key = _idempotency_cache_key(request)
    if not cache_key:
        return None
    cached = cache.get(cache_key)
    if cached is None:
        return None
    response = Response(cached["data"], status=cached["status"])
    response["X-Idempotent-Replay"] = "true"
    return response


def _store_idempotency_response(request, response):
    cache_key = _idempotency_cache_key(request)
    if not cache_key:
        return
    if response.status_code >= 500:
        return
    cache.set(
        cache_key,
        {"status": response.status_code, "data": response.data},
        timeout=IDEMPOTENCY_CACHE_TTL_SECONDS,
    )


class RegisterAPIView(generics.CreateAPIView):
    """
    /api/auth/register/
    - POST: Create a user account
    """

    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    throttle_classes = [AuthRateThrottle]


class CustomTokenObtainPairAPIView(TokenObtainPairView):
    """JWT login endpoint supporting username or email identifier."""

    serializer_class = CustomTokenObtainPairSerializer
    permission_classes = [AllowAny]
    throttle_classes = [AuthRateThrottle]


class CurrentUserAPIView(APIView):
    """Return profile of currently authenticated user."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: CurrentUserSerializer})
    def get(self, request, *args, **kwargs):
        serializer = CurrentUserSerializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)


class UserNutritionTargetAPIView(APIView):
    """Get or update user nutrition targets."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: UserNutritionTargetSerializer})
    def get(self, request, *args, **kwargs):
        target, _ = UserNutritionTarget.objects.get_or_create(user=request.user)
        serializer = UserNutritionTargetSerializer(target)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(request=UserNutritionTargetSerializer, responses={200: UserNutritionTargetSerializer})
    def put(self, request, *args, **kwargs):
        target, _ = UserNutritionTarget.objects.get_or_create(user=request.user)
        serializer = UserNutritionTargetSerializer(target, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)


class FoodRecentAPIView(APIView):
    """Return user's recently consumed foods."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: RecentFoodSerializer(many=True)})
    def get(self, request, *args, **kwargs):
        limit = min(max(int(request.query_params.get("limit", 20)), 1), 100)
        recent_rows = (
            MealLog.objects.filter(user=request.user, food_item__isnull=False)
            .values("food_item_id", "food_item__name")
            .annotate(last_used_at=Max("created_at"), use_count=Count("id"))
            .order_by("-last_used_at")[:limit]
        )
        payload = [
            {
                "food_item": row["food_item_id"],
                "food_item_name": row["food_item__name"],
                "last_used_at": row["last_used_at"],
                "use_count": row["use_count"],
            }
            for row in recent_rows
        ]
        return Response(payload, status=status.HTTP_200_OK)


class FoodFavoriteListCreateAPIView(APIView):
    """List and create user favorites."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: FoodFavoriteSerializer(many=True)})
    def get(self, request, *args, **kwargs):
        queryset = FoodFavorite.objects.filter(user=request.user).select_related("food_item")
        serializer = FoodFavoriteSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(request=FoodFavoriteCreateSerializer, responses={201: FoodFavoriteSerializer})
    def post(self, request, *args, **kwargs):
        replay_response = _get_idempotency_response(request)
        if replay_response is not None:
            return replay_response

        serializer = FoodFavoriteCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        favorite, _ = FoodFavorite.objects.get_or_create(
            user=request.user,
            food_item=serializer.validated_data["food_item"],
        )
        output = FoodFavoriteSerializer(favorite).data
        response = Response(output, status=status.HTTP_201_CREATED)
        _store_idempotency_response(request, response)
        return response


class FoodFavoriteDeleteAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={204: None})
    def delete(self, request, food_item_id: int, *args, **kwargs):
        deleted, _ = FoodFavorite.objects.filter(user=request.user, food_item_id=food_item_id).delete()
        if deleted == 0:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MealLogQuickCreateAPIView(APIView):
    """Quick-create a meal log by food name."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [BurstUserRateThrottle, MealWriteRateThrottle]

    @extend_schema(request=QuickMealLogSerializer, responses={201: MealLogSerializer})
    def post(self, request, *args, **kwargs):
        replay_response = _get_idempotency_response(request)
        if replay_response is not None:
            return replay_response

        serializer = QuickMealLogSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data
        name_query = validated["food_name"].strip()

        food = FoodItem.objects.filter(name__iexact=name_query).first()
        if not food:
            matches = list(
                FoodItem.objects.filter(name__icontains=name_query).values_list("name", flat=True)[:5]
            )
            return Response(
                {
                    "food_name": ["No exact food match found."],
                    "candidates": matches,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        payload = {
            "intake_date": validated["intake_date"],
            "meal_type": validated["meal_type"],
            "food_item": food.id,
            "intake_weight_grams": validated.get("intake_weight_grams"),
            "unit": validated.get("unit"),
            "unit_quantity": validated.get("unit_quantity"),
        }
        payload = {key: value for key, value in payload.items() if value is not None}
        log_serializer = MealLogSerializer(data=payload)
        log_serializer.is_valid(raise_exception=True)
        meal_log = log_serializer.save(user=request.user)
        bump_analytics_cache_version(request.user.id)
        response = Response(MealLogSerializer(meal_log).data, status=status.HTTP_201_CREATED)
        _store_idempotency_response(request, response)
        return response


class MealLogBulkCreateAPIView(APIView):
    """Create multiple meal logs in one request."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [BurstUserRateThrottle, MealWriteRateThrottle]

    @extend_schema(request=MealLogBulkCreateSerializer, responses={201: MealLogBulkCreateResponseSerializer})
    def post(self, request, *args, **kwargs):
        replay_response = _get_idempotency_response(request)
        if replay_response is not None:
            return replay_response

        serializer = MealLogBulkCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        items = serializer.validated_data["items"]

        created_logs = []
        with transaction.atomic():
            for item in items:
                payload = {
                    "intake_date": item["intake_date"],
                    "meal_type": item["meal_type"],
                    "food_item": item["food_item"].id,
                    "intake_weight_grams": item.get("intake_weight_grams"),
                    "unit": item.get("unit"),
                    "unit_quantity": item.get("unit_quantity"),
                }
                payload = {key: value for key, value in payload.items() if value is not None}
                meal_serializer = MealLogSerializer(data=payload)
                meal_serializer.is_valid(raise_exception=True)
                created_logs.append(meal_serializer.save(user=request.user))

        bump_analytics_cache_version(request.user.id)
        output = MealLogSerializer(created_logs, many=True).data
        response = Response({"created": len(output), "results": output}, status=status.HTTP_201_CREATED)
        _store_idempotency_response(request, response)
        return response


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

    def create(self, request, *args, **kwargs):
        replay_response = _get_idempotency_response(request)
        if replay_response is not None:
            return replay_response
        response = super().create(request, *args, **kwargs)
        _store_idempotency_response(request, response)
        return response


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


class FoodItemFuzzySearchAPIView(APIView):
    """Fuzzy food search by approximate name."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [BurstUserRateThrottle, FoodLookupRateThrottle]

    @extend_schema(
        parameters=[FoodFuzzySearchQuerySerializer],
        responses={200: FoodFuzzySearchResponseSerializer},
    )
    def get(self, request, *args, **kwargs):
        query_serializer = FoodFuzzySearchQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        params = query_serializer.validated_data

        query = params["q"].strip()
        limit = params["limit"]
        tokens = [token for token in query.split() if token]

        search_params = {"mode": "fuzzy_search", "q": query, "limit": limit}
        cache_key = build_food_list_cache_key(user_id=request.user.id, params=search_params)
        cached_payload = cache.get(cache_key)
        if cached_payload is not None:
            response = Response(cached_payload, status=status.HTTP_200_OK)
            response["X-Cache"] = "HIT"
            return response

        base_qs = FoodItem.objects.all()
        prefix_qs = base_qs.filter(name__istartswith=query)
        contains_qs = base_qs.filter(name__icontains=query)
        token_qs = base_qs.none()
        for token in tokens:
            token_qs = token_qs | base_qs.filter(name__icontains=token)

        candidate_qs = (prefix_qs | contains_qs | token_qs).distinct()
        candidates = list(candidate_qs[:500])

        scored = [
            (item, _food_name_similarity_score(query, item.name))
            for item in candidates
        ]

        # For typo-heavy input (e.g. "chikn brest"), fall back to a global fuzzy
        # pass, but only keep items above threshold to avoid unrelated results.
        if not scored:
            global_candidates = list(base_qs[:2000])
            global_scored = [
                (item, _food_name_similarity_score(query, item.name))
                for item in global_candidates
            ]
            scored = [pair for pair in global_scored if pair[1] >= 0.45]

        if not scored:
            payload = {"message": "No close matches found.", "results": []}
            cache.set(cache_key, payload, timeout=FOOD_LIST_CACHE_TIMEOUT_SECONDS)
            response = Response(payload, status=status.HTTP_200_OK)
            response["X-Cache"] = "MISS"
            return response

        ranked = sorted(
            scored,
            key=lambda pair: (
                -pair[1],
                len(pair[0].name),
                pair[0].name.lower(),
            ),
        )

        top_results = [item for item, _score in ranked[:limit]]
        payload = {
            "message": f"Found {len(top_results)} close matches.",
            "results": FoodItemSerializer(top_results, many=True).data,
        }
        cache.set(cache_key, payload, timeout=FOOD_LIST_CACHE_TIMEOUT_SECONDS)
        response = Response(payload, status=status.HTTP_200_OK)
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
        target_kcal = query_serializer.validated_data.get("target_kcal", _default_target_kcal_for_user(request.user))
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
        target_kcal = query_serializer.validated_data.get("target_kcal", _default_target_kcal_for_user(request.user))
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
