from decimal import Decimal

from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db.models import Q
from rest_framework import serializers
from rest_framework_simplejwt.exceptions import AuthenticationFailed, TokenError
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.settings import api_settings as jwt_api_settings
from rest_framework_simplejwt.tokens import RefreshToken

from nutrition.models import FoodItem, MealLog
from nutrition.models import (
    CustomFoodItem,
    FoodFavorite,
    Recipe,
    RecipeItem,
    UserNutritionTarget,
)

User = get_user_model()


class MealLogSerializer(serializers.ModelSerializer):
    """Serializer for creating/updating and reading meal logs."""

    UNIT_TO_GRAMS = {
        "g": Decimal("1"),
        "gram": Decimal("1"),
        "grams": Decimal("1"),
        "piece": Decimal("50"),
        "cup": Decimal("240"),
        "tbsp": Decimal("15"),
    }

    user = serializers.IntegerField(source="user_id", read_only=True)
    food_item_name = serializers.CharField(source="food_item.name", read_only=True)
    custom_food_name = serializers.CharField(source="custom_food.name", read_only=True)
    intake_weight_grams = serializers.DecimalField(
        required=False,
        max_digits=7,
        decimal_places=2,
        min_value=Decimal("0.01"),
    )
    unit = serializers.ChoiceField(
        required=False,
        write_only=True,
        choices=sorted(UNIT_TO_GRAMS.keys()),
    )
    unit_quantity = serializers.DecimalField(
        required=False,
        write_only=True,
        max_digits=8,
        decimal_places=2,
        min_value=Decimal("0.01"),
    )

    class Meta:
        model = MealLog
        fields = [
            "id",
            "user",
            "intake_date",
            "meal_type",
            "food_item",
            "food_item_name",
            "custom_food",
            "custom_food_name",
            "intake_weight_grams",
            "unit",
            "unit_quantity",
            "actual_kcal",
            "actual_protein",
            "actual_carbs",
            "actual_fat",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "food_item_name",
            "custom_food_name",
            "actual_kcal",
            "actual_protein",
            "actual_carbs",
            "actual_fat",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        attrs = super().validate(attrs)
        food_item = attrs.get("food_item", getattr(self.instance, "food_item", None))
        custom_food = attrs.get("custom_food", getattr(self.instance, "custom_food", None))

        if food_item and custom_food:
            raise serializers.ValidationError(
                {"food_item": "Provide either food_item or custom_food, not both."}
            )
        if not food_item and not custom_food:
            raise serializers.ValidationError(
                {"food_item": "Either food_item or custom_food is required."}
            )

        intake_weight_grams = attrs.get("intake_weight_grams")
        unit = attrs.pop("unit", None)
        unit_quantity = attrs.pop("unit_quantity", None)

        if self.instance is None and intake_weight_grams is None and unit is None:
            raise serializers.ValidationError(
                {"intake_weight_grams": "Provide intake_weight_grams, or use unit + unit_quantity."}
            )
        if unit and unit_quantity is None:
            raise serializers.ValidationError({"unit_quantity": "unit_quantity is required with unit."})

        if intake_weight_grams is None and unit and unit_quantity is not None:
            attrs["intake_weight_grams"] = (
                Decimal(unit_quantity) * self.UNIT_TO_GRAMS[unit]
            ).quantize(Decimal("0.01"))

        return attrs


class MealLogListQuerySerializer(serializers.Serializer):
    """Query serializer for listing meal logs."""

    date = serializers.DateField(required=False)
    start_date = serializers.DateField(required=False)
    end_date = serializers.DateField(required=False)
    meal_type = serializers.ChoiceField(
        required=False,
        choices=[choice for choice, _ in MealLog.MealType.choices],
    )
    meal_types = serializers.CharField(required=False, allow_blank=False, max_length=128)
    kcal_min = serializers.DecimalField(required=False, min_value=Decimal("0"), max_digits=10, decimal_places=2)
    kcal_max = serializers.DecimalField(required=False, min_value=Decimal("0"), max_digits=10, decimal_places=2)
    protein_min = serializers.DecimalField(
        required=False, min_value=Decimal("0"), max_digits=10, decimal_places=2
    )
    protein_max = serializers.DecimalField(
        required=False, min_value=Decimal("0"), max_digits=10, decimal_places=2
    )
    carbs_min = serializers.DecimalField(required=False, min_value=Decimal("0"), max_digits=10, decimal_places=2)
    carbs_max = serializers.DecimalField(required=False, min_value=Decimal("0"), max_digits=10, decimal_places=2)
    fat_min = serializers.DecimalField(required=False, min_value=Decimal("0"), max_digits=10, decimal_places=2)
    fat_max = serializers.DecimalField(required=False, min_value=Decimal("0"), max_digits=10, decimal_places=2)
    ordering = serializers.ChoiceField(
        required=False,
        choices=[
            "intake_date",
            "-intake_date",
            "created_at",
            "-created_at",
            "actual_kcal",
            "-actual_kcal",
            "actual_protein",
            "-actual_protein",
            "actual_carbs",
            "-actual_carbs",
            "actual_fat",
            "-actual_fat",
        ],
        default="-intake_date",
    )

    @staticmethod
    def _validate_min_max(attrs: dict, min_key: str, max_key: str, label: str) -> None:
        min_value = attrs.get(min_key)
        max_value = attrs.get(max_key)
        if min_value is not None and max_value is not None and min_value > max_value:
            raise serializers.ValidationError({min_key: f"{label} min must be <= {label} max."})

    def validate(self, attrs):
        date_value = attrs.get("date")
        start_date = attrs.get("start_date")
        end_date = attrs.get("end_date")

        if date_value:
            if start_date and start_date != date_value:
                raise serializers.ValidationError(
                    {"start_date": "start_date must match date when date is provided."}
                )
            if end_date and end_date != date_value:
                raise serializers.ValidationError(
                    {"end_date": "end_date must match date when date is provided."}
                )
            attrs["start_date"] = date_value
            attrs["end_date"] = date_value

        if attrs.get("start_date") and attrs.get("end_date") and attrs["start_date"] > attrs["end_date"]:
            raise serializers.ValidationError(
                {"start_date": "start_date must be earlier than or equal to end_date."}
            )

        self._validate_min_max(attrs, "kcal_min", "kcal_max", "kcal")
        self._validate_min_max(attrs, "protein_min", "protein_max", "protein")
        self._validate_min_max(attrs, "carbs_min", "carbs_max", "carbs")
        self._validate_min_max(attrs, "fat_min", "fat_max", "fat")

        meal_types_csv = attrs.get("meal_types")
        if meal_types_csv:
            allowed = {choice for choice, _ in MealLog.MealType.choices}
            parsed_types = [item.strip() for item in meal_types_csv.split(",") if item.strip()]
            invalid = [item for item in parsed_types if item not in allowed]
            if invalid:
                raise serializers.ValidationError(
                    {"meal_types": f"Invalid meal_type values: {', '.join(invalid)}"}
                )
            attrs["meal_types_list"] = parsed_types

        return attrs


class FoodItemSerializer(serializers.ModelSerializer):
    """Read-only serializer for food catalog lookup."""

    class Meta:
        model = FoodItem
        fields = [
            "id",
            "name",
            "diet_type",
            "per_100g_kcal",
            "per_100g_protein",
            "per_100g_carbs",
            "per_100g_fat",
            "source",
        ]


class FoodItemListQuerySerializer(serializers.Serializer):
    """Query serializer for listing food items."""

    q = serializers.CharField(required=False, allow_blank=False, max_length=255)
    diet_type = serializers.ChoiceField(
        required=False,
        choices=[choice for choice, _ in FoodItem.DietType.choices],
    )
    kcal_min = serializers.DecimalField(required=False, min_value=Decimal("0"), max_digits=10, decimal_places=2)
    kcal_max = serializers.DecimalField(required=False, min_value=Decimal("0"), max_digits=10, decimal_places=2)
    protein_min = serializers.DecimalField(
        required=False, min_value=Decimal("0"), max_digits=10, decimal_places=2
    )
    protein_max = serializers.DecimalField(
        required=False, min_value=Decimal("0"), max_digits=10, decimal_places=2
    )
    carbs_min = serializers.DecimalField(required=False, min_value=Decimal("0"), max_digits=10, decimal_places=2)
    carbs_max = serializers.DecimalField(required=False, min_value=Decimal("0"), max_digits=10, decimal_places=2)
    fat_min = serializers.DecimalField(required=False, min_value=Decimal("0"), max_digits=10, decimal_places=2)
    fat_max = serializers.DecimalField(required=False, min_value=Decimal("0"), max_digits=10, decimal_places=2)
    ordering = serializers.ChoiceField(
        required=False,
        choices=[
            "name",
            "-name",
            "per_100g_kcal",
            "-per_100g_kcal",
            "per_100g_protein",
            "-per_100g_protein",
            "per_100g_carbs",
            "-per_100g_carbs",
            "per_100g_fat",
            "-per_100g_fat",
        ],
        default="name",
    )

    @staticmethod
    def _validate_min_max(attrs: dict, min_key: str, max_key: str, label: str) -> None:
        min_value = attrs.get(min_key)
        max_value = attrs.get(max_key)
        if min_value is not None and max_value is not None and min_value > max_value:
            raise serializers.ValidationError({min_key: f"{label} min must be <= {label} max."})

    def validate(self, attrs):
        self._validate_min_max(attrs, "kcal_min", "kcal_max", "kcal")
        self._validate_min_max(attrs, "protein_min", "protein_max", "protein")
        self._validate_min_max(attrs, "carbs_min", "carbs_max", "carbs")
        self._validate_min_max(attrs, "fat_min", "fat_max", "fat")
        return attrs


class RegisterSerializer(serializers.ModelSerializer):
    """Serializer for account creation."""

    email = serializers.EmailField(required=True)
    password = serializers.CharField(write_only=True, min_length=8, validators=[validate_password])
    password_confirm = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = ["id", "username", "email", "password", "password_confirm"]
        read_only_fields = ["id"]

    def validate(self, attrs):
        attrs["email"] = attrs["email"].strip().lower()
        if User.objects.filter(email__iexact=attrs["email"]).exists():
            raise serializers.ValidationError({"email": "This email is already registered."})
        if attrs["password"] != attrs["password_confirm"]:
            raise serializers.ValidationError({"password_confirm": "Passwords do not match."})
        return attrs

    def create(self, validated_data):
        validated_data.pop("password_confirm")
        password = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user


class CurrentUserSerializer(serializers.ModelSerializer):
    """Serializer for /api/auth/me/ endpoint."""

    class Meta:
        model = User
        fields = ["id", "username", "email"]


class LogoutSerializer(serializers.Serializer):
    """Serializer for logout endpoint that blacklists refresh token."""

    refresh = serializers.CharField()

    def validate(self, attrs):
        refresh = attrs.get("refresh")
        try:
            token = RefreshToken(refresh)
            token.blacklist()
        except TokenError as exc:
            raise serializers.ValidationError({"refresh": str(exc)}) from exc
        return attrs


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Support login via username or email in the `username` field.

    This keeps compatibility with SimpleJWT default request shape while
    making login UX friendlier for users.
    """

    default_error_messages = {
        "no_active_account": "No active account found with the given credentials.",
    }

    def _resolve_username(self, identifier: str) -> str:
        username_field = self.username_field
        user = User.objects.filter(**{f"{username_field}__iexact": identifier}).first()
        if user:
            return user.get_username()

        email_user = User.objects.filter(Q(email__iexact=identifier)).order_by("id").first()
        if email_user:
            return email_user.get_username()

        return identifier

    def validate(self, attrs):
        credentials = {
            self.username_field: self._resolve_username(attrs.get(self.username_field, "")),
            "password": attrs.get("password"),
        }
        request = self.context.get("request")
        if request is not None:
            credentials["request"] = request

        self.user = authenticate(**credentials)
        if not jwt_api_settings.USER_AUTHENTICATION_RULE(self.user):
            raise AuthenticationFailed(
                self.error_messages["no_active_account"],
                "no_active_account",
            )

        refresh = self.get_token(self.user)
        data = {
            "refresh": str(refresh),
            "access": str(refresh.access_token),
        }

        if jwt_api_settings.UPDATE_LAST_LOGIN:
            from django.contrib.auth.models import update_last_login

            update_last_login(None, self.user)
        return data


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8, validators=[validate_password])
    new_password_confirm = serializers.CharField(write_only=True, min_length=8)

    def validate(self, attrs):
        if attrs["new_password"] != attrs["new_password_confirm"]:
            raise serializers.ValidationError({"new_password_confirm": "Passwords do not match."})
        return attrs


class DeleteAccountSerializer(serializers.Serializer):
    password = serializers.CharField(write_only=True)


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        return value.strip().lower()


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True, min_length=8, validators=[validate_password])
    new_password_confirm = serializers.CharField(write_only=True, min_length=8)

    def validate(self, attrs):
        if attrs["new_password"] != attrs["new_password_confirm"]:
            raise serializers.ValidationError({"new_password_confirm": "Passwords do not match."})
        return attrs


class UserNutritionTargetSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserNutritionTarget
        fields = [
            "target_kcal",
            "target_protein",
            "target_carbs",
            "target_fat",
            "updated_at",
        ]
        read_only_fields = ["updated_at"]


class FoodFavoriteSerializer(serializers.ModelSerializer):
    food_item_name = serializers.CharField(source="food_item.name", read_only=True)
    food_item = serializers.IntegerField(source="food_item_id")

    class Meta:
        model = FoodFavorite
        fields = ["id", "food_item", "food_item_name", "created_at"]
        read_only_fields = ["id", "food_item_name", "created_at"]


class FoodFavoriteCreateSerializer(serializers.Serializer):
    food_item = serializers.PrimaryKeyRelatedField(queryset=FoodItem.objects.all())


class RecentFoodSerializer(serializers.Serializer):
    food_item = serializers.IntegerField()
    food_item_name = serializers.CharField()
    last_used_at = serializers.DateTimeField()
    use_count = serializers.IntegerField()


class QuickMealLogSerializer(serializers.Serializer):
    food_name = serializers.CharField(max_length=255)
    intake_date = serializers.DateField()
    meal_type = serializers.ChoiceField(choices=[choice for choice, _ in MealLog.MealType.choices])
    intake_weight_grams = serializers.DecimalField(
        required=False,
        max_digits=7,
        decimal_places=2,
        min_value=Decimal("0.01"),
    )
    unit = serializers.ChoiceField(required=False, choices=sorted(MealLogSerializer.UNIT_TO_GRAMS.keys()))
    unit_quantity = serializers.DecimalField(
        required=False,
        max_digits=8,
        decimal_places=2,
        min_value=Decimal("0.01"),
    )

    def validate(self, attrs):
        if attrs.get("intake_weight_grams") is None and attrs.get("unit") is None:
            raise serializers.ValidationError(
                {"intake_weight_grams": "Provide intake_weight_grams, or use unit + unit_quantity."}
            )
        if attrs.get("unit") and attrs.get("unit_quantity") is None:
            raise serializers.ValidationError({"unit_quantity": "unit_quantity is required with unit."})
        return attrs


class MealLogBulkCreateItemSerializer(serializers.Serializer):
    intake_date = serializers.DateField()
    meal_type = serializers.ChoiceField(choices=[choice for choice, _ in MealLog.MealType.choices])
    food_item = serializers.PrimaryKeyRelatedField(required=False, queryset=FoodItem.objects.all())
    custom_food = serializers.PrimaryKeyRelatedField(required=False, queryset=CustomFoodItem.objects.all())
    intake_weight_grams = serializers.DecimalField(
        required=False,
        max_digits=7,
        decimal_places=2,
        min_value=Decimal("0.01"),
    )
    unit = serializers.ChoiceField(required=False, choices=sorted(MealLogSerializer.UNIT_TO_GRAMS.keys()))
    unit_quantity = serializers.DecimalField(
        required=False,
        max_digits=8,
        decimal_places=2,
        min_value=Decimal("0.01"),
    )

    def validate(self, attrs):
        food_item = attrs.get("food_item")
        custom_food = attrs.get("custom_food")
        if food_item and custom_food:
            raise serializers.ValidationError({"food_item": "Provide either food_item or custom_food, not both."})
        if not food_item and not custom_food:
            raise serializers.ValidationError({"food_item": "Either food_item or custom_food is required."})

        if attrs.get("intake_weight_grams") is None and attrs.get("unit") is None:
            raise serializers.ValidationError(
                {"intake_weight_grams": "Provide intake_weight_grams, or use unit + unit_quantity."}
            )
        if attrs.get("unit") and attrs.get("unit_quantity") is None:
            raise serializers.ValidationError({"unit_quantity": "unit_quantity is required with unit."})
        return attrs


class MealLogBulkCreateSerializer(serializers.Serializer):
    items = MealLogBulkCreateItemSerializer(many=True, min_length=1, max_length=100)


class CustomFoodItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomFoodItem
        fields = [
            "id",
            "name",
            "per_100g_kcal",
            "per_100g_protein",
            "per_100g_carbs",
            "per_100g_fat",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class RecipeItemSerializer(serializers.ModelSerializer):
    food_item_name = serializers.CharField(source="food_item.name", read_only=True)
    custom_food_name = serializers.CharField(source="custom_food.name", read_only=True)

    class Meta:
        model = RecipeItem
        fields = [
            "id",
            "food_item",
            "food_item_name",
            "custom_food",
            "custom_food_name",
            "weight_grams",
        ]
        read_only_fields = ["id", "food_item_name", "custom_food_name"]

    def validate(self, attrs):
        food_item = attrs.get("food_item")
        custom_food = attrs.get("custom_food")
        if food_item and custom_food:
            raise serializers.ValidationError({"food_item": "Provide either food_item or custom_food, not both."})
        if not food_item and not custom_food:
            raise serializers.ValidationError({"food_item": "Either food_item or custom_food is required."})
        return attrs


class RecipeSerializer(serializers.ModelSerializer):
    items = RecipeItemSerializer(many=True)
    total_kcal = serializers.SerializerMethodField()
    total_protein = serializers.SerializerMethodField()
    total_carbs = serializers.SerializerMethodField()
    total_fat = serializers.SerializerMethodField()

    class Meta:
        model = Recipe
        fields = [
            "id",
            "name",
            "description",
            "items",
            "total_kcal",
            "total_protein",
            "total_carbs",
            "total_fat",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "total_kcal",
            "total_protein",
            "total_carbs",
            "total_fat",
            "created_at",
            "updated_at",
        ]

    @staticmethod
    def _totals(recipe: Recipe) -> dict:
        total_kcal = Decimal("0")
        total_protein = Decimal("0")
        total_carbs = Decimal("0")
        total_fat = Decimal("0")
        for item in recipe.items.all():
            source = item.food_item if item.food_item_id else item.custom_food
            factor = Decimal(item.weight_grams) / Decimal("100")
            total_kcal += factor * Decimal(source.per_100g_kcal)
            total_protein += factor * Decimal(source.per_100g_protein)
            total_carbs += factor * Decimal(source.per_100g_carbs)
            total_fat += factor * Decimal(source.per_100g_fat)
        return {
            "kcal": total_kcal.quantize(Decimal("0.01")),
            "protein": total_protein.quantize(Decimal("0.01")),
            "carbs": total_carbs.quantize(Decimal("0.01")),
            "fat": total_fat.quantize(Decimal("0.01")),
        }

    def get_total_kcal(self, obj) -> Decimal:
        return self._totals(obj)["kcal"]

    def get_total_protein(self, obj) -> Decimal:
        return self._totals(obj)["protein"]

    def get_total_carbs(self, obj) -> Decimal:
        return self._totals(obj)["carbs"]

    def get_total_fat(self, obj) -> Decimal:
        return self._totals(obj)["fat"]

    def create(self, validated_data):
        items_data = validated_data.pop("items", [])
        recipe = Recipe.objects.create(**validated_data)
        for item_data in items_data:
            RecipeItem.objects.create(recipe=recipe, **item_data)
        return recipe

    def update(self, instance, validated_data):
        items_data = validated_data.pop("items", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        if items_data is not None:
            instance.items.all().delete()
            for item_data in items_data:
                RecipeItem.objects.create(recipe=instance, **item_data)
        return instance


class CurrentSessionsItemSerializer(serializers.Serializer):
    jti = serializers.CharField()
    created_at = serializers.DateTimeField()
    expires_at = serializers.DateTimeField()


class CurrentSessionsResponseSerializer(serializers.Serializer):
    sessions = CurrentSessionsItemSerializer(many=True)


class RevokeAllSessionsResponseSerializer(serializers.Serializer):
    revoked_sessions = serializers.IntegerField()


class MealLogBulkCreateResponseSerializer(serializers.Serializer):
    created = serializers.IntegerField()
    results = MealLogSerializer(many=True)


class UserDataExportResponseSerializer(serializers.Serializer):
    user = CurrentUserSerializer()
    nutrition_target = UserNutritionTargetSerializer()
    favorites = FoodFavoriteSerializer(many=True)
    custom_food_items = CustomFoodItemSerializer(many=True)
    meal_logs = MealLogSerializer(many=True)


class DailySummaryQuerySerializer(serializers.Serializer):
    """Query serializer for /api/logs/daily-summary/ endpoint."""

    date = serializers.DateField(required=True)


class TrendsQuerySerializer(serializers.Serializer):
    """Query serializer for /api/analytics/trends/ endpoint."""

    end_date = serializers.DateField(required=False)
    days = serializers.IntegerField(required=False, default=7, min_value=1, max_value=31)
    target_kcal = serializers.DecimalField(
        required=False,
        min_value=Decimal("0"),
        max_digits=8,
        decimal_places=2,
    )


class AdvancedAnalyticsQuerySerializer(serializers.Serializer):
    """Query serializer for /api/analytics/advanced/ endpoint."""

    start_date = serializers.DateField(required=False)
    end_date = serializers.DateField(required=False)
    target_kcal = serializers.DecimalField(
        required=False,
        min_value=Decimal("0"),
        max_digits=8,
        decimal_places=2,
    )
    adherence_tolerance_pct = serializers.DecimalField(
        required=False,
        default=Decimal("10"),
        min_value=Decimal("0"),
        max_digits=5,
        decimal_places=2,
    )

    def validate(self, attrs):
        start_date = attrs.get("start_date")
        end_date = attrs.get("end_date")
        if start_date and end_date and start_date > end_date:
            raise serializers.ValidationError(
                {"start_date": "start_date must be earlier than or equal to end_date."}
            )
        return attrs


class DailySummaryResponseSerializer(serializers.Serializer):
    """Response serializer for daily summary endpoint."""

    date = serializers.DateField()
    log_count = serializers.IntegerField()
    total_kcal = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_protein = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_carbs = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_fat = serializers.DecimalField(max_digits=10, decimal_places=2)


class TrendsPeriodSerializer(serializers.Serializer):
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    days = serializers.IntegerField()
    days_with_logs = serializers.IntegerField()


class TrendsDailyEntrySerializer(serializers.Serializer):
    date = serializers.DateField()
    log_count = serializers.IntegerField()
    total_kcal = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_protein = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_carbs = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_fat = serializers.DecimalField(max_digits=10, decimal_places=2)
    kcal_deficit = serializers.DecimalField(max_digits=10, decimal_places=2)


class TrendsAverageSerializer(serializers.Serializer):
    kcal = serializers.DecimalField(max_digits=10, decimal_places=2)
    protein = serializers.DecimalField(max_digits=10, decimal_places=2)
    carbs = serializers.DecimalField(max_digits=10, decimal_places=2)
    fat = serializers.DecimalField(max_digits=10, decimal_places=2)
    kcal_deficit = serializers.DecimalField(max_digits=10, decimal_places=2)
    deficit_interpretation = serializers.ChoiceField(
        choices=["average_deficit", "average_surplus", "on_target"]
    )


class TrendsInsightsSerializer(serializers.Serializer):
    average_status = serializers.ChoiceField(choices=["below_target", "above_target", "on_target"])
    average_kcal_gap = serializers.DecimalField(max_digits=10, decimal_places=2)
    logging_consistency_percent = serializers.DecimalField(max_digits=7, decimal_places=2)
    summary = serializers.CharField()


class TrendsResponseSerializer(serializers.Serializer):
    period = TrendsPeriodSerializer()
    target_kcal_per_day = serializers.DecimalField(max_digits=10, decimal_places=2)
    daily = TrendsDailyEntrySerializer(many=True)
    average = TrendsAverageSerializer()
    insights = TrendsInsightsSerializer()


class AdvancedTotalsSerializer(serializers.Serializer):
    kcal = serializers.DecimalField(max_digits=12, decimal_places=2)
    protein = serializers.DecimalField(max_digits=12, decimal_places=2)
    carbs = serializers.DecimalField(max_digits=12, decimal_places=2)
    fat = serializers.DecimalField(max_digits=12, decimal_places=2)
    avg_daily_kcal = serializers.DecimalField(max_digits=12, decimal_places=2)


class MacroRatioPercentSerializer(serializers.Serializer):
    protein = serializers.DecimalField(max_digits=7, decimal_places=2)
    carbs = serializers.DecimalField(max_digits=7, decimal_places=2)
    fat = serializers.DecimalField(max_digits=7, decimal_places=2)


class TargetAchievementSerializer(serializers.Serializer):
    target_kcal_per_day = serializers.DecimalField(max_digits=10, decimal_places=2)
    adherence_tolerance_pct = serializers.DecimalField(max_digits=6, decimal_places=2)
    logged_days = serializers.IntegerField()
    days_met_target = serializers.IntegerField()
    adherence_rate_percent = serializers.DecimalField(max_digits=7, decimal_places=2)
    average_kcal_gap = serializers.DecimalField(max_digits=12, decimal_places=2)


class MealTypeBreakdownSerializer(serializers.Serializer):
    meal_type = serializers.CharField()
    log_count = serializers.IntegerField()
    total_kcal = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_protein = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_carbs = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_fat = serializers.DecimalField(max_digits=12, decimal_places=2)
    kcal_share_percent = serializers.DecimalField(max_digits=7, decimal_places=2)


class WeeklyTrendSerializer(serializers.Serializer):
    week_start = serializers.DateField()
    logged_days = serializers.IntegerField()
    total_kcal = serializers.DecimalField(max_digits=12, decimal_places=2)
    avg_daily_kcal = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_protein = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_carbs = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_fat = serializers.DecimalField(max_digits=12, decimal_places=2)


class MonthlyTrendSerializer(serializers.Serializer):
    month = serializers.CharField()
    logged_days = serializers.IntegerField()
    total_kcal = serializers.DecimalField(max_digits=12, decimal_places=2)
    avg_daily_kcal = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_protein = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_carbs = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_fat = serializers.DecimalField(max_digits=12, decimal_places=2)


class AdvancedDailyTrendSerializer(serializers.Serializer):
    date = serializers.DateField()
    log_count = serializers.IntegerField()
    total_kcal = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_protein = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_carbs = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_fat = serializers.DecimalField(max_digits=12, decimal_places=2)
    kcal_7day_moving_avg = serializers.DecimalField(max_digits=12, decimal_places=2)


class AdvancedAnalyticsResponseSerializer(serializers.Serializer):
    period = TrendsPeriodSerializer()
    totals = AdvancedTotalsSerializer()
    macro_ratio_percent = MacroRatioPercentSerializer()
    target_achievement = TargetAchievementSerializer()
    meal_type_breakdown = MealTypeBreakdownSerializer(many=True)
    weekly_trend = WeeklyTrendSerializer(many=True)
    monthly_trend = MonthlyTrendSerializer(many=True)
    daily_trend = AdvancedDailyTrendSerializer(many=True)
