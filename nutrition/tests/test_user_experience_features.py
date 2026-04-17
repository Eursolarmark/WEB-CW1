from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from nutrition.models import CustomFoodItem, FoodFavorite, FoodItem, MealLog, UserNutritionTarget

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

    def test_quick_log_by_food_name_with_unit(self):
        response = self.client.post(
            reverse("meal-log-quick-create"),
            {
                "food_name": "banana",
                "intake_date": "2026-04-17",
                "meal_type": "snack",
                "unit": "piece",
                "unit_quantity": "1.00",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["food_item"], self.food.id)
        self.assertEqual(as_decimal(response.data["intake_weight_grams"]), Decimal("50.00"))
        self.assertEqual(as_decimal(response.data["actual_kcal"]), Decimal("44.50"))

    def test_bulk_create_supports_idempotency(self):
        url = reverse("meal-log-bulk-create")
        payload = {
            "items": [
                {
                    "intake_date": "2026-04-17",
                    "meal_type": "breakfast",
                    "food_item": self.food.id,
                    "intake_weight_grams": "100.00",
                },
                {
                    "intake_date": "2026-04-17",
                    "meal_type": "lunch",
                    "food_item": self.food.id,
                    "unit": "piece",
                    "unit_quantity": "2.00",
                },
            ]
        }

        first = self.client.post(
            url,
            payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY="bulk-001",
        )
        second = self.client.post(
            url,
            payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY="bulk-001",
        )

        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second["X-Idempotent-Replay"], "true")
        self.assertEqual(MealLog.objects.filter(user=self.user).count(), 2)

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

    def test_custom_food_and_meallog(self):
        custom_food_response = self.client.post(
            reverse("custom-food-list-create"),
            {
                "name": "My Oat Bowl",
                "per_100g_kcal": "150.00",
                "per_100g_protein": "6.00",
                "per_100g_carbs": "24.00",
                "per_100g_fat": "3.00",
            },
            format="json",
        )
        self.assertEqual(custom_food_response.status_code, status.HTTP_201_CREATED)
        custom_food_id = custom_food_response.data["id"]

        log_response = self.client.post(
            reverse("meal-log-list-create"),
            {
                "intake_date": "2026-04-17",
                "meal_type": "breakfast",
                "custom_food": custom_food_id,
                "intake_weight_grams": "200.00",
            },
            format="json",
        )
        self.assertEqual(log_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(log_response.data["custom_food"], custom_food_id)
        self.assertEqual(log_response.data["custom_food_name"], "My Oat Bowl")
        self.assertEqual(as_decimal(log_response.data["actual_kcal"]), Decimal("300.00"))

    def test_user_target_is_default_for_trends_when_target_not_provided(self):
        UserNutritionTarget.objects.create(
            user=self.user,
            target_kcal=Decimal("1500.00"),
            target_protein=Decimal("100.00"),
            target_carbs=Decimal("180.00"),
            target_fat=Decimal("50.00"),
        )
        MealLog.objects.create(
            user=self.user,
            intake_date=date(2026, 4, 17),
            meal_type="dinner",
            food_item=self.food,
            intake_weight_grams=Decimal("100.00"),
        )

        response = self.client.get(
            reverse("nutrition-trends"),
            {"end_date": "2026-04-17", "days": 1},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(as_decimal(response.data["target_kcal_per_day"]), Decimal("1500.00"))

    def test_recipe_create_and_total_values(self):
        custom_food = CustomFoodItem.objects.create(
            user=self.user,
            name="Custom Yogurt",
            per_100g_kcal=Decimal("100.00"),
            per_100g_protein=Decimal("10.00"),
            per_100g_carbs=Decimal("8.00"),
            per_100g_fat=Decimal("2.00"),
        )
        response = self.client.post(
            reverse("recipe-list-create"),
            {
                "name": "Breakfast Bowl",
                "description": "Demo recipe",
                "items": [
                    {"food_item": self.food.id, "weight_grams": "100.00"},
                    {"custom_food": custom_food.id, "weight_grams": "150.00"},
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["name"], "Breakfast Bowl")
        self.assertEqual(as_decimal(response.data["total_kcal"]), Decimal("239.00"))

