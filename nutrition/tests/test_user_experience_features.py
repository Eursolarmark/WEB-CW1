from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from nutrition.models import FoodFavorite, FoodItem, MealLog

User = get_user_model()


def as_decimal(value) -> Decimal:
    return Decimal(str(value))


class UserExperienceFeatureTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="alice",
            email="alice@example.com",
            password="StrongPass123!",
        )
        self.client.force_authenticate(self.user)
        self.food = FoodItem.objects.create(
            name="Banana",
            diet_type=FoodItem.DietType.VEGAN,
            per_100g_kcal=Decimal("89.00"),
            per_100g_protein=Decimal("1.10"),
            per_100g_carbs=Decimal("22.80"),
            per_100g_fat=Decimal("0.30"),
            source="TEST",
        )

    def test_favorites_flow(self):
        create_response = self.client.post(
            reverse("food-favorite-list-create"),
            {"food_item": self.food.id},
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(FoodFavorite.objects.filter(user=self.user, food_item=self.food).exists())

        list_response = self.client.get(reverse("food-favorite-list-create"))
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(list_response.data), 1)
        self.assertEqual(list_response.data[0]["food_item"], self.food.id)

        delete_response = self.client.delete(reverse("food-favorite-delete", kwargs={"food_item_id": self.food.id}))
        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(FoodFavorite.objects.filter(user=self.user, food_item=self.food).exists())

    def test_trends_target_defaults_and_accepts_override(self):
        MealLog.objects.create(
            user=self.user,
            intake_date=date(2026, 4, 17),
            meal_type="dinner",
            food_item=self.food,
            intake_weight_grams=Decimal("100.00"),
        )

        default_response = self.client.get(
            reverse("nutrition-trends"),
            {"end_date": "2026-04-17", "days": 1},
        )
        self.assertEqual(default_response.status_code, status.HTTP_200_OK)
        self.assertEqual(as_decimal(default_response.data["target_kcal_per_day"]), Decimal("2000.00"))

        override_response = self.client.get(
            reverse("nutrition-trends"),
            {"end_date": "2026-04-17", "days": 1, "target_kcal": "1500.00"},
        )
        self.assertEqual(override_response.status_code, status.HTTP_200_OK)
        self.assertEqual(as_decimal(override_response.data["target_kcal_per_day"]), Decimal("1500.00"))
