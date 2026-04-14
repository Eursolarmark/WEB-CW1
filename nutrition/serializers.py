from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from nutrition.models import FoodItem, MealLog

User = get_user_model()


class MealLogSerializer(serializers.ModelSerializer):
    """Serializer for creating/updating and reading meal logs."""

    user = serializers.IntegerField(source="user_id", read_only=True)
    food_item_name = serializers.CharField(source="food_item.name", read_only=True)

    class Meta:
        model = MealLog
        fields = [
            "id",
            "user",
            "intake_date",
            "meal_type",
            "food_item",
            "food_item_name",
            "intake_weight_grams",
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
            "actual_kcal",
            "actual_protein",
            "actual_carbs",
            "actual_fat",
            "created_at",
            "updated_at",
        ]


class MealLogListQuerySerializer(serializers.Serializer):
    """Query serializer for listing meal logs."""

    date = serializers.DateField(required=False)


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


class RegisterSerializer(serializers.ModelSerializer):
    """Serializer for account creation."""

    password = serializers.CharField(write_only=True, min_length=8, validators=[validate_password])
    password_confirm = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = ["id", "username", "email", "password", "password_confirm"]
        read_only_fields = ["id"]

    def validate(self, attrs):
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


class DailySummaryQuerySerializer(serializers.Serializer):
    """Query serializer for /api/logs/daily-summary/ endpoint."""

    date = serializers.DateField(required=True)


class TrendsQuerySerializer(serializers.Serializer):
    """Query serializer for /api/analytics/trends/ endpoint."""

    end_date = serializers.DateField(required=False)
    days = serializers.IntegerField(required=False, default=7, min_value=1, max_value=31)
    target_kcal = serializers.DecimalField(
        required=False,
        default=Decimal("2000"),
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
        default=Decimal("2000"),
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


class TrendsResponseSerializer(serializers.Serializer):
    period = TrendsPeriodSerializer()
    target_kcal_per_day = serializers.DecimalField(max_digits=10, decimal_places=2)
    daily = TrendsDailyEntrySerializer(many=True)
    average = TrendsAverageSerializer()


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
