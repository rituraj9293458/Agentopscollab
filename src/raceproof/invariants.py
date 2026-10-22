from __future__ import annotations

from sqlalchemy import Engine, text

from raceproof.contracts import InvariantResult

INVENTORY_INVARIANT_SQL = """
SELECT
  p.available_stock AS final_stock,
  count(o.id) AS successful_orders
FROM products p
LEFT JOIN orders o ON o.product_id = p.id
WHERE p.id = 1
GROUP BY p.available_stock
""".strip()


def check_inventory(engine: Engine, initial_stock: int = 1) -> InvariantResult:
    with engine.connect() as connection:
        row = connection.execute(text(INVENTORY_INVARIANT_SQL)).mappings().one()
    orders = int(row["successful_orders"])
    final_stock = int(row["final_stock"])
    passed = orders <= initial_stock and final_stock == initial_stock - orders
    return InvariantResult(
        passed=passed,
        initial_stock=initial_stock,
        successful_orders=orders,
        final_stock=final_stock,
        explanation="Executable SQL oracle; no model judgment is used.",
    )
