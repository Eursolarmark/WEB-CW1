import csv
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from nutrition.models import FoodItem


# Aliases for common single-table nutrition datasets (USDA/FSA/Kaggle variants).
COLUMN_ALIASES = {
    "name": [
        "name",
        "food_name",
        "description",
        "long_desc",
        "item",
        "food",
    ],
    "kcal": [
        "kcal",
        "calories",
        "energy_kcal",
        "energy (kcal)",
        "energy",
        "calories per 100g",
    ],
    "protein": [
        "protein",
        "protein_g",
        "protein (g)",
        "protein per 100g",
    ],
    "carbs": [
        "carbs",
        "carbohydrate",
        "carbohydrates",
        "carbohydrate_g",
        "carbohydrate (g)",
        "carbohydrate per 100g",
    ],
    "fat": [
        "fat",
        "total_fat",
        "fat_g",
        "fat (g)",
        "fat per 100g",
        "lipid",
    ],
}

USDA_FILE_ALIASES = {
    "food": ("food.csv", "foods.csv"),
    "food_nutrient": ("food_nutrient.csv", "foodnutrient.csv"),
    "nutrient": ("nutrient.csv", "nutrients.csv"),
}

# Common USDA nutrient numbers used across FoodData Central variants.
USDA_NUTRIENT_NUMBER_MAP = {
    "1008": "kcal",      # Energy (kcal)
    "208": "kcal",       # Legacy Energy
    "1003": "protein",   # Protein
    "203": "protein",    # Legacy Protein
    "1005": "carbs",     # Carbohydrate, by difference
    "205": "carbs",      # Legacy Carbohydrate
    "1004": "fat",       # Total lipid (fat)
    "204": "fat",        # Legacy fat
}


@dataclass(frozen=True)
class ParsedFoodRow:
    name: str
    per_100g_kcal: Decimal
    per_100g_protein: Decimal
    per_100g_carbs: Decimal
    per_100g_fat: Decimal
    diet_type: str


class Command(BaseCommand):
    help = "Import and clean food nutrition data into FoodItem table."

    def add_arguments(self, parser):
        mode_group = parser.add_mutually_exclusive_group(required=False)
        mode_group.add_argument(
            "--csv-path",
            help="Path to a single CSV with name/kcal/protein/carbs/fat columns.",
        )
        mode_group.add_argument(
            "--usda-dir",
            help=(
                "Path to USDA FoodData Central directory containing "
                "food.csv, food_nutrient.csv, nutrient.csv. "
                "If omitted, command auto-detects these files from project folders."
            ),
        )
        parser.add_argument(
            "--source",
            default="USDA",
            help="Source name persisted to FoodItem.source. Example: USDA/FSA/Kaggle.",
        )
        parser.add_argument(
            "--encoding",
            default="utf-8-sig",
            help="CSV file encoding. utf-8-sig handles BOM safely.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Optional max number of cleaned rows to import.",
        )
        parser.add_argument(
            "--min-records",
            type=int,
            default=100,
            help="Warn if imported rows are fewer than this threshold.",
        )
        parser.add_argument(
            "--truncate",
            action="store_true",
            help="Delete existing FoodItem rows before import.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and validate rows without writing to database.",
        )

    def handle(self, *args, **options):
        csv_path_option = options.get("csv_path")
        usda_dir_option = options.get("usda_dir")

        if usda_dir_option:
            usda_dir = Path(options["usda_dir"]).expanduser().resolve()
            if not usda_dir.exists() or not usda_dir.is_dir():
                raise CommandError(f"USDA directory not found: {usda_dir}")
            parsed_rows, skipped = self._parse_usda_directory(
                usda_dir=usda_dir,
                encoding=options["encoding"],
                limit=options["limit"],
            )
        elif csv_path_option:
            csv_path = Path(csv_path_option).expanduser().resolve()
            if not csv_path.exists() or not csv_path.is_file():
                raise CommandError(f"CSV file not found: {csv_path}")
            parsed_rows, skipped = self._parse_csv(
                csv_path=csv_path,
                encoding=options["encoding"],
                limit=options["limit"],
            )
        else:
            auto_dir = self._resolve_default_usda_dir()
            if auto_dir is None:
                raise CommandError(
                    "No input files found. Provide --usda-dir or --csv-path, "
                    "or place food.csv, food_nutrient.csv, nutrient.csv in project root/data."
                )
            self.stdout.write(
                self.style.NOTICE(f"Auto-detected USDA CSV directory: {auto_dir}")
            )
            parsed_rows, skipped = self._parse_usda_directory(
                usda_dir=auto_dir,
                encoding=options["encoding"],
                limit=options["limit"],
            )

        self.stdout.write(self.style.NOTICE(f"Parsed rows: {len(parsed_rows)}"))
        self.stdout.write(self.style.WARNING(f"Skipped rows: {skipped}"))

        if len(parsed_rows) < options["min_records"]:
            self.stdout.write(
                self.style.WARNING(
                    f"Imported rows below recommended minimum ({options['min_records']})."
                )
            )

        if options["dry_run"]:
            self.stdout.write(self.style.SUCCESS("Dry-run complete. No data written."))
            self._print_preview(parsed_rows)
            return

        created, updated = self._upsert_rows(
            parsed_rows=parsed_rows,
            source=options["source"],
            truncate=options["truncate"],
        )
        self.stdout.write(self.style.SUCCESS(f"Created: {created}, Updated: {updated}"))

    def _parse_csv(
        self,
        csv_path: Path,
        encoding: str,
        limit: int | None,
    ) -> tuple[list[ParsedFoodRow], int]:
        parsed: list[ParsedFoodRow] = []
        skipped = 0
        seen_names: set[str] = set()

        with csv_path.open("r", encoding=encoding, newline="") as fp:
            reader = csv.DictReader(fp)
            if not reader.fieldnames:
                raise CommandError("CSV has no header row.")

            field_lookup = self._build_field_lookup(reader.fieldnames)
            for row in reader:
                cleaned = self._clean_row(row, field_lookup)
                if cleaned is None:
                    skipped += 1
                    continue

                dedup_key = cleaned.name.casefold()
                if dedup_key in seen_names:
                    skipped += 1
                    continue

                parsed.append(cleaned)
                seen_names.add(dedup_key)
                if limit and len(parsed) >= limit:
                    break

        return parsed, skipped

    def _parse_usda_directory(
        self,
        usda_dir: Path,
        encoding: str,
        limit: int | None,
    ) -> tuple[list[ParsedFoodRow], int]:
        food_path = self._find_file(usda_dir, USDA_FILE_ALIASES["food"])
        food_nutrient_path = self._find_file(usda_dir, USDA_FILE_ALIASES["food_nutrient"])
        nutrient_path = self._find_file(usda_dir, USDA_FILE_ALIASES["nutrient"])

        if not (food_path and food_nutrient_path and nutrient_path):
            raise CommandError(
                "Missing USDA files. Expected food.csv, food_nutrient.csv, nutrient.csv."
            )

        nutrient_to_kind = self._build_usda_nutrient_mapping(nutrient_path, encoding)
        if not nutrient_to_kind:
            raise CommandError("Unable to map USDA nutrient IDs to macro fields.")

        macro_values_by_fdc: dict[str, dict[str, Decimal]] = {}
        with food_nutrient_path.open("r", encoding=encoding, newline="") as fp:
            reader = csv.DictReader(fp)
            if not reader.fieldnames:
                raise CommandError("USDA food_nutrient.csv has no header row.")
            field_lookup = self._build_field_lookup(reader.fieldnames)

            for row in reader:
                fdc_id = self._read_by_aliases(
                    row,
                    field_lookup,
                    ("fdc_id", "fdcid", "food_id"),
                )
                nutrient_id = self._read_by_aliases(
                    row,
                    field_lookup,
                    ("nutrient_id", "nutrientid", "nutrient"),
                )
                amount_raw = self._read_by_aliases(row, field_lookup, ("amount", "value"))

                if not fdc_id or not nutrient_id:
                    continue
                kind = nutrient_to_kind.get(nutrient_id.strip())
                if not kind:
                    continue
                amount = self._to_decimal(amount_raw)
                if amount is None or amount < Decimal("0"):
                    continue

                slot = macro_values_by_fdc.setdefault(fdc_id.strip(), {})
                # Keep first non-zero value per nutrient to avoid noisy duplicates.
                if kind not in slot or (slot[kind] == Decimal("0") and amount > Decimal("0")):
                    slot[kind] = amount

        parsed: list[ParsedFoodRow] = []
        skipped = 0
        seen_names: set[str] = set()
        with food_path.open("r", encoding=encoding, newline="") as fp:
            reader = csv.DictReader(fp)
            if not reader.fieldnames:
                raise CommandError("USDA food.csv has no header row.")
            field_lookup = self._build_field_lookup(reader.fieldnames)

            for row in reader:
                fdc_id = self._read_by_aliases(
                    row,
                    field_lookup,
                    ("fdc_id", "fdcid", "id", "food_id"),
                )
                name_raw = self._read_by_aliases(
                    row,
                    field_lookup,
                    ("description", "food_description", "name", "long_desc"),
                )

                if not fdc_id or not name_raw:
                    skipped += 1
                    continue

                macros = macro_values_by_fdc.get(fdc_id.strip())
                if not macros:
                    skipped += 1
                    continue
                if any(key not in macros for key in ("kcal", "protein", "carbs", "fat")):
                    skipped += 1
                    continue

                name = self._normalize_name(name_raw)
                if not name:
                    skipped += 1
                    continue

                dedup_key = name.casefold()
                if dedup_key in seen_names:
                    skipped += 1
                    continue
                seen_names.add(dedup_key)

                parsed.append(
                    ParsedFoodRow(
                        name=name,
                        per_100g_kcal=macros["kcal"],
                        per_100g_protein=macros["protein"],
                        per_100g_carbs=macros["carbs"],
                        per_100g_fat=macros["fat"],
                        diet_type=self._infer_diet_type(
                            name=name,
                            protein=macros["protein"],
                            carbs=macros["carbs"],
                            fat=macros["fat"],
                        ),
                    )
                )

                if limit and len(parsed) >= limit:
                    break

        return parsed, skipped

    def _build_usda_nutrient_mapping(self, nutrient_path: Path, encoding: str) -> dict[str, str]:
        mapping: dict[str, str] = {}
        with nutrient_path.open("r", encoding=encoding, newline="") as fp:
            reader = csv.DictReader(fp)
            if not reader.fieldnames:
                raise CommandError("USDA nutrient.csv has no header row.")
            field_lookup = self._build_field_lookup(reader.fieldnames)

            for row in reader:
                nutrient_id = self._read_by_aliases(row, field_lookup, ("id", "nutrient_id"))
                nutrient_number = self._read_by_aliases(
                    row,
                    field_lookup,
                    ("number", "nutrient_nbr", "nutrient_number"),
                )
                nutrient_name = self._read_by_aliases(
                    row,
                    field_lookup,
                    ("name", "nutrient_name"),
                )
                unit_name = self._read_by_aliases(row, field_lookup, ("unit_name", "unit"))

                if not nutrient_id:
                    continue

                kind = self._classify_usda_nutrient(
                    nutrient_number=nutrient_number,
                    nutrient_name=nutrient_name,
                    unit_name=unit_name,
                )
                if kind:
                    mapping[nutrient_id.strip()] = kind

        return mapping

    @staticmethod
    def _classify_usda_nutrient(
        nutrient_number: str | None,
        nutrient_name: str | None,
        unit_name: str | None,
    ) -> str | None:
        number = (nutrient_number or "").strip()
        if number in USDA_NUTRIENT_NUMBER_MAP:
            return USDA_NUTRIENT_NUMBER_MAP[number]

        name = (nutrient_name or "").strip().lower()
        unit = (unit_name or "").strip().lower()

        if "protein" in name:
            return "protein"
        if "carbohydrate" in name:
            return "carbs"
        if "lipid" in name or "total fat" in name or name == "fat":
            return "fat"
        if "energy" in name and "kcal" in unit:
            return "kcal"
        return None

    @staticmethod
    def _find_file(directory: Path, candidates: tuple[str, ...]) -> Path | None:
        for filename in candidates:
            candidate = directory / filename
            if candidate.exists() and candidate.is_file():
                return candidate
        return None

    def _resolve_default_usda_dir(self) -> Path | None:
        cwd = Path.cwd().resolve()
        base_dir = Path(settings.BASE_DIR).resolve()
        candidate_dirs = (
            cwd,
            cwd / "data",
            cwd / "dataset",
            cwd / "datasets",
            base_dir,
            base_dir / "data",
            base_dir / "dataset",
            base_dir / "datasets",
        )

        seen: set[Path] = set()
        for candidate in candidate_dirs:
            if candidate in seen:
                continue
            seen.add(candidate)
            if not candidate.exists() or not candidate.is_dir():
                continue
            if self._find_file(candidate, USDA_FILE_ALIASES["food"]) is None:
                continue
            if self._find_file(candidate, USDA_FILE_ALIASES["food_nutrient"]) is None:
                continue
            if self._find_file(candidate, USDA_FILE_ALIASES["nutrient"]) is None:
                continue
            return candidate

        return None

    def _clean_row(self, row: dict, field_lookup: dict[str, str]) -> ParsedFoodRow | None:
        raw_name = self._read_value(row, field_lookup, *COLUMN_ALIASES["name"])
        kcal = self._to_decimal(self._read_value(row, field_lookup, *COLUMN_ALIASES["kcal"]))
        protein = self._to_decimal(self._read_value(row, field_lookup, *COLUMN_ALIASES["protein"]))
        carbs = self._to_decimal(self._read_value(row, field_lookup, *COLUMN_ALIASES["carbs"]))
        fat = self._to_decimal(self._read_value(row, field_lookup, *COLUMN_ALIASES["fat"]))

        if not raw_name:
            return None
        if any(v is None for v in [kcal, protein, carbs, fat]):
            return None
        if any(v < Decimal("0") for v in [kcal, protein, carbs, fat]):
            return None

        name = self._normalize_name(raw_name)
        if not name:
            return None

        return ParsedFoodRow(
            name=name,
            per_100g_kcal=kcal,
            per_100g_protein=protein,
            per_100g_carbs=carbs,
            per_100g_fat=fat,
            diet_type=self._infer_diet_type(
                name=name,
                protein=protein,
                carbs=carbs,
                fat=fat,
            ),
        )

    def _upsert_rows(self, parsed_rows: list[ParsedFoodRow], source: str, truncate: bool) -> tuple[int, int]:
        created = 0
        updated = 0
        with transaction.atomic():
            if truncate:
                FoodItem.objects.all().delete()

            for row in parsed_rows:
                _, is_created = FoodItem.objects.update_or_create(
                    name=row.name,
                    defaults={
                        "diet_type": row.diet_type,
                        "per_100g_kcal": row.per_100g_kcal,
                        "per_100g_protein": row.per_100g_protein,
                        "per_100g_carbs": row.per_100g_carbs,
                        "per_100g_fat": row.per_100g_fat,
                        "source": source,
                    },
                )
                if is_created:
                    created += 1
                else:
                    updated += 1

        return created, updated

    def _print_preview(self, parsed_rows: list[ParsedFoodRow]) -> None:
        preview_size = min(5, len(parsed_rows))
        if preview_size == 0:
            self.stdout.write(self.style.WARNING("No valid rows to preview."))
            return

        self.stdout.write(self.style.NOTICE("Preview (first 5 cleaned rows):"))
        for row in parsed_rows[:preview_size]:
            self.stdout.write(
                f"- {row.name}: kcal={row.per_100g_kcal}, P={row.per_100g_protein}, "
                f"C={row.per_100g_carbs}, F={row.per_100g_fat}, diet={row.diet_type}"
            )

    @staticmethod
    def _normalize_key(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", value.strip().lower())

    def _build_field_lookup(self, fieldnames: list[str]) -> dict[str, str]:
        return {self._normalize_key(column): column for column in fieldnames}

    def _read_by_aliases(
        self,
        row: dict,
        field_lookup: dict[str, str],
        aliases: tuple[str, ...],
    ) -> str | None:
        return self._read_value(row, field_lookup, *aliases)

    def _read_value(
        self,
        row: dict,
        field_lookup: dict[str, str],
        *aliases: str,
    ) -> str | None:
        for alias in aliases:
            column = field_lookup.get(self._normalize_key(alias))
            if column is not None:
                value = row.get(column)
                return value if value is not None else None
        return None

    @staticmethod
    def _to_decimal(raw_value: str | None) -> Decimal | None:
        if raw_value is None:
            return None
        normalized = raw_value.strip().replace(",", ".")
        normalized = re.sub(r"[^0-9.\-]+", "", normalized)
        if normalized in {"", "-", ".", "-."}:
            return None
        try:
            return Decimal(normalized).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            return None

    @staticmethod
    def _normalize_name(name: str) -> str:
        collapsed = re.sub(r"\s+", " ", name).strip()
        return collapsed.title()

    @staticmethod
    def _infer_diet_type(name: str, protein: Decimal, carbs: Decimal, fat: Decimal) -> str:
        n = name.casefold()

        vegan_keywords = (
            "tofu",
            "soy",
            "lentil",
            "bean",
            "chickpea",
            "quinoa",
            "broccoli",
            "spinach",
            "oat",
            "almond",
            "apple",
            "banana",
            "rice",
            "potato",
        )
        vegetarian_keywords = ("milk", "cheese", "yogurt", "egg")
        animal_keywords = (
            "beef",
            "pork",
            "chicken",
            "turkey",
            "fish",
            "salmon",
            "shrimp",
            "lamb",
            "bacon",
        )

        if any(k in n for k in vegan_keywords):
            return FoodItem.DietType.VEGAN
        if any(k in n for k in vegetarian_keywords):
            return FoodItem.DietType.VEGETARIAN
        if protein >= Decimal("20"):
            return FoodItem.DietType.HIGH_PROTEIN
        if carbs <= Decimal("10") and fat >= Decimal("10"):
            return FoodItem.DietType.KETO
        if any(k in n for k in animal_keywords):
            return FoodItem.DietType.OMNIVORE
        return FoodItem.DietType.OTHER
