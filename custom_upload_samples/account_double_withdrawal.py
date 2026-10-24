"""Intentionally vulnerable sample for RaceProof static analysis.

Issue: check-then-act race during concurrent withdrawals.
This file is demonstration code and must not be used in production.
"""

from __future__ import annotations

from sqlalchemy import Integer, Numeric, String, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "sample_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner: Mapped[str] = mapped_column(String(100))
    balance: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)


class Withdrawal(Base):
    __tablename__ = "sample_withdrawals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)


def withdraw_funds(session: Session, account_id: int, amount: float) -> bool:
    """Withdraw using a vulnerable balance check followed by an insert.

    Concurrent example when the balance starts at 100:
    Actor A checks that a withdrawal of 80 is affordable.
    Actor B independently checks that a withdrawal of 80 is affordable.
    Both create withdrawal records, producing 160 in withdrawals against 100.
    """
    account = session.scalar(select(Account).where(Account.id == account_id))
    if account is None or account.balance < amount:
        return False

    session.add(Withdrawal(account_id=account_id, amount=amount))
    account.balance = account.balance - amount
    session.flush()
    return True
