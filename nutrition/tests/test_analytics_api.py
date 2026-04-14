from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from nutrition.models import FoodItem, MealLog

User = get_user_model()


def as_decimal(value) -> Decimal:
    return Decimal(str(value))


class AnalyticsAPITests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="StrongPass123!")
        self.food = FoodItem.objects.create(
            name="Test Food",
            diet_type=FoodItem.DietType.OMNIVORE,
            per_100g_kcal=Decimal("100.00"),
            per_100g_protein=Decimal("10.00"),
            per_100g_carbs=Decimal("20.00"),
            per_100g_fat=Decimal("5.00"),
            source="TEST",
        )
        MealLog.objects.create(
            user=self.user,
            intake_date=date(2026, 4, 10),
            meal_type="breakfast",
            food_item=self.food,
            intake_weight_grams=Decimal("100.00"),
        )
        MealLog.objects.create(
            user=self.user,
            intake_date=date(2026, 4, 12),
            meal_type="dinner",
            food_item=self.food,
            intake_weight_grams=Decimal("150.00"),
        )

    def test_daily_summary_requires_date(self):
        self.client.force_authenticate(self.user)

        response = self.client.get(reverse("meal-log-daily-summary"))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("date", response.data)

    def test_daily_summary_returns_correct_aggregate(self):
        self.client.force_authenticate(self.user)

        response = self.client.get(
            reverse("meal-log-daily-summary"),
            {"date": "2026-04-12"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["log_count"], 1)
        self.assertEqual(as_decimal(response.data["total_kcal"]), Decimal("150.00"))
        self.assertEqual(as_decimal(response.data["total_protein"]), Decimal("15.00"))
        self.assertEqual(as_decimal(response.data["total_carbs"]), Decimal("30.00"))
        self.assertEqual(as_decimal(response.data["total_fat"]), Decimal("7.50"))

    def test_trends_endpoint_includes_gap_days(self):
        self.client.force_authenticate(self.user)

        response = self.client.get(
            reverse("nutrition-trends"),
            {"end_date": "2026-04-12", "days": 3, "target_kcal": "200"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["period"]["start_date"], date(2026, 4, 10))
        self.assertEqual(response.data["period"]["days_with_logs"], 2)
        self.assertEqual(len(response.data["daily"]), 3)
        self.assertEqual(response.data["daily"][1]["date"], date(2026, 4, 11))
        self.assertEqual(as_decimal(response.data["daily"][1]["total_kcal"]), Decimal("0.00"))
        self.assertEqual(as_decimal(response.data["average"]["kcal"]), Decimal("83.33"))

    def test_advanced_analytics_returns_core_sections(self):
        self.client.force_authenticate(self.user)

        response = self.client.get(
            reverse("nutrition-advanced-analytics"),
            {
                "start_date": "2026-04-10",
                "end_date": "2026-04-12",
                "target_kcal": "200",
                "adherence_tolerance_pct": "10",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["period"]["days"], 3)
        self.assertEqual(response.data["target_achievement"]["logged_days"], 2)
        self.assertEqual(response.data["target_achievement"]["days_met_target"], 0)
        self.assertEqual(as_decimal(response.data["totals"]["kcal"]), Decimal("250.00"))
        self.assertEqual(as_decimal(response.data["totals"]["avg_daily_kcal"]), Decimal("83.33"))
        self.assertEqual(len(response.data["daily_trend"]), 3)
        self.assertTrue(isinstance(response.data["meal_type_breakdown"], list))
        self.assertTrue(isinstance(response.data["weekly_trend"], list))
        self.assertTrue(isinstance(response.data["monthly_trend"], list))
