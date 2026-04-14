from django.conf import settings
from django.db import migrations, models


def backfill_meallog_user(apps, schema_editor):
    app_label, model_name = settings.AUTH_USER_MODEL.split(".")
    User = apps.get_model(app_label, model_name)
    MealLog = apps.get_model("nutrition", "MealLog")

    legacy_user, _ = User.objects.get_or_create(
        username="legacy_owner",
        defaults={"email": "legacy_owner@local.invalid"},
    )
    MealLog.objects.filter(user__isnull=True).update(user_id=legacy_user.pk)


class Migration(migrations.Migration):
    dependencies = [
        ("nutrition", "0002_remove_meallog_nutrition_m_intake__5ebcb9_idx_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_meallog_user, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="meallog",
            name="user",
            field=models.ForeignKey(
                on_delete=models.CASCADE,
                related_name="meal_logs",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
