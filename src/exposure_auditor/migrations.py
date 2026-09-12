"""Schema migrations (Alembic), callable from the CLI and from tests."""

from alembic import command
from alembic.config import Config

from .config import get_settings


def alembic_config(url: str | None = None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", "exposure_auditor:migrations")
    # configparser interpolation: a literal % in a password must be doubled.
    cfg.set_main_option("sqlalchemy.url", (url or get_settings().database_url).replace("%", "%%"))
    return cfg


def upgrade(url: str | None = None, revision: str = "head") -> None:
    command.upgrade(alembic_config(url), revision)


def downgrade(revision: str, url: str | None = None) -> None:
    command.downgrade(alembic_config(url), revision)


def stamp(revision: str, url: str | None = None) -> None:
    """Record that a database built before migrations existed is at `revision`."""
    command.stamp(alembic_config(url), revision)
