from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from exposure_auditor import migrations
from exposure_auditor.models import Base


def test_migrations_build_exactly_the_schema_the_models_describe(tmp_path):
    # Tests and the running app must agree on the schema; this is what keeps
    # a model change from shipping without its migration.
    db = tmp_path / "migrated.db"
    migrations.upgrade(f"sqlite+aiosqlite:///{db}")
    with create_engine(f"sqlite:///{db}").connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_migrations_downgrade_cleanly(tmp_path):
    db = tmp_path / "migrated.db"
    url = f"sqlite+aiosqlite:///{db}"
    migrations.upgrade(url)
    migrations.downgrade("base", url)
    assert set(inspect(create_engine(f"sqlite:///{db}")).get_table_names()) == {"alembic_version"}
    migrations.upgrade(url)
