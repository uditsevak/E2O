"""procrastinate job queue schema

Revision ID: aea2d9014c4c
Revises: 063d375bee09
Create Date: 2026-10-14

The job queue lives in Postgres (procrastinate). Its schema is vendored in alembic/sql so this
migration is deterministic. When upgrading procrastinate, add a new revision that applies the
library's migration files for the versions in between (procrastinate/sql/migrations).
"""

from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "aea2d9014c4c"
down_revision: str | Sequence[str] | None = "063d375bee09"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA_FILE = Path(__file__).resolve().parent.parent / "sql" / "procrastinate_3.10.0_schema.sql"


def upgrade() -> None:
    # The driver treats % as a placeholder marker even without parameters; escape it (this is
    # what procrastinate's own `schema --apply` does).
    sql = SCHEMA_FILE.read_text(encoding="utf-8").replace("%", "%%")
    op.get_bind().exec_driver_sql(sql)


DROP_ALL = """
DROP TABLE IF EXISTS procrastinate_events, procrastinate_periodic_defers, procrastinate_jobs,
    procrastinate_workers CASCADE;
DO $$
DECLARE r record;
BEGIN
    FOR r IN
        SELECT p.oid::regprocedure AS sig
        FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = current_schema() AND left(p.proname, 14) = 'procrastinate_'
    LOOP
        EXECUTE 'DROP ROUTINE IF EXISTS ' || r.sig || ' CASCADE';
    END LOOP;
END $$;
DROP TYPE IF EXISTS procrastinate_job_status, procrastinate_job_event_type,
    procrastinate_job_to_defer_v1 CASCADE;
"""


def downgrade() -> None:
    op.get_bind().exec_driver_sql(DROP_ALL)
