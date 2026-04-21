from django.db import migrations, models
import django.db.models.deletion


def delete_orphan_meallogs(apps, schema_editor):
    MealLog = apps.get_model("nutrition", "MealLog")
    MealLog.objects.filter(food_item_id__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("nutrition", "0005_remove_customfooditem_custom_food_unique_name_per_user_and_more"),
    ]

    operations = [
        migrations.RunPython(delete_orphan_meallogs, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="meallog",
            name="food_item",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="meal_logs",
                to="nutrition.fooditem",
            ),
        ),
    ]
