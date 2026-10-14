"""Background jobs on a Postgres-backed queue (procrastinate): no Redis to run or pay for.

Run a worker with:  uv run python -m app.jobs.worker
"""

from procrastinate import App, PsycopgConnector

from app.config import get_settings

job_app = App(
    connector=PsycopgConnector(conninfo=get_settings().psycopg_conninfo),
    import_paths=["app.jobs.tasks"],
)
