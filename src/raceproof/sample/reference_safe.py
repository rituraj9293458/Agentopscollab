from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import update
from sqlalchemy.orm import Session

from raceproof.sample.models import Order, Product


def purchase_inventory_reference(
    session: Session,
    product_id: int,
    actor_id: str,
    checkpoint: Callable[[str, str], None],
) -> bool:
    """Reference implementation for harness tests, never represented as model output."""
    checkpoint(actor_id, "before_claim")
    claim = session.execute(
        update(Product)
        .where(Product.id == product_id, Product.available_stock > 0)
        .values(available_stock=Product.available_stock - 1)
    )
    if claim.rowcount != 1:
        return False
    session.add(Order(product_id=product_id, actor_id=actor_id))
    session.flush()
    checkpoint(actor_id, "after_claim")
    return True
