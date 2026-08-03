from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(120), default="")
    # owner = full control; partner = full day-to-day (married/shared);
    # member = edit money, not people; viewer = look only
    role: Mapped[str] = mapped_column(String(32), default="owner")
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Household(Base):
    __tablename__ = "households"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), default="My Household")
    starting_balance: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    items: Mapped[list["BudgetItem"]] = relationship(back_populates="household")
    names: Mapped[list["ItemName"]] = relationship(back_populates="household")
    goals: Mapped[list["Goal"]] = relationship(back_populates="household")
    debts: Mapped[list["Debt"]] = relationship(back_populates="household")
    investments: Mapped[list["Investment"]] = relationship(back_populates="household")
    jobs: Mapped[list["JobPay"]] = relationship(back_populates="household")


class ItemName(Base):
    """Retained names for the bill/estimate dropdown (custom + seeded)."""

    __tablename__ = "item_names"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    household_id: Mapped[int] = mapped_column(ForeignKey("households.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(32), default="general")  # bill|estimate|income|general
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    household: Mapped[Household] = relationship(back_populates="names")


class BudgetItem(Base):
    """
    Calendar / budget line.
    item_type: bill | estimate | paycheck | actual
    amount: positive number; direction is income vs expense via is_income
    """

    __tablename__ = "budget_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    household_id: Mapped[int] = mapped_column(ForeignKey("households.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    item_type: Mapped[str] = mapped_column(String(32), index=True)  # bill|estimate|paycheck|actual
    amount: Mapped[float] = mapped_column(Float)
    is_income: Mapped[bool] = mapped_column(Boolean, default=False)
    due_date: Mapped[date] = mapped_column(Date, index=True)
    frequency: Mapped[str] = mapped_column(String(32), default="once")  # once|weekly|biweekly|monthly
    notes: Mapped[str] = mapped_column(Text, default="")
    is_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    category: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    household: Mapped[Household] = relationship(back_populates="items")


class Goal(Base):
    """Savings target: house, vacation, emergency fund, etc."""

    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    household_id: Mapped[int] = mapped_column(ForeignKey("households.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    target_amount: Mapped[float] = mapped_column(Float)
    current_amount: Mapped[float] = mapped_column(Float, default=0.0)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    monthly_contribution: Mapped[float] = mapped_column(Float, default=0.0)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    household: Mapped[Household] = relationship(back_populates="goals")


class Debt(Base):
    """Debt account for paydown planning (cards, loans)."""

    __tablename__ = "debts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    household_id: Mapped[int] = mapped_column(ForeignKey("households.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    balance: Mapped[float] = mapped_column(Float)
    apr: Mapped[float] = mapped_column(Float, default=0.0)  # annual % e.g. 22.9
    min_payment: Mapped[float] = mapped_column(Float, default=0.0)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    household: Mapped[Household] = relationship(back_populates="debts")


class JobPay(Base):
    """Saved job / pay profile from pay stubs or manual entry."""

    __tablename__ = "job_pay"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    household_id: Mapped[int] = mapped_column(ForeignKey("households.id"), index=True)
    employer: Mapped[str] = mapped_column(String(120), default="")
    employee_label: Mapped[str] = mapped_column(String(120), default="")  # e.g. Mom
    frequency: Mapped[str] = mapped_column(String(32), default="biweekly")
    gross_pay: Mapped[float] = mapped_column(Float, default=0.0)
    net_pay: Mapped[float] = mapped_column(Float, default=0.0)
    last_pay_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    monthly_net_estimate: Mapped[float] = mapped_column(Float, default=0.0)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    household: Mapped[Household] = relationship(back_populates="jobs")


class Investment(Base):
    """
    Simple investment bucket — not a brokerage feed.
    Examples: 401k, IRA, brokerage, crypto, kids 529, HSA.
    User updates current_value when they check the app.
    """

    __tablename__ = "investments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    household_id: Mapped[int] = mapped_column(ForeignKey("households.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    account_type: Mapped[str] = mapped_column(String(64), default="other")
    # 401k | ira | brokerage | crypto | 529 | hsa | savings | other
    current_value: Mapped[float] = mapped_column(Float, default=0.0)
    cost_basis: Mapped[float] = mapped_column(Float, default=0.0)  # optional "what I put in"
    monthly_contribution: Mapped[float] = mapped_column(Float, default=0.0)
    notes: Mapped[str] = mapped_column(Text, default="")
    last_updated: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    household: Mapped[Household] = relationship(back_populates="investments")


class SessionToken(Base):
    __tablename__ = "sessions"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # Idle timeout: updated on each authenticated request
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
