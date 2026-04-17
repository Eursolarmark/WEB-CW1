from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class FoodItem(models.Model):
    """Canonical food table with nutrition values normalized per 100g."""

    class DietType(models.TextChoices):
        HIGH_PROTEIN = "high_protein", "High Protein"
        KETO = "keto", "Keto"
        VEGAN = "vegan", "Vegan"
        VEGETARIAN = "vegetarian", "Vegetarian"
        OMNIVORE = "omnivore", "Omnivore"
        OTHER = "other", "Other"

    name = models.CharField(max_length=255, unique=True)
    diet_type = models.CharField(
        max_length=32,
        choices=DietType.choices,
        default=DietType.OMNIVORE,
    )
    per_100g_kcal = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Calories per 100g",
    )
    per_100g_protein = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Protein grams per 100g",
    )
    per_100g_carbs = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Carbohydrate grams per 100g",
    )
    per_100g_fat = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Fat grams per 100g",
    )
    source = models.CharField(
        max_length=128,
        blank=True,
        help_text="Dataset/source name such as USDA/FSA",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        constraints = [
            models.CheckConstraint(
                condition=models.Q(per_100g_kcal__gte=0),
                name="fooditem_kcal_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(per_100g_protein__gte=0),
                name="fooditem_protein_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(per_100g_carbs__gte=0),
                name="fooditem_carbs_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(per_100g_fat__gte=0),
                name="fooditem_fat_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class CustomFoodItem(models.Model):
    """User-defined food profile normalized per 100g."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="custom_food_items",
    )
    name = models.CharField(max_length=255)
    per_100g_kcal = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
    )
    per_100g_protein = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
    )
    per_100g_carbs = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
    )
    per_100g_fat = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(fields=["user", "name"], name="custom_food_unique_name_per_user"),
            models.CheckConstraint(
                condition=models.Q(per_100g_kcal__gte=0),
                name="custom_food_kcal_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(per_100g_protein__gte=0),
                name="custom_food_protein_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(per_100g_carbs__gte=0),
                name="custom_food_carbs_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(per_100g_fat__gte=0),
                name="custom_food_fat_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user.username} - {self.name}"


class MealLog(models.Model):
    """User meal entry with denormalized nutrition values for fast analytics."""

    class MealType(models.TextChoices):
        BREAKFAST = "breakfast", "Breakfast"
        LUNCH = "lunch", "Lunch"
        DINNER = "dinner", "Dinner"
        SNACK = "snack", "Snack"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="meal_logs",
    )
    intake_date = models.DateField(db_index=True)
    meal_type = models.CharField(max_length=16, choices=MealType.choices)
    food_item = models.ForeignKey(
        FoodItem,
        on_delete=models.PROTECT,
        related_name="meal_logs",
        null=True,
        blank=True,
    )
    custom_food = models.ForeignKey(
        CustomFoodItem,
        on_delete=models.PROTECT,
        related_name="meal_logs",
        null=True,
        blank=True,
    )
    intake_weight_grams = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )

    # These values are computed from food macros and intake weight on save.
    actual_kcal = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
        editable=False,
    )
    actual_protein = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
        editable=False,
    )
    actual_carbs = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
        editable=False,
    )
    actual_fat = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
        editable=False,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-intake_date", "-created_at")
        indexes = [
            models.Index(fields=["user", "intake_date"]),
            models.Index(fields=["user", "intake_date", "meal_type"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(intake_weight_grams__gt=0),
                name="meallog_weight_positive",
            ),
            models.CheckConstraint(
                condition=(
                    (models.Q(food_item__isnull=False) & models.Q(custom_food__isnull=True))
                    | (models.Q(food_item__isnull=True) & models.Q(custom_food__isnull=False))
                ),
                name="meallog_exactly_one_food_source",
            ),
            models.CheckConstraint(
                condition=models.Q(actual_kcal__gte=0),
                name="meallog_kcal_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(actual_protein__gte=0),
                name="meallog_protein_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(actual_carbs__gte=0),
                name="meallog_carbs_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(actual_fat__gte=0),
                name="meallog_fat_non_negative",
            ),
        ]

    def __str__(self) -> str:
        source_name = self.food_item.name if self.food_item_id else self.custom_food.name
        return f"{self.user.username}: {self.intake_date} {self.get_meal_type_display()} - {source_name}"

    @staticmethod
    def _round(value: Decimal) -> Decimal:
        """Ensure deterministic 2-decimal rounding across DB backends."""
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def calculate_actual_nutrients(self) -> dict[str, Decimal]:
        """
        Compute absolute nutrition values from per-100g food profile.

        Formula:
            actual_metric = (intake_weight_grams / 100) * per_100g_metric
        """
        source = self.food_item if self.food_item_id else self.custom_food
        if source is None:
            raise ValueError("Either food_item or custom_food must be set.")

        factor = Decimal(self.intake_weight_grams) / Decimal("100")
        return {
            "actual_kcal": self._round(factor * Decimal(source.per_100g_kcal)),
            "actual_protein": self._round(factor * Decimal(source.per_100g_protein)),
            "actual_carbs": self._round(factor * Decimal(source.per_100g_carbs)),
            "actual_fat": self._round(factor * Decimal(source.per_100g_fat)),
        }

    def save(self, *args, **kwargs):
        # Keep computed columns synchronized whenever a log is created/updated.
        computed = self.calculate_actual_nutrients()
        self.actual_kcal = computed["actual_kcal"]
        self.actual_protein = computed["actual_protein"]
        self.actual_carbs = computed["actual_carbs"]
        self.actual_fat = computed["actual_fat"]
        return super().save(*args, **kwargs)


class FoodFavorite(models.Model):
    """User-starred foods for quick access."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="food_favorites",
    )
    food_item = models.ForeignKey(
        FoodItem,
        on_delete=models.CASCADE,
        related_name="favorited_by",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(fields=["user", "food_item"], name="food_favorite_unique_per_user"),
        ]


class UserNutritionTarget(models.Model):
    """Per-user nutrition targets for personalized analytics defaults."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="nutrition_target",
    )
    target_kcal = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
        default=Decimal("2000"),
    )
    target_protein = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
        default=Decimal("120"),
    )
    target_carbs = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
        default=Decimal("220"),
    )
    target_fat = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
        default=Decimal("67"),
    )
    updated_at = models.DateTimeField(auto_now=True)


class Recipe(models.Model):
    """User recipe template built from food/custom-food components."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="recipes",
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(fields=["user", "name"], name="recipe_unique_name_per_user"),
        ]

    def __str__(self) -> str:
        return f"{self.user.username} - {self.name}"


class RecipeItem(models.Model):
    """Ingredient item in a user recipe."""

    recipe = models.ForeignKey(
        Recipe,
        on_delete=models.CASCADE,
        related_name="items",
    )
    food_item = models.ForeignKey(
        FoodItem,
        on_delete=models.PROTECT,
        related_name="recipe_items",
        null=True,
        blank=True,
    )
    custom_food = models.ForeignKey(
        CustomFoodItem,
        on_delete=models.PROTECT,
        related_name="recipe_items",
        null=True,
        blank=True,
    )
    weight_grams = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    (models.Q(food_item__isnull=False) & models.Q(custom_food__isnull=True))
                    | (models.Q(food_item__isnull=True) & models.Q(custom_food__isnull=False))
                ),
                name="recipe_item_exactly_one_food_source",
            ),
            models.CheckConstraint(
                condition=models.Q(weight_grams__gt=0),
                name="recipe_item_weight_positive",
            ),
        ]

    @property
    def source_name(self) -> str:
        return self.food_item.name if self.food_item_id else self.custom_food.name
