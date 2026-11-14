"""Global pytest configuration and session fixtures."""

from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest

from app.config import get_settings


@pytest.fixture(scope="session", autouse=True)
def prepare_test_database() -> None:
    """Ensure database schema is migrated to head before tests execute."""
    backend_dir = Path(__file__).resolve().parent.parent
    ini_path = backend_dir / "alembic.ini"
    cfg = Config(str(ini_path))
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    command.upgrade(cfg, "head")
