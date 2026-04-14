from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from nutrition.models import FoodItem, MealLog

User = get_user_model()


class MealLogModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="StrongPass123!")
        self.food = FoodItem.objects.create(
            name="Rounded Food",
            diet_type=FoodItem.DietType.OTHER,
            per_100g_kcal=Decimal("123.45"),
            per_100g_protein=Decimal("10.11"),
            per_100g_carbs=Decimal("20.22"),
            per_100g_fat=Decimal("30.33"),
            source="TEST",
        )

    def test_save_calculates_actual_nutrients_with_two_decimal_rounding(self):
        log = MealLog.objects.create(
            user=self.user,
            intake_date=date(2026, 4, 13),
            meal_type="lunch",
            food_item=self.food,
            intake_weight_grams=Decimal("55.55"),
        )

        self.assertEqual(log.actual_kcal, Decimal("68.58"))
        self.assertEqual(log.actual_protein, Decimal("5.62"))
        self.assertEqual(log.actual_carbs, Decimal("11.23"))
        self.assertEqual(log.actual_fat, Decimal("16.85"))

    def test_save_recomputes_when_weight_changes(self):
        log = MealLog.objects.create(
            user=self.user,
            intake_date=date(2026, 4, 13),
            meal_type="lunch",
            food_item=self.food,
            intake_weight_grams=Decimal("55.55"),
        )

        log.intake_weight_grams = Decimal("100.00")
        log.save()
        log.refresh_from_db()

        self.assertEqual(log.actual_kcal, Decimal("123.45"))
        self.assertEqual(log.actual_protein, Decimal("10.11"))
        self.assertEqual(log.actual_carbs, Decimal("20.22"))
        self.assertEqual(log.actual_fat, Decimal("30.33"))

    def test_weight_must_be_positive(self):
        log = MealLog(
            user=self.user,
            intake_date=date(2026, 4, 13),
            meal_type="lunch",
            food_item=self.food,
            intake_weight_grams=Decimal("0.00"),
        )

        with self.assertRaises(ValidationError):
            log.full_clean()
