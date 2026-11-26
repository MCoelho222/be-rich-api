"""Read models: balances, summaries, projections and card bills (specs/api.md §13).

Nothing here is stored. Each request loads the stored rows and computes the
projected occurrences for its range, converts every amount once, then
aggregates in Python. Households are small, so this stays cheap.
"""

import base64
import json
import uuid
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from app.api.errors import ApiError, validation_error
from app.domain.balances import Movement, account_balance
from app.domain.business_days import next_business_day
from app.domain.credit import CardCycle, next_statement
from app.domain.dates import add_months, first_of_month, month_index
from app.domain.enums import CardType, Currency, EntryType, OccurrenceStatus, PaymentMethod
from app.domain.fx import rate_date_for
from app.domain.money import round_money
from app.domain.recurrence import projected_occurrences
from app.models import Account, Card, Category, Expense, Income, Recurrence, User
from app.services.calendar import load_holidays
from app.services.fx import historical_rate, latest_rate
from app.services.fx_provider import RateProvider
from app.services.investments import InvestmentBook
from app.services.recurrences import OccurrenceCalculator, registered_rows, rule_of

MAX_RANGE_DAYS = 1096  # 3 years
MAX_PROJECTION_MONTHS = 36
ZERO = Decimal("0")
SHARE_PLACES = Decimal("0.0001")


# --- Inputs ------------------------------------------------------------------------


@dataclass(frozen=True)
class Filters:
    account_id: uuid.UUID | None = None
    member_id: uuid.UUID | None = None


def check_range(start: date, end: date, max_days: int = MAX_RANGE_DAYS) -> None:
    if end < start:
        raise validation_error({"to": ["Must be on or after from"]})
    if (end - start).days + 1 > max_days:
        raise validation_error({"to": ["The range can be at most 3 years"]})


def check_filters(db: Session, household_id: uuid.UUID, filters: Filters) -> None:
    """Unknown or foreign ids are 404 (api.md §1.2). A former member is accepted when
    this household still references them."""
    if filters.account_id is not None:
        account = db.get(Account, filters.account_id)
        if account is None or account.household_id != household_id:
            raise ApiError(404, "NOT_FOUND", "Account not found.")
    if filters.member_id is not None:
        user = db.get(User, filters.member_id)
        if user is None:
            raise ApiError(404, "NOT_FOUND", "Member not found.")
        if user.household_id != household_id:
            referenced = db.scalar(
                select(
                    exists().where(Expense.household_id == household_id, Expense.spender_id == user.id)
                    | exists().where(Income.household_id == household_id, Income.receiver_id == user.id)
                    | exists().where(Recurrence.household_id == household_id, Recurrence.person_id == user.id)
                )
            )
            if not referenced:
                raise ApiError(404, "NOT_FOUND", "Member not found.")


# --- Currency conversion -----------------------------------------------------------


class Converter:
    """Converts amounts with the rules of schemas §16.3 and records what the response
    must disclose: the oldest rate used and the amounts that couldn't be converted."""

    def __init__(self, db: Session, provider: RateProvider, target: Currency, today: date, now: datetime) -> None:
        self.db, self.provider, self.target, self.today, self.now = db, provider, target, today, now
        self._rates: dict[tuple[Currency, Currency, date | None], tuple[Decimal, date | None] | None] = {}
        self.rates_as_of: date | None = None
        self.unconverted: dict[Currency, Decimal] = defaultdict(lambda: ZERO)

    def rate(self, base: Currency, quote: Currency, on: date | None) -> Decimal | None:
        key = (base, quote, on)
        if key not in self._rates:
            if on is None:
                self._rates[key] = latest_rate(self.db, base, quote)
            else:
                self._rates[key] = historical_rate(self.db, self.provider, base, quote, on, self.now)
        found = self._rates[key]
        if found is None:
            return None
        rate, rate_date = found
        if rate_date is not None and (self.rates_as_of is None or rate_date < self.rates_as_of):
            self.rates_as_of = rate_date
        return rate

    def convert(
        self, amount: Decimal, currency: Currency, payment_date: date | None,
        to: Currency | None = None, record: bool = True,
    ) -> Decimal | None:  # fmt: skip
        """`payment_date` None means a current value (latest rate). Returns None, and
        records the amount as unconverted, when no rate was ever cached."""
        to = to or self.target
        if currency == to:
            return amount
        on = None if payment_date is None else rate_date_for(payment_date, self.today)
        rate = self.rate(currency, to, on)
        if rate is None:
            if record:
                self.unconverted[currency] += amount
            return None
        return amount * rate

    def meta(self) -> dict:
        return {
            "currency": self.target,
            "rates_as_of": self.rates_as_of,
            "unconverted": [
                {"currency": c, "amount": round_money(a)} for c, a in sorted(self.unconverted.items()) if a
            ],
        }


# --- Lines: stored rows and projected occurrences ----------------------------------


@dataclass
class Line:
    """One stored row or one projected occurrence, reduced to what aggregation needs."""

    type: EntryType
    projected: bool
    payment_date: date
    amount: Decimal
    currency: Currency
    fixed: bool  # registered from a recurrence, or projected
    category_id: uuid.UUID
    account_id: uuid.UUID
    card_id: uuid.UUID | None
    person_id: uuid.UUID
    payment_method: PaymentMethod
    row: Expense | Income | None = None
    recurrence: Recurrence | None = None
    occurrence_date: date | None = None
    occurrence_status: OccurrenceStatus | None = None
    converted: Decimal | None = field(default=None)


def _types(type_: EntryType | None) -> tuple[EntryType, ...]:
    return (type_,) if type_ is not None else (EntryType.EXPENSE, EntryType.INCOME)


def stored_lines(
    db: Session, household_id: uuid.UUID, start: date, end: date, filters: Filters,
    type_: EntryType | None = None, card_id: uuid.UUID | None = None,
) -> list[Line]:  # fmt: skip
    lines: list[Line] = []
    for entry_type in _types(type_):
        is_expense = entry_type is EntryType.EXPENSE
        model, person = (Expense, Expense.spender_id) if is_expense else (Income, Income.receiver_id)
        stmt = select(model).where(
            model.household_id == household_id, model.payment_date >= start, model.payment_date <= end
        )
        if filters.account_id is not None:
            stmt = stmt.where(model.account_id == filters.account_id)
        if filters.member_id is not None:
            stmt = stmt.where(person == filters.member_id)
        if card_id is not None:
            if not is_expense:
                continue
            stmt = stmt.where(Expense.card_id == card_id)
        for row in db.scalars(stmt):
            lines.append(
                Line(
                    type=entry_type, projected=False, payment_date=row.payment_date, amount=row.amount,
                    currency=row.currency, fixed=row.recurrence_id is not None, category_id=row.category_id,
                    account_id=row.account_id, card_id=row.card_id if is_expense else None,
                    person_id=row.spender_id if is_expense else row.receiver_id,
                    payment_method=row.payment_method, row=row,
                )  # fmt: skip
            )
    return lines


def projected_lines(
    db: Session, household_id: uuid.UUID, start: date, end: date, today: date, filters: Filters,
    type_: EntryType | None = None, card_id: uuid.UUID | None = None,
) -> list[Line]:  # fmt: skip
    """Valid, unregistered, non-overdue occurrences paid within [start, end] (schemas §13.1)."""
    if end < today:
        return []  # projections only reach today and later
    stmt = select(Recurrence).where(
        Recurrence.household_id == household_id,
        Recurrence.is_active.is_(True),
        Recurrence.type.in_(_types(type_)),
        Recurrence.start_date <= end,
        or_(Recurrence.end_date.is_(None), Recurrence.end_date >= first_of_month(today)),
    )
    if filters.account_id is not None:
        stmt = stmt.where(Recurrence.account_id == filters.account_id)
    if filters.member_id is not None:
        stmt = stmt.where(Recurrence.person_id == filters.member_id)
    if card_id is not None:
        stmt = stmt.where(Recurrence.card_id == card_id)
    lines: list[Line] = []
    for rec in db.scalars(stmt):
        calc = OccurrenceCalculator(db, rec, today.year, end.year)
        registered = set(registered_rows(db, rec))
        for occ in projected_occurrences(rule_of(rec), registered, today, start, end, calc.payment_date):
            lines.append(
                Line(
                    type=rec.type, projected=True, payment_date=occ.payment_date, amount=rec.amount,
                    currency=rec.currency, fixed=True, category_id=rec.category_id, account_id=rec.account_id,
                    card_id=rec.card_id, person_id=rec.person_id, payment_method=rec.payment_method,
                    recurrence=rec, occurrence_date=occ.occurrence_date, occurrence_status=occ.status,
                )  # fmt: skip
            )
    return lines


def lines_for(
    db: Session, household_id: uuid.UUID, start: date, end: date, today: date, filters: Filters,
    conv: Converter, type_: EntryType | None = None,
) -> list[Line]:  # fmt: skip
    """Stored rows plus projected occurrences, each converted once."""
    lines = stored_lines(db, household_id, start, end, filters, type_)
    lines += projected_lines(db, household_id, start, end, today, filters, type_)
    for line in lines:
        line.converted = conv.convert(line.amount, line.currency, line.payment_date)
    return lines


def _sum(values: Iterable[Decimal | None]) -> Decimal:
    return sum((v for v in values if v is not None), ZERO)


def _share(part: Decimal, whole: Decimal) -> Decimal | None:
    return None if whole == 0 else (part / whole).quantize(SHARE_PLACES)


# --- Balances (§13.2) --------------------------------------------------------------


class BalanceBook:
    """Account movements up to `until`, loaded and converted once, so that balances
    on many dates (one per projection month) don't reload anything."""

    def __init__(
        self, db: Session, household_id: uuid.UUID, until: date, today: date, conv: Converter,
        account_id: uuid.UUID | None = None, include_archived: bool = True,
    ) -> None:  # fmt: skip
        self.today, self.conv = today, conv
        # Investments belong to no account, so a per-account view leaves them out (schemas §20.1).
        self.investments = InvestmentBook(db, household_id) if account_id is None else None
        stmt = select(Account).where(Account.household_id == household_id)
        if account_id is not None:
            stmt = stmt.where(Account.id == account_id)
        if not include_archived:
            stmt = stmt.where(Account.is_active.is_(True))
        self.accounts = list(db.scalars(stmt.order_by(Account.name)))
        by_id = {a.id: a for a in self.accounts}
        self.stored: dict[uuid.UUID, list[Movement]] = defaultdict(list)
        self.projected: dict[uuid.UUID, list[Movement]] = defaultdict(list)

        # Stored rows after each account's opening date, summed per day and currency.
        for entry_type, model in ((EntryType.EXPENSE, Expense), (EntryType.INCOME, Income)):
            rows = db.execute(
                select(model.account_id, model.currency, model.payment_date, func.sum(model.amount))
                .join(Account, Account.id == model.account_id)
                .where(
                    model.household_id == household_id,
                    model.account_id.in_(by_id),
                    model.payment_date > Account.opening_balance_date,
                    model.payment_date <= until,
                )
                .group_by(model.account_id, model.currency, model.payment_date)
            )
            for acc_id, currency, day, amount in rows:
                value = conv.convert(amount, currency, day, to=by_id[acc_id].currency)
                if value is not None:
                    self.stored[acc_id].append(Movement(entry_type, day, value))

        if until > today:
            for line in projected_lines(db, household_id, today, until, today, Filters(account_id=account_id)):
                account = by_id.get(line.account_id)
                if account is None or line.payment_date <= account.opening_balance_date:
                    continue
                value = conv.convert(line.amount, line.currency, line.payment_date, to=account.currency)
                if value is not None:
                    self.projected[account.id].append(Movement(line.type, line.payment_date, value))

    def balance(self, account: Account, at: date) -> Decimal | None:
        """balance(a, t) of schemas §14.1, in the account's currency."""
        value = account_balance(account.opening_balance, account.opening_balance_date, self.stored[account.id], at)
        if value is None or at <= self.today:
            return value
        return value + _sum(m.signed for m in self.projected[account.id] if m.payment_date <= at)

    def invested(self, day: date, record: bool = True) -> Decimal | None:
        """Investments counted in the balance on `day`, in the household currency (§20.1)."""
        if self.investments is None:
            return None
        return InvestmentBook.total(
            self.investments.held(day), lambda i: self.conv.convert(i.amount, i.currency, None, record=record)
        )

    def at(self, day: date, record: bool = True) -> tuple[Decimal | None, list[dict], Decimal | None]:
        """The total in the household currency, the per-account balances and the invested
        amount on `day`. `record` controls whether unconvertible balances are reported (once per request)."""
        accounts, total, any_open = [], ZERO, False
        for account in self.accounts:
            balance = self.balance(account, day)
            converted = None
            if balance is not None:
                any_open = True
                converted = self.conv.convert(balance, account.currency, None, record=record)
                total += converted or ZERO
            accounts.append(
                {
                    "account_id": account.id, "account_currency": account.currency,
                    "balance": None if balance is None else round_money(balance),
                    "converted": None if converted is None else round_money(converted),
                }  # fmt: skip
            )
        invested = self.invested(day, record)
        if invested is not None:
            total += invested
            any_open = True
            invested = round_money(invested)
        return (round_money(total) if any_open else None), accounts, invested


def balances(db: Session, household_id: uuid.UUID, day: date, today: date, conv: Converter,
             account_id: uuid.UUID | None, include_archived: bool) -> dict:  # fmt: skip
    book = BalanceBook(db, household_id, day, today, conv, account_id, include_archived)
    total, accounts, invested = book.at(day)
    return {
        "date": day, "projected": day > today, **conv.meta(), "total": total or ZERO, "accounts": accounts,
        "investments": invested or ZERO,
    }  # fmt: skip


# --- Summary (§13.3) ---------------------------------------------------------------


def _pair(lines: list[Line], realized_until: date) -> dict:
    return {
        "realized": round_money(_sum(ln.converted for ln in lines if not ln.projected and ln.payment_date <= realized_until)),
        "total": round_money(_sum(ln.converted for ln in lines)),
    }


def summary(db: Session, household_id: uuid.UUID, start: date, end: date, today: date,
            filters: Filters, conv: Converter) -> dict:  # fmt: skip
    lines = lines_for(db, household_id, start, end, today, filters, conv)
    realized_until = min(end, today)
    income = _pair([ln for ln in lines if ln.type is EntryType.INCOME], realized_until)
    expenses_lines = [ln for ln in lines if ln.type is EntryType.EXPENSE]
    expenses = _pair(expenses_lines, realized_until)
    fixed = round_money(_sum(ln.converted for ln in expenses_lines if ln.fixed))
    return {
        "from": start, "to": end, "includes_projection": end >= today, **conv.meta(),
        "income": income, "expenses": expenses,
        "net": {k: income[k] - expenses[k] for k in ("realized", "total")},
        "fixed_expenses": {"total": fixed, "share": _share(fixed, expenses["total"])},
    }  # fmt: skip


# --- Projection (§13.4) ------------------------------------------------------------


def projection(db: Session, household_id: uuid.UUID, start: date, end: date, today: date,
               filters: Filters, conv: Converter) -> dict:  # fmt: skip
    start = first_of_month(start)
    end = add_months(first_of_month(end), 1) - timedelta(days=1)
    if end < start:
        raise validation_error({"to": ["Must be on or after from"]})
    months_count = month_index(end) - month_index(start) + 1
    if months_count > MAX_PROJECTION_MONTHS:
        raise validation_error({"to": [f"The range can be at most {MAX_PROJECTION_MONTHS} months"]})

    lines = lines_for(db, household_id, start, end, today, filters, conv)
    by_month: dict[int, list[Line]] = defaultdict(list)
    for line in lines:
        by_month[month_index(line.payment_date)].append(line)

    book = BalanceBook(db, household_id, end, today, conv, filters.account_id)
    months, first_negative = [], None
    for k in range(months_count):
        month_start = add_months(start, k)
        month_end = add_months(month_start, 1) - timedelta(days=1)
        month_lines = by_month[month_index(month_start)]
        parts = {}
        for entry_type, key in ((EntryType.INCOME, "income"), (EntryType.EXPENSE, "expenses")):
            typed = [ln for ln in month_lines if ln.type is entry_type]
            realized = _sum(ln.converted for ln in typed if not ln.projected and ln.payment_date <= today)
            scheduled = _sum(ln.converted for ln in typed if not ln.projected and ln.payment_date > today)
            projected = _sum(ln.converted for ln in typed if ln.projected)
            parts[key] = {
                "realized": round_money(realized), "scheduled": round_money(scheduled),
                "projected_fixed": round_money(projected), "total": round_money(realized + scheduled + projected),
            }  # fmt: skip
        # Unconvertible balances are reported once, for the current month.
        end_balance, _, end_investments = book.at(month_end, record=month_index(month_start) == month_index(today))
        if first_negative is None and end_balance is not None and end_balance < 0 and month_end >= today:
            first_negative = month_start.strftime("%Y-%m")
        months.append(
            {
                "month": month_start.strftime("%Y-%m"), **parts,
                "net": parts["income"]["total"] - parts["expenses"]["total"],
                "end_balance": end_balance, "end_balance_projected": month_end > today,
                "end_investments": end_investments or ZERO,
            }  # fmt: skip
        )
    return {"from": start, "to": end, **conv.meta(), "months": months, "first_negative_month": first_negative}


# --- Categories (§13.5) ------------------------------------------------------------


def categories(db: Session, household_id: uuid.UUID, start: date, end: date, today: date,
               type_: EntryType, filters: Filters, conv: Converter) -> dict:  # fmt: skip
    lines = lines_for(db, household_id, start, end, today, filters, conv, type_)
    grouped: dict[uuid.UUID, list[Line]] = defaultdict(list)
    for line in lines:
        grouped[line.category_id].append(line)
    names = dict(db.execute(select(Category.id, Category.name).where(Category.id.in_(grouped))).all())
    realized_until = min(end, today)
    items = [{"category_id": cid, **_pair(group, realized_until)} for cid, group in grouped.items()]
    total = round_money(_sum(ln.converted for ln in lines))
    items = [i for i in items if i["total"] != 0 or i["realized"] != 0]
    items.sort(key=lambda i: (-i["total"], names.get(i["category_id"], "").lower()))
    for item in items:
        item["share"] = _share(item["total"], total)
    return {"type": type_, "from": start, "to": end, **conv.meta(), "total": total, "items": items}


# --- Card bills (§13.6) ------------------------------------------------------------


def card_bills(db: Session, household_id: uuid.UUID, today: date, filters: Filters, conv: Converter) -> dict:
    stmt = select(Card).where(
        Card.household_id == household_id,
        Card.is_active.is_(True),
        Card.type.in_((CardType.CREDIT, CardType.CREDIT_DEBIT)),
    )
    if filters.account_id is not None:
        stmt = stmt.where(Card.account_id == filters.account_id)
    holidays = load_holidays(db, today.year, today.year + 1)
    items = []
    for card in db.scalars(stmt):
        assert card.best_buy_day is not None and card.due_day is not None
        statement, due = next_statement(
            today, CardCycle(card.best_buy_day, card.due_day), lambda d: next_business_day(d, holidays)
        )
        member = Filters(member_id=filters.member_id)
        rows = [
            ln for ln in stored_lines(db, household_id, due, due, member, EntryType.EXPENSE, card_id=card.id)
            if ln.payment_method is PaymentMethod.CREDIT
        ]
        projected = [
            ln for ln in projected_lines(db, household_id, due, due, today, member, EntryType.EXPENSE, card_id=card.id)
            if ln.payment_method is PaymentMethod.CREDIT
        ]
        rows_total = _sum(conv.convert(ln.amount, ln.currency, ln.payment_date) for ln in rows)
        projected_total = _sum(conv.convert(ln.amount, ln.currency, ln.payment_date) for ln in projected)
        items.append(
            {
                "card_id": card.id, "due_date": due, "closes_on": statement.closing_date - timedelta(days=1),
                "rows_total": round_money(rows_total), "projected_fixed": round_money(projected_total),
                "total": round_money(rows_total + projected_total), "rows_count": len(rows), "_alias": card.alias,
            }  # fmt: skip
        )
    items.sort(key=lambda i: (i["due_date"], i.pop("_alias").lower()))
    return {**conv.meta(), "items": items}


# --- Projection items (§13.7) ------------------------------------------------------

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _sort_key(line: Line, sign: int) -> list:
    """Order by payment_date, then stored rows before occurrences, then created_at
    (or occurrence_date), then id, with the date and time parts following `order`."""
    if line.row is not None:
        created = line.row.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        group, moment, ident = 0, (created - EPOCH) // timedelta(microseconds=1), str(line.row.id)
    else:
        assert line.recurrence is not None and line.occurrence_date is not None
        group, moment, ident = 1, line.occurrence_date.toordinal(), str(line.recurrence.id)
    return [sign * line.payment_date.toordinal(), group, sign * moment, ident]


def _encode(key: list) -> str:
    return base64.urlsafe_b64encode(json.dumps(key).encode()).decode()


def _decode(cursor: str) -> list:
    try:
        key = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        if not (isinstance(key, list) and len(key) == 4):
            raise ValueError
        return key
    except (ValueError, TypeError) as exc:
        raise ApiError(400, "BAD_REQUEST", "Invalid cursor.") from exc


def projection_items(
    db: Session, household_id: uuid.UUID, start: date, end: date, today: date, filters: Filters,
    conv: Converter, type_: EntryType | None, descending: bool, limit: int, cursor: str | None,
) -> tuple[list[Line], str | None]:  # fmt: skip
    sign = -1 if descending else 1
    lines = stored_lines(db, household_id, start, end, filters, type_)
    lines += projected_lines(db, household_id, start, end, today, filters, type_)
    keyed = sorted(((_sort_key(ln, sign), ln) for ln in lines), key=lambda kl: kl[0])
    if cursor:
        after = _decode(cursor)
        keyed = [kl for kl in keyed if kl[0] > after]
    page = keyed[:limit]
    for _, line in page:
        line.converted = conv.convert(line.amount, line.currency, line.payment_date)
    next_cursor = _encode(page[-1][0]) if len(keyed) > limit else None
    return [line for _, line in page], next_cursor
