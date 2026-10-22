from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from raceproof.sample.models import Order, Product

Checkpoint = Callable[[str, str], None]


def purchase_inventory(
    session: Session,
    product_id: int,
    actor_id: str,
    checkpoint: Checkpoint,
) -> bool:
    """Deliberately vulnerable read, check, then absolute write operation."""
    product = session.scalar(select(Product).where(Product.id == product_id))
    if product is None or product.available_stock <= 0:
        return False

    observed_stock = product.available_stock
    checkpoint(actor_id, "after_read")
    session.add(Order(product_id=product_id, actor_id=actor_id))
    product.available_stock = observed_stock - 1
    session.flush()
    checkpoint(actor_id, "after_write")
    return True
