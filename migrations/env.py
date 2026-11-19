from alembic import context
from sqlalchemy import create_engine, pool
from backend.config import settings
from backend.db import sqlalchemy_url
from backend.models import Base

config = context.config
url = settings().database_url_unpooled
if not url:
    raise RuntimeError("DATABASE_URL_UNPOOLED is required for migrations")
if "-pooler." in url:
    raise RuntimeError("Migrations require a direct, unpooled connection")
target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to):
    # PostgreSQL exposes expression-index SQL as a textual element; SQLAlchemy
    # models it as a ColumnClause. Alembic otherwise reports a false remove/add.
    if type_ == "index" and name == "ix_decision_fts":
        return False
    return True


if context.is_offline_mode():
    context.configure(url=sqlalchemy_url(url), target_metadata=target_metadata, literal_binds=True,
                      include_object=include_object)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(sqlalchemy_url(url), poolclass=pool.NullPool, hide_parameters=True)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True,
                          include_object=include_object)
        with context.begin_transaction():
            context.run_migrations()
