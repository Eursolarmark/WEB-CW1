from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, Max
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
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
from nutrition.models import CustomFoodItem, FoodFavorite, FoodItem, MealLog, Recipe, UserNutritionTarget
from nutrition.pagination import StandardResultsSetPagination
from nutrition.serializers import (
    AdvancedAnalyticsQuerySerializer,
    AdvancedAnalyticsResponseSerializer,
    ChangePasswordSerializer,
    CustomFoodItemSerializer,
    CustomTokenObtainPairSerializer,
    CurrentSessionsResponseSerializer,
    CurrentUserSerializer,
    DailySummaryResponseSerializer,
    DailySummaryQuerySerializer,
    DeleteAccountSerializer,
    FoodFavoriteCreateSerializer,
    FoodFavoriteSerializer,
    FoodItemListQuerySerializer,
    FoodItemSerializer,
    LogoutSerializer,
    MealLogBulkCreateSerializer,
    MealLogBulkCreateResponseSerializer,
    MealLogListQuerySerializer,
    MealLogBulkCreateItemSerializer,
    MealLogSerializer,
    RecentFoodSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    QuickMealLogSerializer,
    RevokeAllSessionsResponseSerializer,
    RegisterSerializer,
    RecipeSerializer,
    UserDataExportResponseSerializer,
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


class LogoutAPIView(APIView):
    """Blacklist refresh token to terminate session."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [AuthRateThrottle]

    @extend_schema(request=LogoutSerializer, responses={205: None})
    def post(self, request, *args, **kwargs):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(status=status.HTTP_205_RESET_CONTENT)


class ChangePasswordAPIView(APIView):
    """Allow authenticated users to change password."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [AuthRateThrottle]

    @extend_schema(request=ChangePasswordSerializer, responses={200: None})
    def post(self, request, *args, **kwargs):
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if not request.user.check_password(serializer.validated_data["old_password"]):
            return Response(
                {"old_password": ["Old password is incorrect."]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        request.user.set_password(serializer.validated_data["new_password"])
        request.user.save(update_fields=["password"])
        update_session_auth_hash(request, request.user)
        return Response(status=status.HTTP_200_OK)


class PasswordResetRequestAPIView(APIView):
    """Issue password reset token payload (development/coursework-friendly)."""

    permission_classes = [AllowAny]
    throttle_classes = [AuthRateThrottle]

    @extend_schema(request=PasswordResetRequestSerializer, responses={200: None})
    def post(self, request, *args, **kwargs):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"]
        user = User.objects.filter(email__iexact=email).first()
        response = {"message": "If the email exists, reset instructions are prepared."}
        if user and settings.DEBUG:
            token_generator = PasswordResetTokenGenerator()
            response["uid"] = urlsafe_base64_encode(force_bytes(user.pk))
            response["token"] = token_generator.make_token(user)
        return Response(response, status=status.HTTP_200_OK)


class PasswordResetConfirmAPIView(APIView):
    """Confirm password reset using uid/token pair."""

    permission_classes = [AllowAny]
    throttle_classes = [AuthRateThrottle]

    @extend_schema(request=PasswordResetConfirmSerializer, responses={200: None})
    def post(self, request, *args, **kwargs):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        uid = serializer.validated_data["uid"]
        token = serializer.validated_data["token"]
        try:
            user_id = force_str(urlsafe_base64_decode(uid))
            user = User.objects.get(pk=user_id)
        except Exception:
            return Response({"uid": ["Invalid uid."]}, status=status.HTTP_400_BAD_REQUEST)

        token_generator = PasswordResetTokenGenerator()
        if not token_generator.check_token(user, token):
            return Response({"token": ["Invalid or expired token."]}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(serializer.validated_data["new_password"])
        user.save(update_fields=["password"])
        return Response(status=status.HTTP_200_OK)


class CurrentSessionsAPIView(APIView):
    """List active refresh-token sessions for current user."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: CurrentSessionsResponseSerializer})
    def get(self, request, *args, **kwargs):
        from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

        blacklisted_ids = set(
            BlacklistedToken.objects.filter(token__user=request.user).values_list("token_id", flat=True)
        )
        sessions = []
        for token in OutstandingToken.objects.filter(user=request.user).order_by("-created_at"):
            if token.id in blacklisted_ids:
                continue
            sessions.append(
                {
                    "jti": token.jti,
                    "created_at": token.created_at,
                    "expires_at": token.expires_at,
                }
            )
        return Response({"sessions": sessions}, status=status.HTTP_200_OK)


class RevokeAllSessionsAPIView(APIView):
    """Blacklist all active refresh tokens for current user."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: RevokeAllSessionsResponseSerializer})
    def post(self, request, *args, **kwargs):
        from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

        outstanding_tokens = OutstandingToken.objects.filter(user=request.user)
        revoked = 0
        for token in outstanding_tokens:
            _, created = BlacklistedToken.objects.get_or_create(token=token)
            if created:
                revoked += 1
        return Response({"revoked_sessions": revoked}, status=status.HTTP_200_OK)


class DeleteAccountAPIView(APIView):
    """Delete authenticated user account."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=DeleteAccountSerializer, responses={204: None})
    def delete(self, request, *args, **kwargs):
        serializer = DeleteAccountSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if not request.user.check_password(serializer.validated_data["password"]):
            return Response({"password": ["Password is incorrect."]}, status=status.HTTP_400_BAD_REQUEST)
        request.user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class UserDataExportAPIView(APIView):
    """Export current user's key account and tracking data."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: UserDataExportResponseSerializer})
    def get(self, request, *args, **kwargs):
        logs = MealLog.objects.filter(user=request.user).select_related("food_item", "custom_food")
        export_payload = {
            "user": CurrentUserSerializer(request.user).data,
            "nutrition_target": UserNutritionTargetSerializer(
                getattr(request.user, "nutrition_target", UserNutritionTarget(user=request.user))
            ).data,
            "favorites": FoodFavoriteSerializer(
                FoodFavorite.objects.filter(user=request.user).select_related("food_item"),
                many=True,
            ).data,
            "custom_food_items": CustomFoodItemSerializer(
                CustomFoodItem.objects.filter(user=request.user),
                many=True,
            ).data,
            "meal_logs": MealLogSerializer(logs, many=True).data,
        }
        return Response(export_payload, status=status.HTTP_200_OK)


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


class CustomFoodItemListCreateAPIView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CustomFoodItemSerializer

    def get_queryset(self):
        return CustomFoodItem.objects.filter(user=self.request.user).order_by("name")

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def create(self, request, *args, **kwargs):
        replay_response = _get_idempotency_response(request)
        if replay_response is not None:
            return replay_response
        response = super().create(request, *args, **kwargs)
        _store_idempotency_response(request, response)
        return response


class CustomFoodItemDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CustomFoodItemSerializer

    def get_queryset(self):
        return CustomFoodItem.objects.filter(user=self.request.user)


class RecipeListCreateAPIView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = RecipeSerializer

    def get_queryset(self):
        return Recipe.objects.filter(user=self.request.user).prefetch_related("items__food_item", "items__custom_food")

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def create(self, request, *args, **kwargs):
        replay_response = _get_idempotency_response(request)
        if replay_response is not None:
            return replay_response
        response = super().create(request, *args, **kwargs)
        _store_idempotency_response(request, response)
        return response


class RecipeDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = RecipeSerializer

    def get_queryset(self):
        return Recipe.objects.filter(user=self.request.user).prefetch_related("items__food_item", "items__custom_food")


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
        custom_food = None
        if not food:
            custom_food = CustomFoodItem.objects.filter(user=request.user, name__iexact=name_query).first()

        if not food and not custom_food:
            matches = list(
                FoodItem.objects.filter(name__icontains=name_query).values_list("name", flat=True)[:5]
            )
            custom_matches = list(
                CustomFoodItem.objects.filter(user=request.user, name__icontains=name_query).values_list(
                    "name", flat=True
                )[:5]
            )
            candidates = matches + [f"[Custom] {name}" for name in custom_matches]
            return Response(
                {
                    "food_name": ["No exact food match found."],
                    "candidates": candidates,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        payload = {
            "intake_date": validated["intake_date"],
            "meal_type": validated["meal_type"],
            "food_item": food.id if food else None,
            "custom_food": custom_food.id if custom_food else None,
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
                custom_food = item.get("custom_food")
                if custom_food and custom_food.user_id != request.user.id:
                    return Response(
                        {"custom_food": ["custom_food does not belong to current user."]},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                payload = {
                    "intake_date": item["intake_date"],
                    "meal_type": item["meal_type"],
                    "food_item": item.get("food_item").id if item.get("food_item") else None,
                    "custom_food": custom_food.id if custom_food else None,
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
    queryset = MealLog.objects.select_related("food_item", "custom_food").all()
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


class MealLogDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    """
    /api/logs/{id}/
    - PUT/PATCH: Update meal log
    - DELETE: Remove meal log
    """

    serializer_class = MealLogSerializer
    queryset = MealLog.objects.select_related("food_item", "custom_food").all()
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
