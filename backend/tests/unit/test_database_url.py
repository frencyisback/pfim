"""Database URL resolution (app.database._resolve_database_url).

This runs at startup. Without tests, a failure prevents application launch
with an unhelpful SQLite message rather than causing a test failure.

Relative paths must resolve against backend/, regardless of uvicorn's
working directory. Non-path values, including memory databases and URIs,
must pass through unchanged.
"""

from pathlib import Path

import pytest

from app.database import BACKEND_DIR, _resolve_database_url

PREFIX = "sqlite:///"


def test_a_relative_path_is_resolved_against_the_backend_directory():
    """A relative SQLite URL must target the same directory regardless of the working directory, whether launched from backend/, the project root, or the launcher."""
    resolved = _resolve_database_url(f"{PREFIX}../data/pfim.db")

    assert resolved.startswith(PREFIX)
    assert Path(resolved[len(PREFIX) :]) == (BACKEND_DIR.parent / "data" / "pfim.db")


def test_an_absolute_path_is_left_where_it_is(tmp_path):
    target = tmp_path / "elsewhere" / "pfim.db"

    resolved = _resolve_database_url(f"{PREFIX}{target}")

    assert Path(resolved[len(PREFIX) :]) == target
    # Prepare the directory: a valid but missing path must not
    # cause an opening error on first startup.
    assert target.parent.is_dir()


@pytest.mark.parametrize(
    "url",
    [
        "sqlite:///:memory:",  # in-memory database, no file
        "sqlite://",  # short form of the same case
        "sqlite:///",  # empty path
        "sqlite:///file:pfim?mode=memory&cache=shared&uri=true",  # SQLite URI
        "postgresql://user:password@localhost/pfim",  # another engine
    ],
)
def test_what_is_not_a_file_path_passes_through_untouched(url):
    """Previously, :memory: was joined to the filesystem path, attempting to open backend/:memory:, an invalid Windows filename. This value must select an in-memory database rather than produce a filesystem error."""
    assert _resolve_database_url(url) == url


def test_the_resolved_url_can_actually_be_opened(tmp_path):
    """The decisive check: SQLAlchemy must be able to open the returned URL."""
    from sqlalchemy import create_engine, text

    for url in (f"{PREFIX}{tmp_path / 'new' / 'pfim.db'}", "sqlite:///:memory:"):
        engine = create_engine(_resolve_database_url(url))
        with engine.connect() as connection:
            assert connection.execute(text("select 1")).scalar() == 1
        engine.dispose()
