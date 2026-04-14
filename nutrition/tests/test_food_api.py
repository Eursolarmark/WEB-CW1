from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from nutrition.models import FoodItem

User = get_user_model()


class FoodItemAPITests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="StrongPass123!")

        FoodItem.objects.create(
            name="Tofu",
            diet_type=FoodItem.DietType.VEGAN,
            per_100g_kcal=Decimal("76.00"),
            per_100g_protein=Decimal("8.00"),
            per_100g_carbs=Decimal("1.90"),
            per_100g_fat=Decimal("4.80"),
            source="TEST",
        )
        FoodItem.objects.create(
            name="Chicken Breast",
            diet_type=FoodItem.DietType.HIGH_PROTEIN,
            per_100g_kcal=Decimal("165.00"),
            per_100g_protein=Decimal("31.00"),
            per_100g_carbs=Decimal("0.00"),
            per_100g_fat=Decimal("3.60"),
            source="TEST",
        )
        FoodItem.objects.create(
            name="Brown Rice",
            diet_type=FoodItem.DietType.VEGAN,
            per_100g_kcal=Decimal("111.00"),
            per_100g_protein=Decimal("2.60"),
            per_100g_carbs=Decimal("23.00"),
            per_100g_fat=Decimal("0.90"),
            source="TEST",
        )

    def test_list_requires_authentication(self):
        response = self.client.get(reverse("food-item-list"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_foods_with_pagination(self):
        self.client.force_authenticate(self.user)

        response = self.client.get(reverse("food-item-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 3)
        self.assertIn("results", response.data)
        self.assertEqual(len(response.data["results"]), 3)

    def test_filter_foods_by_query_and_diet_type(self):
        self.client.force_authenticate(self.user)

        response = self.client.get(
            reverse("food-item-list"),
            {"q": "rice", "diet_type": FoodItem.DietType.VEGAN},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["name"], "Brown Rice")

    def test_filter_with_invalid_diet_type_returns_400(self):
        self.client.force_authenticate(self.user)

        response = self.client.get(reverse("food-item-list"), {"diet_type": "carnivore"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("diet_type", response.data)
