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


class MealLogAPITests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="StrongPass123!")
        self.other_user = User.objects.create_user(username="bob", password="StrongPass123!")

        self.food = FoodItem.objects.create(
            name="Greek Yogurt",
            diet_type=FoodItem.DietType.VEGETARIAN,
            per_100g_kcal=Decimal("59.00"),
            per_100g_protein=Decimal("10.00"),
            per_100g_carbs=Decimal("3.60"),
            per_100g_fat=Decimal("0.40"),
            source="TEST",
        )

    def test_create_meallog_computes_actual_nutrients(self):
        self.client.force_authenticate(self.user)

        payload = {
            "intake_date": "2026-04-13",
            "meal_type": "lunch",
            "food_item": self.food.id,
            "intake_weight_grams": "150.00",
        }
        response = self.client.post(reverse("meal-log-list-create"), payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(as_decimal(response.data["actual_kcal"]), Decimal("88.50"))
        self.assertEqual(as_decimal(response.data["actual_protein"]), Decimal("15.00"))
        self.assertEqual(as_decimal(response.data["actual_carbs"]), Decimal("5.40"))
        self.assertEqual(as_decimal(response.data["actual_fat"]), Decimal("0.60"))

        log = MealLog.objects.get(pk=response.data["id"])
        self.assertEqual(log.user_id, self.user.id)

    def test_list_returns_only_current_user_data(self):
        MealLog.objects.create(
            user=self.user,
            intake_date=date(2026, 4, 13),
            meal_type="lunch",
            food_item=self.food,
            intake_weight_grams=Decimal("100.00"),
        )
        MealLog.objects.create(
            user=self.other_user,
            intake_date=date(2026, 4, 13),
            meal_type="dinner",
            food_item=self.food,
            intake_weight_grams=Decimal("120.00"),
        )
        self.client.force_authenticate(self.user)

        response = self.client.get(reverse("meal-log-list-create"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["meal_type"], "lunch")

    def test_list_supports_date_filter(self):
        MealLog.objects.create(
            user=self.user,
            intake_date=date(2026, 4, 12),
            meal_type="breakfast",
            food_item=self.food,
            intake_weight_grams=Decimal("100.00"),
        )
        MealLog.objects.create(
            user=self.user,
            intake_date=date(2026, 4, 13),
            meal_type="lunch",
            food_item=self.food,
            intake_weight_grams=Decimal("100.00"),
        )
        self.client.force_authenticate(self.user)

        response = self.client.get(reverse("meal-log-list-create"), {"date": "2026-04-12"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["intake_date"], "2026-04-12")

    def test_other_user_cannot_access_meallog_detail(self):
        foreign_log = MealLog.objects.create(
            user=self.other_user,
            intake_date=date(2026, 4, 13),
            meal_type="dinner",
            food_item=self.food,
            intake_weight_grams=Decimal("120.00"),
        )
        self.client.force_authenticate(self.user)

        response = self.client.get(reverse("meal-log-detail", kwargs={"pk": foreign_log.pk}))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_patch_recomputes_nutrients(self):
        log = MealLog.objects.create(
            user=self.user,
            intake_date=date(2026, 4, 13),
            meal_type="snack",
            food_item=self.food,
            intake_weight_grams=Decimal("100.00"),
        )
        self.client.force_authenticate(self.user)

        response = self.client.patch(
            reverse("meal-log-detail", kwargs={"pk": log.pk}),
            {"intake_weight_grams": "200.00"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(as_decimal(response.data["actual_kcal"]), Decimal("118.00"))
        self.assertEqual(as_decimal(response.data["actual_protein"]), Decimal("20.00"))

    def test_delete_meallog(self):
        log = MealLog.objects.create(
            user=self.user,
            intake_date=date(2026, 4, 13),
            meal_type="snack",
            food_item=self.food,
            intake_weight_grams=Decimal("100.00"),
        )
        self.client.force_authenticate(self.user)

        response = self.client.delete(reverse("meal-log-detail", kwargs={"pk": log.pk}))

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(MealLog.objects.filter(pk=log.pk).exists())
