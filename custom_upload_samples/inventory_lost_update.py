"""Intentionally vulnerable sample for RaceProof static analysis.

Issue: lost update during concurrent inventory sales.
This file is demonstration code and must not be used in production.
"""

from __future__ import annotations

from sqlalchemy import Integer, String, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "sample_products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    stock: Mapped[int] = mapped_column(Integer, nullable=False)


def sell_product(session: Session, product_id: int, quantity: int) -> bool:
    """Sell stock using a vulnerable read, calculate, write sequence.

    Concurrent example when stock starts at 10:
    Actor A reads 10 and calculates 10 - 7 = 3.
    Actor B reads 10 and calculates 10 - 6 = 4.
    Both updates succeed, even though 13 units were sold from a stock of 10.
    The final value becomes either 3 or 4 instead of rejecting one sale.
    """
    product = session.scalar(select(Product).where(Product.id == product_id))
    if product is None or product.stock < quantity:
        return False

    product.stock = product.stock - quantity
    session.flush()
    return True

