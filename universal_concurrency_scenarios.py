"""RaceProof upload showcase with several intentionally vulnerable DB patterns.

This file is for static-analysis and concurrency-lab testing only.
Do not use any operation in production.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, Numeric, String, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "showcase_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner: Mapped[str] = mapped_column(String(100))
    balance: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)


class Withdrawal(Base):
    __tablename__ = "showcase_withdrawals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("showcase_accounts.id"))
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)


class Product(Base):
    __tablename__ = "showcase_products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    stock: Mapped[int] = mapped_column(Integer, nullable=False)


class Resource(Base):
    __tablename__ = "showcase_resources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))


class Booking(Base):
    __tablename__ = "showcase_bookings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("showcase_resources.id"))


class Claim(Base):
    __tablename__ = "showcase_claims"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    resource_id: Mapped[int] = mapped_column(Integer, nullable=False)


def withdraw_funds(session: Session, account_id: int, amount: float) -> bool:
    """Check-then-act withdrawal that can allow two excessive withdrawals."""
    account = session.scalar(select(Account).where(Account.id == account_id))
    if account is None or account.balance < amount:
        return False

    session.add(Withdrawal(account_id=account_id, amount=amount))
    account.balance = account.balance - amount
    session.flush()
    return True


def sell_product(session: Session, product_id: int, quantity: int) -> bool:
    """Read-modify-write inventory operation that can lose an update."""
    product = session.scalar(select(Product).where(Product.id == product_id))
    if product is None or product.stock < quantity:
        return False

    product.stock = product.stock - quantity
    session.flush()
    return True


def reserve_resource(session: Session, resource_id: int) -> bool:
    """Existence check followed by insert that can create duplicate bookings."""
    existing = session.scalar(
        select(Booking).where(Booking.resource_id == resource_id)
    )
    if existing is not None:
        return False

    session.add(Booking(resource_id=resource_id))
    session.flush()
    return True


class DjangoStyleAccountService:
    """Django-shaped example parsed statically without importing Django."""

    def withdraw(self, account_id: int, amount: float) -> bool:
        account = DjangoAccount.objects.get(id=account_id)  # type: ignore[name-defined]
        if account.balance < amount:
            return False
        account.balance -= amount
        account.save()
        return True


def raw_sql_reserve(cursor, resource_id: int) -> bool:
    """Raw SQL SELECT followed by UPDATE without a lock."""
    cursor.execute(
        "SELECT available FROM resources WHERE id = %s",
        (resource_id,),
    )
    row = cursor.fetchone()
    if not row or not row[0]:
        return False
    cursor.execute(
        "UPDATE resources SET available = false WHERE id = %s",
        (resource_id,),
    )
    return True


async def async_claim_resource(session, resource_id: int) -> bool:
    """Async SQLAlchemy-shaped check followed by insert."""
    existing = await session.scalar(
        select(Claim).where(Claim.resource_id == resource_id)
    )
    if existing is not None:
        return False
    session.add(Claim(resource_id=resource_id))
    await session.flush()
    return True
