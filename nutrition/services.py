from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Count, Sum
from django.db.models.functions import TruncMonth, TruncWeek

from nutrition.models import MealLog


class NutritionAnalyticsService:
    """Service layer for daily summary and trends analytics."""

    ZERO = Decimal("0")

    @staticmethod
    def _q(value: Decimal | int | float | str | None) -> Decimal:
        if value is None:
            value = Decimal("0")
        decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
        return decimal_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @classmethod
    def _pct(cls, numerator: Decimal, denominator: Decimal) -> Decimal:
        if denominator == cls.ZERO:
            return cls.ZERO
        return cls._q((numerator / denominator) * Decimal("100"))

    @classmethod
    def get_daily_summary(cls, user, target_date: date) -> dict:
        aggregate = MealLog.objects.filter(user=user, intake_date=target_date).aggregate(
            log_count=Count("id"),
            total_kcal=Sum("actual_kcal"),
            total_protein=Sum("actual_protein"),
            total_carbs=Sum("actual_carbs"),
            total_fat=Sum("actual_fat"),
        )
        return {
            "date": target_date,
            "log_count": aggregate["log_count"] or 0,
            "total_kcal": cls._q(aggregate["total_kcal"]),
            "total_protein": cls._q(aggregate["total_protein"]),
            "total_carbs": cls._q(aggregate["total_carbs"]),
            "total_fat": cls._q(aggregate["total_fat"]),
        }

    @classmethod
    def get_7day_trends(
        cls,
        user,
        end_date: date,
        days: int = 7,
        target_kcal: Decimal = Decimal("2000"),
    ) -> dict:
        start_date = end_date - timedelta(days=days - 1)

        grouped = (
            MealLog.objects.filter(user=user, intake_date__range=(start_date, end_date))
            .values("intake_date")
            .annotate(
                log_count=Count("id"),
                total_kcal=Sum("actual_kcal"),
                total_protein=Sum("actual_protein"),
                total_carbs=Sum("actual_carbs"),
                total_fat=Sum("actual_fat"),
            )
        )
        grouped_by_day = {row["intake_date"]: row for row in grouped}

        daily_entries = []
        total_kcal = cls.ZERO
        total_protein = cls.ZERO
        total_carbs = cls.ZERO
        total_fat = cls.ZERO
        total_deficit = cls.ZERO
        days_with_logs = 0

        for i in range(days):
            current_day = start_date + timedelta(days=i)
            day_row = grouped_by_day.get(current_day, {})

            kcal = cls._q(day_row.get("total_kcal"))
            protein = cls._q(day_row.get("total_protein"))
            carbs = cls._q(day_row.get("total_carbs"))
            fat = cls._q(day_row.get("total_fat"))
            deficit = cls._q(Decimal(target_kcal) - kcal)
            log_count = day_row.get("log_count", 0) or 0

            if log_count > 0:
                days_with_logs += 1

            total_kcal += kcal
            total_protein += protein
            total_carbs += carbs
            total_fat += fat
            total_deficit += deficit

            daily_entries.append(
                {
                    "date": current_day,
                    "log_count": log_count,
                    "total_kcal": kcal,
                    "total_protein": protein,
                    "total_carbs": carbs,
                    "total_fat": fat,
                    "kcal_deficit": deficit,
                }
            )

        divisor = Decimal(days)
        avg_deficit = cls._q(total_deficit / divisor)
        if avg_deficit > cls.ZERO:
            deficit_interpretation = "average_deficit"
        elif avg_deficit < cls.ZERO:
            deficit_interpretation = "average_surplus"
        else:
            deficit_interpretation = "on_target"

        avg_kcal = cls._q(total_kcal / divisor)
        average_kcal_gap = cls._q(Decimal(target_kcal) - avg_kcal)
        if average_kcal_gap > cls.ZERO:
            average_status = "below_target"
            summary = f"Average intake is below target by {average_kcal_gap} kcal/day."
        elif average_kcal_gap < cls.ZERO:
            average_status = "above_target"
            summary = f"Average intake is above target by {abs(average_kcal_gap)} kcal/day."
        else:
            average_status = "on_target"
            summary = "Average intake is on target."
        logging_consistency = cls._q((Decimal(days_with_logs) / divisor) * Decimal("100"))

        return {
            "period": {
                "start_date": start_date,
                "end_date": end_date,
                "days": days,
                "days_with_logs": days_with_logs,
            },
            "target_kcal_per_day": cls._q(target_kcal),
            "daily": daily_entries,
            "average": {
                "kcal": avg_kcal,
                "protein": cls._q(total_protein / divisor),
                "carbs": cls._q(total_carbs / divisor),
                "fat": cls._q(total_fat / divisor),
                "kcal_deficit": avg_deficit,
                "deficit_interpretation": deficit_interpretation,
            },
            "insights": {
                "average_status": average_status,
                "average_kcal_gap": average_kcal_gap,
                "logging_consistency_percent": logging_consistency,
                "summary": summary,
            },
        }

    @classmethod
    def get_advanced_analytics(
        cls,
        user,
        start_date: date,
        end_date: date,
        target_kcal: Decimal = Decimal("2000"),
        adherence_tolerance_pct: Decimal = Decimal("10"),
    ) -> dict:
        base_qs = MealLog.objects.filter(user=user, intake_date__range=(start_date, end_date))
        total_days = (end_date - start_date).days + 1
        grouped_daily_map = cls._get_daily_grouped_map(base_qs=base_qs)
        daily_trend, totals = cls._build_daily_trend(
            grouped_daily_map=grouped_daily_map,
            start_date=start_date,
            total_days=total_days,
        )
        target_achievement = cls._build_target_achievement(
            daily_trend=daily_trend,
            target_kcal=target_kcal,
            adherence_tolerance_pct=adherence_tolerance_pct,
        )
        meal_type_breakdown = cls._build_meal_type_breakdown(
            base_qs=base_qs,
            total_kcal=totals["kcal"],
        )
        weekly_trend = cls._build_weekly_trend(base_qs=base_qs)
        monthly_trend = cls._build_monthly_trend(base_qs=base_qs)
        macro_ratio = cls._build_macro_ratio(
            total_protein=totals["protein"],
            total_carbs=totals["carbs"],
            total_fat=totals["fat"],
        )

        return {
            "period": {
                "start_date": start_date,
                "end_date": end_date,
                "days": total_days,
                "days_with_logs": target_achievement["logged_days"],
            },
            "totals": {
                "kcal": totals["kcal"],
                "protein": totals["protein"],
                "carbs": totals["carbs"],
                "fat": totals["fat"],
                "avg_daily_kcal": cls._q(totals["kcal"] / Decimal(total_days)),
            },
            "macro_ratio_percent": macro_ratio,
            "target_achievement": target_achievement,
            "meal_type_breakdown": meal_type_breakdown,
            "weekly_trend": weekly_trend,
            "monthly_trend": monthly_trend,
            "daily_trend": daily_trend,
        }

    @classmethod
    def _get_daily_grouped_map(cls, base_qs):
        grouped_daily = (
            base_qs.values("intake_date")
            .annotate(
                log_count=Count("id"),
                total_kcal=Sum("actual_kcal"),
                total_protein=Sum("actual_protein"),
                total_carbs=Sum("actual_carbs"),
                total_fat=Sum("actual_fat"),
            )
            .order_by("intake_date")
        )
        return {row["intake_date"]: row for row in grouped_daily}

    @classmethod
    def _build_daily_trend(cls, grouped_daily_map: dict, start_date: date, total_days: int):
        total_kcal = cls.ZERO
        total_protein = cls.ZERO
        total_carbs = cls.ZERO
        total_fat = cls.ZERO
        daily_trend = []
        rolling_kcal_window: list[Decimal] = []

        for i in range(total_days):
            current_day = start_date + timedelta(days=i)
            day_row = grouped_daily_map.get(current_day, {})

            day_kcal = cls._q(day_row.get("total_kcal"))
            day_protein = cls._q(day_row.get("total_protein"))
            day_carbs = cls._q(day_row.get("total_carbs"))
            day_fat = cls._q(day_row.get("total_fat"))
            day_log_count = day_row.get("log_count", 0) or 0

            total_kcal += day_kcal
            total_protein += day_protein
            total_carbs += day_carbs
            total_fat += day_fat

            rolling_kcal_window.append(day_kcal)
            if len(rolling_kcal_window) > 7:
                rolling_kcal_window.pop(0)
            moving_avg = cls._q(sum(rolling_kcal_window, start=cls.ZERO) / Decimal(len(rolling_kcal_window)))

            daily_trend.append(
                {
                    "date": current_day,
                    "log_count": day_log_count,
                    "total_kcal": day_kcal,
                    "total_protein": day_protein,
                    "total_carbs": day_carbs,
                    "total_fat": day_fat,
                    "kcal_7day_moving_avg": moving_avg,
                }
            )

        totals = {
            "kcal": cls._q(total_kcal),
            "protein": cls._q(total_protein),
            "carbs": cls._q(total_carbs),
            "fat": cls._q(total_fat),
        }
        return daily_trend, totals

    @classmethod
    def _build_target_achievement(
        cls,
        daily_trend: list[dict],
        target_kcal: Decimal,
        adherence_tolerance_pct: Decimal,
    ) -> dict:
        min_kcal = Decimal(target_kcal) * (Decimal("1") - (Decimal(adherence_tolerance_pct) / Decimal("100")))
        max_kcal = Decimal(target_kcal) * (Decimal("1") + (Decimal(adherence_tolerance_pct) / Decimal("100")))

        logged_days = 0
        days_met_target = 0
        kcal_gap_sum = cls.ZERO
        for day in daily_trend:
            if day["log_count"] <= 0:
                continue
            logged_days += 1
            day_kcal = day["total_kcal"]
            if min_kcal <= day_kcal <= max_kcal:
                days_met_target += 1
            kcal_gap_sum += cls._q(Decimal(target_kcal) - day_kcal)

        if logged_days == 0:
            adherence_rate = cls.ZERO
            average_kcal_gap = cls.ZERO
        else:
            adherence_rate = cls._q((Decimal(days_met_target) / Decimal(logged_days)) * Decimal("100"))
            average_kcal_gap = cls._q(kcal_gap_sum / Decimal(logged_days))

        return {
            "target_kcal_per_day": cls._q(target_kcal),
            "adherence_tolerance_pct": cls._q(adherence_tolerance_pct),
            "logged_days": logged_days,
            "days_met_target": days_met_target,
            "adherence_rate_percent": adherence_rate,
            "average_kcal_gap": average_kcal_gap,
        }

    @classmethod
    def _build_macro_ratio(cls, total_protein: Decimal, total_carbs: Decimal, total_fat: Decimal) -> dict:
        macro_protein_kcal = total_protein * Decimal("4")
        macro_carbs_kcal = total_carbs * Decimal("4")
        macro_fat_kcal = total_fat * Decimal("9")
        macro_kcal_total = macro_protein_kcal + macro_carbs_kcal + macro_fat_kcal
        return {
            "protein": cls._pct(macro_protein_kcal, macro_kcal_total),
            "carbs": cls._pct(macro_carbs_kcal, macro_kcal_total),
            "fat": cls._pct(macro_fat_kcal, macro_kcal_total),
        }

    @classmethod
    def _build_meal_type_breakdown(cls, base_qs, total_kcal: Decimal) -> list[dict]:
        meal_type_breakdown_qs = (
            base_qs.values("meal_type")
            .annotate(
                log_count=Count("id"),
                total_kcal=Sum("actual_kcal"),
                total_protein=Sum("actual_protein"),
                total_carbs=Sum("actual_carbs"),
                total_fat=Sum("actual_fat"),
            )
            .order_by("meal_type")
        )
        breakdown = []
        for row in meal_type_breakdown_qs:
            meal_kcal = cls._q(row["total_kcal"])
            breakdown.append(
                {
                    "meal_type": row["meal_type"],
                    "log_count": row["log_count"],
                    "total_kcal": meal_kcal,
                    "total_protein": cls._q(row["total_protein"]),
                    "total_carbs": cls._q(row["total_carbs"]),
                    "total_fat": cls._q(row["total_fat"]),
                    "kcal_share_percent": cls._pct(meal_kcal, total_kcal),
                }
            )
        return breakdown

    @classmethod
    def _build_weekly_trend(cls, base_qs) -> list[dict]:
        weekly_qs = (
            base_qs.annotate(week_start=TruncWeek("intake_date"))
            .values("week_start")
            .annotate(
                logged_days=Count("intake_date", distinct=True),
                total_kcal=Sum("actual_kcal"),
                total_protein=Sum("actual_protein"),
                total_carbs=Sum("actual_carbs"),
                total_fat=Sum("actual_fat"),
            )
            .order_by("week_start")
        )
        weekly = []
        for row in weekly_qs:
            logged_days = row["logged_days"] or 1
            weekly.append(
                {
                    "week_start": row["week_start"],
                    "logged_days": row["logged_days"],
                    "total_kcal": cls._q(row["total_kcal"]),
                    "avg_daily_kcal": cls._q(Decimal(row["total_kcal"] or cls.ZERO) / Decimal(logged_days)),
                    "total_protein": cls._q(row["total_protein"]),
                    "total_carbs": cls._q(row["total_carbs"]),
                    "total_fat": cls._q(row["total_fat"]),
                }
            )
        return weekly

    @classmethod
    def _build_monthly_trend(cls, base_qs) -> list[dict]:
        monthly_qs = (
            base_qs.annotate(month_start=TruncMonth("intake_date"))
            .values("month_start")
            .annotate(
                logged_days=Count("intake_date", distinct=True),
                total_kcal=Sum("actual_kcal"),
                total_protein=Sum("actual_protein"),
                total_carbs=Sum("actual_carbs"),
                total_fat=Sum("actual_fat"),
            )
            .order_by("month_start")
        )
        monthly = []
        for row in monthly_qs:
            logged_days = row["logged_days"] or 1
            month_start = row["month_start"]
            monthly.append(
                {
                    "month": month_start.strftime("%Y-%m"),
                    "logged_days": row["logged_days"],
                    "total_kcal": cls._q(row["total_kcal"]),
                    "avg_daily_kcal": cls._q(Decimal(row["total_kcal"] or cls.ZERO) / Decimal(logged_days)),
                    "total_protein": cls._q(row["total_protein"]),
                    "total_carbs": cls._q(row["total_carbs"]),
                    "total_fat": cls._q(row["total_fat"]),
                }
            )
        return monthly
