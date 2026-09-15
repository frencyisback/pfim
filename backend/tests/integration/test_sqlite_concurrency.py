"""SQLite transaction semantics with real connections and temporary files.

The main fixture uses StaticPool and one connection: fast, but unable to
prove locking and snapshots across processes or connections. These tests
use an isolated file under tmp_path and never open the operational database.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.database import (
    Base,
    _translate_sqlite_lock_error,
    begin_session_transaction,
    configure_sqlite_engine,
)
from app.models.account import Account
from app.models.category import Category
from app.models.security import Security
from app.models.trade import Trade
from app.schemas.category import CategoryCreate
from app.schemas.trade import TradeCostCreate, TradeCreate
from app.schemas.transaction import TransactionCreate
from app.services.category_service import CategoryService
from app.services.trade_service import TradeService
from app.services.transaction_service import TransactionService
from app.utils.csv_parser import CsvProfile
from app.utils.errors import ConflictError, DatabaseBusyError


@pytest.fixture
def sqlite_file():
    """Isolated file in an existing directory, compatible with the Windows sandbox."""
    path = Path(__file__).parent / f".sqlite-concurrency-{uuid4().hex}.db"
    try:
        yield path
    finally:
        for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm"), Path(f"{path}-journal")):
            candidate.unlink(missing_ok=True)


def _file_engine(sqlite_file: Path, *, busy_timeout_ms: int = 75, wal: bool = False):
    if wal:
        # journal_mode cannot change inside the engine's explicit BEGIN.
        # Enable it first using a bootstrap connection that is immediately
        # closed; it remains a property of the temporary database only.
        bootstrap = sqlite3.connect(sqlite_file)
        try:
            assert bootstrap.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower() == "wal"
        finally:
            bootstrap.close()
    engine = create_engine(
        f"sqlite:///{sqlite_file}",
        connect_args={"check_same_thread": False, "timeout": busy_timeout_ms / 1_000},
    )
    configure_sqlite_engine(engine, busy_timeout_ms=busy_timeout_ms)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE entries (id INTEGER PRIMARY KEY, value TEXT)"))
    return engine


def test_configuration_enables_fk_busy_timeout_and_explicit_begin(sqlite_file):
    engine = _file_engine(sqlite_file, busy_timeout_ms=123)
    statements: list[str] = []

    def record_statement(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record_statement)
    try:
        with Session(engine) as read_session:
            begin_session_transaction(read_session, immediate=False)
            read_session.execute(text("SELECT 1")).scalar_one()
            read_session.rollback()

        with Session(engine) as write_session:
            begin_session_transaction(write_session, immediate=True)
            write_session.execute(text("INSERT INTO entries(value) VALUES ('ok')"))
            write_session.commit()

        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
            assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one() == 123
    finally:
        event.remove(engine, "before_cursor_execute", record_statement)
        engine.dispose()

    normalized = [statement.strip().upper() for statement in statements]
    assert "BEGIN" in normalized
    assert "BEGIN IMMEDIATE" in normalized


def test_begin_immediate_serializes_writers_and_busy_is_explicit(sqlite_file):
    engine = _file_engine(sqlite_file, busy_timeout_ms=20)
    first = Session(engine)
    second = Session(engine)
    try:
        begin_session_transaction(first, immediate=True)
        first.execute(text("INSERT INTO entries(value) VALUES ('first')"))

        try:
            begin_session_transaction(second, immediate=True)
        except OperationalError as exc:
            translated = _translate_sqlite_lock_error(exc)
        else:  # pragma: no cover - fail clearly if the lock does not exist
            raise AssertionError("The second writer passed BEGIN IMMEDIATE")

        assert isinstance(translated, DatabaseBusyError)
        assert translated.detail == {"retryable": True}
        second.rollback()

        first.commit()
        begin_session_transaction(second, immediate=True)
        second.execute(text("INSERT INTO entries(value) VALUES ('second')"))
        second.commit()

        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT value FROM entries ORDER BY id")
            ).scalars().all() == [
                "first",
                "second",
            ]
    finally:
        first.close()
        second.close()
        engine.dispose()


def test_multi_query_read_keeps_one_snapshot(sqlite_file):
    engine = _file_engine(sqlite_file, busy_timeout_ms=250, wal=True)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO entries(value) VALUES ('before')"))

    reader = Session(engine)
    writer = Session(engine)
    try:
        begin_session_transaction(reader, immediate=False)
        assert reader.execute(text("SELECT COUNT(*) FROM entries")).scalar_one() == 1

        begin_session_transaction(writer, immediate=True)
        writer.execute(text("INSERT INTO entries(value) VALUES ('after')"))
        writer.commit()

        # The second query of the same report still sees the initial snapshot,
        # rather than mixing different commits.
        assert reader.execute(text("SELECT COUNT(*) FROM entries")).scalar_one() == 1
        reader.commit()

        with engine.connect() as connection:
            assert connection.execute(text("SELECT COUNT(*) FROM entries")).scalar_one() == 2
    finally:
        reader.close()
        writer.close()
        engine.dispose()


def test_category_leaf_invariant_is_serialized_between_writers(sqlite_file):
    """A transaction versus first-child race must not create an impossible state."""
    engine = _file_engine(sqlite_file, busy_timeout_ms=1_000)
    Base.metadata.create_all(engine)
    with Session(engine) as seed:
        begin_session_transaction(seed, immediate=True)
        account = Account(
            name="Checking",
            type="checking",
            currency="EUR",
            opening_balance=0,
            opened_on=date(2026, 1, 10),
        )
        category = Category(name="Expenses", type="expense", is_system=False)
        seed.add_all([account, category])
        seed.flush()
        account_id = account.id
        category_id = category.id
        seed.commit()

    transaction_written = threading.Event()
    second_attempting = threading.Event()
    release_first = threading.Event()

    def write_transaction():
        with Session(engine) as session:
            begin_session_transaction(session, immediate=True)
            TransactionService(session).create_transaction(
                TransactionCreate(
                    account_id=account_id,
                    category_id=category_id,
                    date="2026-01-10",
                    amount=Decimal(-10),
                )
            )
            transaction_written.set()
            assert release_first.wait(timeout=2)
            session.commit()
            return "committed"

    def add_first_child():
        assert transaction_written.wait(timeout=2)
        second_attempting.set()
        with Session(engine) as session:
            begin_session_transaction(session, immediate=True)
            try:
                CategoryService(session).create_category(
                    CategoryCreate(name="Groceries", type="expense", parent_id=category_id)
                )
            except ConflictError:
                session.rollback()
                return "rejected"
            session.commit()
            return "committed"

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(write_transaction)
            second = executor.submit(add_first_child)
            assert second_attempting.wait(timeout=2)
            time.sleep(0.05)
            assert not second.done(), "the second writer did not wait for the first writer's lock"
            release_first.set()
            assert first.result(timeout=2) == "committed"
            assert second.result(timeout=2) == "rejected"

        with Session(engine) as check:
            begin_session_transaction(check, immediate=False)
            assert check.scalar(text("SELECT COUNT(*) FROM transactions")) == 1
            assert (
                check.scalar(text("SELECT COUNT(*) FROM categories WHERE parent_id IS NOT NULL"))
                == 0
            )
    finally:
        engine.dispose()


def test_normalized_category_uniqueness_is_serialized_between_writers(sqlite_file):
    """The second creation rereads the equivalent name after the first commit."""
    engine = _file_engine(sqlite_file, busy_timeout_ms=2_000)
    Base.metadata.create_all(engine)
    first_written = threading.Event()
    second_attempting = threading.Event()
    release_first = threading.Event()

    def create_first():
        with Session(engine) as session:
            begin_session_transaction(session, immediate=True)
            CategoryService(session).create_category(CategoryCreate(name="Straße", type="expense"))
            first_written.set()
            assert release_first.wait(timeout=3)
            session.commit()
            return "committed"

    def create_second():
        assert first_written.wait(timeout=3)
        second_attempting.set()
        with Session(engine) as session:
            begin_session_transaction(session, immediate=True)
            try:
                CategoryService(session).create_category(
                    CategoryCreate(name=" STRASSE ", type="income")
                )
            except ConflictError as exc:
                session.rollback()
                return exc.detail
            raise AssertionError("The second equivalent category was accepted")

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(create_first)
            second = executor.submit(create_second)
            assert second_attempting.wait(timeout=3)
            assert not second.done()
            release_first.set()
            assert first.result(timeout=3) == "committed"
            assert len(second.result(timeout=3)["category_ids"]) == 1
        with Session(engine) as check:
            assert check.execute(text("SELECT name FROM categories")).scalars().all() == ["Straße"]
    finally:
        release_first.set()
        engine.dispose()


def test_sale_cost_aggregate_is_serialized_between_writers(sqlite_file):
    """Two individually valid costs must not make sale proceeds negative.

    Each writer adds EUR 60 to a EUR 100 sale. Without a lock acquired
    before validation, both would read zero costs and commit EUR 120 total.
    BEGIN IMMEDIATE makes the second wait, then reread the committed EUR 60
    and reject its cost without creating it or a partial cash movement.
    """
    engine = _file_engine(sqlite_file, busy_timeout_ms=2_000)
    Base.metadata.create_all(engine)

    with Session(engine) as seed:
        begin_session_transaction(seed, immediate=True)
        cash_account = Account(
            name="Cash",
            type="checking",
            currency="EUR",
            opening_balance=0,
            opened_on=date(2026, 1, 10),
        )
        security = Security(
            ticker="RACE",
            name="Race condition test",
            type="stock",
            currency="EUR",
            is_active=True,
        )
        seed.add_all([cash_account, security])
        seed.flush()
        investment_account = Account(
            name="Investment account",
            type="investment",
            currency="EUR",
            opening_balance=0,
            opened_on=date(2026, 1, 10),
            reference_account_id=cash_account.id,
        )
        seed.add(investment_account)
        seed.flush()
        sale = Trade(
            security_id=security.id,
            account_id=investment_account.id,
            cash_account_id=cash_account.id,
            type="sell",
            date=date(2026, 1, 10),
            quantity=Decimal(1),
            price=Decimal(100),
            quote_price=Decimal(100),
            currency="EUR",
            fx_rate=Decimal(1),
            price_eur=Decimal(100),
            total_amount=Decimal(100),
            total_eur=Decimal(100),
        )
        seed.add(sale)
        seed.flush()
        sale_id = sale.id
        seed.commit()

    first_cost_written = threading.Event()
    second_attempting = threading.Event()
    release_first = threading.Event()

    def add_first_cost():
        with Session(engine) as session:
            begin_session_transaction(session, immediate=True)
            TradeService(session).add_cost(
                sale_id,
                TradeCostCreate(
                    cost_type="commission",
                    amount=Decimal(60),
                    currency="EUR",
                ),
            )
            first_cost_written.set()
            assert release_first.wait(timeout=3)
            session.commit()
            return "committed"

    def add_second_cost():
        assert first_cost_written.wait(timeout=3)
        second_attempting.set()
        with Session(engine) as session:
            begin_session_transaction(session, immediate=True)
            try:
                TradeService(session).add_cost(
                    sale_id,
                    TradeCostCreate(
                        cost_type="tax",
                        amount=Decimal(60),
                        currency="EUR",
                    ),
                )
            except ConflictError:
                session.rollback()
                return "rejected"
            session.commit()
            return "committed"

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(add_first_cost)
            second = executor.submit(add_second_cost)
            assert second_attempting.wait(timeout=3)
            time.sleep(0.05)
            assert not second.done(), "the second cost did not wait for the first cost's lock"
            release_first.set()
            assert first.result(timeout=3) == "committed"
            assert second.result(timeout=3) == "rejected"

        with Session(engine) as check:
            begin_session_transaction(check, immediate=False)
            cost_count, total_costs = check.execute(
                text(
                    "SELECT COUNT(*), COALESCE(SUM(amount_eur), 0) "
                    "FROM trade_costs WHERE trade_id = :trade_id"
                ),
                {"trade_id": sale_id},
            ).one()
            linked_amounts = (
                check.execute(
                    text("SELECT amount_eur FROM transactions WHERE trade_id = :trade_id"),
                    {"trade_id": sale_id},
                )
                .scalars()
                .all()
            )

            assert cost_count == 1
            assert Decimal(str(total_costs)) == Decimal(60)
            assert [Decimal(str(value)) for value in linked_amounts] == [Decimal(40)]
            check.commit()
    finally:
        engine.dispose()


def test_fifo_sale_is_serialized_between_writers(sqlite_file):
    """Concurrent sales must not consume the same lot twice.

    The portfolio has one lot of 10 units, and each writer tries to sell all
    of them. The first keeps its transaction open after validation and linked
    writes; the second waits at BEGIN IMMEDIATE. After the first commit, it
    rereads the updated FIFO sequence and is rejected as a short sale.
    """
    engine = _file_engine(sqlite_file, busy_timeout_ms=2_000)
    Base.metadata.create_all(engine)
    trade_date = date(2026, 3, 10)

    with Session(engine) as seed:
        begin_session_transaction(seed, immediate=True)
        cash_account = Account(
            name="Cash FIFO",
            type="checking",
            currency="EUR",
            opening_balance=0,
            opened_on=trade_date,
        )
        security = Security(
            ticker="FIFO-RACE",
            name="FIFO race condition test",
            type="stock",
            currency="EUR",
            is_active=True,
        )
        seed.add_all([cash_account, security])
        seed.flush()
        investment_account = Account(
            name="Investment account FIFO",
            type="investment",
            currency="EUR",
            opening_balance=0,
            opened_on=trade_date,
            reference_account_id=cash_account.id,
        )
        seed.add(investment_account)
        seed.flush()
        investment_account_id = investment_account.id
        security_id = security.id

        TradeService(seed).create_trade(
            TradeCreate(
                security_id=security_id,
                account_id=investment_account_id,
                type="buy",
                date=trade_date,
                quantity=Decimal(10),
                price=Decimal(10),
                currency="EUR",
            )
        )
        seed.commit()

    first_sale_written = threading.Event()
    second_attempting = threading.Event()
    release_first = threading.Event()

    def sell_first_copy():
        with Session(engine) as session:
            begin_session_transaction(session, immediate=True)
            TradeService(session).create_trade(
                TradeCreate(
                    security_id=security_id,
                    account_id=investment_account_id,
                    type="sell",
                    date=trade_date,
                    quantity=Decimal(10),
                    price=Decimal(10),
                    currency="EUR",
                )
            )
            first_sale_written.set()
            assert release_first.wait(timeout=3)
            session.commit()
            return "committed"

    def sell_second_copy():
        assert first_sale_written.wait(timeout=3)
        second_attempting.set()
        with Session(engine) as session:
            begin_session_transaction(session, immediate=True)
            try:
                TradeService(session).create_trade(
                    TradeCreate(
                        security_id=security_id,
                        account_id=investment_account_id,
                        type="sell",
                        date=trade_date,
                        quantity=Decimal(10),
                        price=Decimal(10),
                        currency="EUR",
                    )
                )
            except ConflictError:
                session.rollback()
                return "rejected"
            session.commit()
            return "committed"

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(sell_first_copy)
            second = executor.submit(sell_second_copy)
            assert second_attempting.wait(timeout=3)
            time.sleep(0.05)
            assert not second.done(), "the second sale did not wait for the first sale's lock"
            release_first.set()
            assert first.result(timeout=3) == "committed"
            assert second.result(timeout=3) == "rejected"

        with Session(engine) as check:
            begin_session_transaction(check, immediate=False)
            buy_count, sale_count, net_quantity = check.execute(
                text(
                    "SELECT "
                    "SUM(CASE WHEN type = 'buy' THEN 1 ELSE 0 END), "
                    "SUM(CASE WHEN type = 'sell' THEN 1 ELSE 0 END), "
                    "SUM(CASE WHEN type = 'buy' THEN quantity ELSE -quantity END) "
                    "FROM trades WHERE security_id = :security_id"
                ),
                {"security_id": security_id},
            ).one()
            linked_sale_movements = check.scalar(
                text(
                    "SELECT COUNT(*) FROM transactions AS tx "
                    "JOIN trades AS trade ON trade.id = tx.trade_id "
                    "WHERE trade.security_id = :security_id AND trade.type = 'sell'"
                ),
                {"security_id": security_id},
            )

            assert buy_count == 1
            assert sale_count == 1
            assert Decimal(str(net_quantity)) == Decimal(0)
            assert linked_sale_movements == 1
            check.commit()
    finally:
        engine.dispose()


def test_transaction_import_deduplication_is_serialized_between_writers(sqlite_file):
    """Simultaneous imports of the same row persist only one movement."""
    engine = _file_engine(sqlite_file, busy_timeout_ms=2_000)
    Base.metadata.create_all(engine)

    with Session(engine) as seed:
        begin_session_transaction(seed, immediate=True)
        account = Account(
            name="Checking import",
            type="checking",
            currency="EUR",
            opening_balance=0,
            opened_on=date(2026, 2, 10),
        )
        category = Category(name="Salary import", type="income", is_system=False)
        seed.add_all([account, category])
        seed.flush()
        account_id = account.id
        seed.commit()

    content = "date,description,amount,category\n" "2026-02-10,Salary,1500.00,Salary import\n"
    profile = CsvProfile(category_column="category")
    first_import_prepared = threading.Event()
    second_attempting = threading.Event()
    release_first = threading.Event()

    def import_first_copy():
        with Session(engine) as session:
            begin_session_transaction(session, immediate=True)
            result = TransactionService(session).import_transactions(
                content,
                profile,
                account_id,
                import_source="race-first.csv",
            )
            assert (result.imported, result.skipped_duplicates, result.errors) == (1, 0, 0)
            first_import_prepared.set()
            assert release_first.wait(timeout=3)
            session.commit()
            return "committed"

    def import_second_copy():
        assert first_import_prepared.wait(timeout=3)
        second_attempting.set()
        with Session(engine) as session:
            begin_session_transaction(session, immediate=True)
            result = TransactionService(session).import_transactions(
                content,
                profile,
                account_id,
                import_source="race-second.csv",
            )
            session.commit()
            return result.imported, result.skipped_duplicates, result.errors

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(import_first_copy)
            second = executor.submit(import_second_copy)
            assert second_attempting.wait(timeout=3)
            time.sleep(0.05)
            assert not second.done(), "the second import did not wait for the first import's lock"
            release_first.set()
            assert first.result(timeout=3) == "committed"
            assert second.result(timeout=3) == (0, 1, 0)

        with Session(engine) as check:
            begin_session_transaction(check, immediate=False)
            assert (
                check.scalar(
                    text(
                        "SELECT COUNT(*) FROM transactions "
                        "WHERE account_id = :account_id AND import_hash IS NOT NULL"
                    ),
                    {"account_id": account_id},
                )
                == 1
            )
            check.commit()
    finally:
        engine.dispose()
