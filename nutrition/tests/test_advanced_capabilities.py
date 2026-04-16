from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from nutrition.models import FoodItem, MealLog
from nutrition.throttles import AnalyticsRateThrottle

User = get_user_model()


def as_decimal(value) -> Decimal:
    return Decimal(str(value))


class AdvancedCapabilitiesAPITests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username="alice", password="StrongPass123!")
        self.client.force_authenticate(self.user)

        self.food_a = FoodItem.objects.create(
            name="Food A",
            diet_type=FoodItem.DietType.VEGAN,
            per_100g_kcal=Decimal("120.00"),
            per_100g_protein=Decimal("10.00"),
            per_100g_carbs=Decimal("15.00"),
            per_100g_fat=Decimal("4.00"),
            source="TEST",
        )
        self.food_b = FoodItem.objects.create(
            name="Food B",
            diet_type=FoodItem.DietType.OMNIVORE,
            per_100g_kcal=Decimal("250.00"),
            per_100g_protein=Decimal("22.00"),
            per_100g_carbs=Decimal("4.00"),
            per_100g_fat=Decimal("12.00"),
            source="TEST",
        )
        self.food_c = FoodItem.objects.create(
            name="Food C",
            diet_type=FoodItem.DietType.VEGETARIAN,
            per_100g_kcal=Decimal("90.00"),
            per_100g_protein=Decimal("3.00"),
            per_100g_carbs=Decimal("20.00"),
            per_100g_fat=Decimal("1.50"),
            source="TEST",
        )

    def test_foods_support_complex_filter_and_ordering(self):
        response = self.client.get(
            reverse("food-item-list"),
            {
                "protein_min": "8",
                "protein_max": "30",
                "kcal_min": "100",
                "ordering": "-per_100g_kcal",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(response.data["results"][0]["name"], "Food B")
        self.assertEqual(response.data["results"][1]["name"], "Food A")

    def test_meallog_supports_complex_filters(self):
        MealLog.objects.create(
            user=self.user,
            intake_date=date(2026, 4, 10),
            meal_type="breakfast",
            food_item=self.food_a,
            intake_weight_grams=Decimal("100.00"),
        )  # kcal 120
        MealLog.objects.create(
            user=self.user,
            intake_date=date(2026, 4, 11),
            meal_type="lunch",
            food_item=self.food_b,
            intake_weight_grams=Decimal("100.00"),
        )  # kcal 250
        MealLog.objects.create(
            user=self.user,
            intake_date=date(2026, 4, 12),
            meal_type="dinner",
            food_item=self.food_a,
            intake_weight_grams=Decimal("200.00"),
        )  # kcal 240

        response = self.client.get(
            reverse("meal-log-list-create"),
            {
                "start_date": "2026-04-10",
                "end_date": "2026-04-12",
                "meal_types": "breakfast,dinner",
                "kcal_min": "150",
                "ordering": "-actual_kcal",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["meal_type"], "dinner")
        self.assertEqual(as_decimal(response.data["results"][0]["actual_kcal"]), Decimal("240.00"))

    def test_food_list_uses_cache(self):
        url = reverse("food-item-list")

        first = self.client.get(url, {"q": "Food"})
        second = self.client.get(url, {"q": "Food"})

        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(first["X-Cache"], "MISS")
        self.assertEqual(second["X-Cache"], "HIT")
        self.assertEqual(first.data["count"], second.data["count"])

    def test_analytics_cache_invalidates_after_meallog_write(self):
        MealLog.objects.create(
            user=self.user,
            intake_date=date(2026, 4, 12),
            meal_type="breakfast",
            food_item=self.food_a,
            intake_weight_grams=Decimal("100.00"),
        )
        url = reverse("nutrition-trends")
        params = {"end_date": "2026-04-12", "days": 3, "target_kcal": "2000"}

        first = self.client.get(url, params)
        second = self.client.get(url, params)
        self.assertEqual(first["X-Cache"], "MISS")
        self.assertEqual(second["X-Cache"], "HIT")

        create_response = self.client.post(
            reverse("meal-log-list-create"),
            {
                "intake_date": "2026-04-12",
                "meal_type": "dinner",
                "food_item": self.food_b.id,
                "intake_weight_grams": "100.00",
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)

        third = self.client.get(url, params)
        self.assertEqual(third.status_code, status.HTTP_200_OK)
        self.assertEqual(third["X-Cache"], "MISS")

    def test_error_response_envelope_has_standard_shape(self):
        response = self.client.get(reverse("meal-log-daily-summary"))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "validation_error")
        self.assertIn("message", response.data)
        self.assertIn("details", response.data)
        self.assertIn("request_id", response.data)
        self.assertIn("timestamp", response.data)
        self.assertIn("date", response.data["details"])

    def test_analytics_endpoint_rate_limit(self):
        cache.clear()
        MealLog.objects.create(
            user=self.user,
            intake_date=date(2026, 4, 12),
            meal_type="breakfast",
            food_item=self.food_a,
            intake_weight_grams=Decimal("100.00"),
        )
        url = reverse("nutrition-trends")
        params = {"end_date": "2026-04-12", "days": 1, "target_kcal": "2000"}

        with patch.object(AnalyticsRateThrottle, "get_rate", return_value="2/minute"):
            r1 = self.client.get(url, params)
            r2 = self.client.get(url, params)
            r3 = self.client.get(url, params)

        self.assertEqual(r1.status_code, status.HTTP_200_OK)
        self.assertEqual(r2.status_code, status.HTTP_200_OK)
        self.assertEqual(r3.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(r3.data["code"], "rate_limited")
