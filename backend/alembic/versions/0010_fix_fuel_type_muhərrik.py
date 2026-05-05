"""fix: null spec columns where the property label was stored as the value

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-05

The detail scraper used `span` as a CSS fallback when selecting spec values.
Because `querySelector` returns the first DOM match across alternatives, and
the name <span> appears before the value <span>, the property label
("Mühərrik", "Rəng", "Ban növü", …) was stored as the value across many
columns whenever the primary `.product-properties__i-value` selector failed.

Fix: null out all affected rows for each spec-derived column and flag them
for re-scrape via `needs_detail_refresh`. The next Details Update sweep will
repopulate them correctly using the fixed JS selector.
"""
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


# (column, set of label values that indicate corruption)
CORRUPTED = [
    ("color",        ["Rəng", "Color", "Цвет"]),
    ("body_type",    ["Ban növü", "Body type", "Кузов", "Növü"]),
    ("transmission", ["Sürətlər qutusu", "Transmission", "Коробка передач", "Sürət"]),
    ("drive_type",   ["Ötürücü", "Drive", "Привод"]),
    ("vin",          ["Vin", "VIN", "Vin-kod"]),
    ("condition",    ["Vəziyyəti", "Condition", "Состояние"]),
    ("market_for",   ["Hansı bazar üçün yığılıb", "Market", "Рынок"]),
    ("city",         ["Şəhər", "City", "Город", "Şehər"]),
    ("fuel_type",    ["Yanacaq", "Fuel type", "Mühərrik", "Mühərrik növü"]),
]


def upgrade() -> None:
    for column, labels in CORRUPTED:
        placeholders = ", ".join(f"'{lab}'" for lab in labels)
        op.execute(
            f"UPDATE vehicles "
            f"SET {column} = NULL, needs_detail_refresh = TRUE "
            f"WHERE {column} IN ({placeholders})"
        )


def downgrade() -> None:
    pass
