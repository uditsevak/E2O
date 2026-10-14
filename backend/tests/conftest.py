import os
import tempfile
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from typing import Any

# Configure before any app module reads settings.
os.environ.setdefault("ENV", "test")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://e2o:e2o@localhost:5433/e2o_test")
os.environ["STORAGE_BACKEND"] = "local"
os.environ["STORAGE_LOCAL_DIR"] = tempfile.mkdtemp(prefix="e2o-blobs-")
os.environ["APP_URL"] = "http://testserver"

import httpx
import psycopg
import pytest
from alembic.config import Config
from procrastinate.testing import InMemoryConnector
from sqlalchemy.ext.asyncio import AsyncSession

from alembic import command
from app.config import get_settings
from app.db import get_sessionmaker
from app.jobs.app import job_app
from app.main import app

KEEP_TABLES = {"alembic_version"}


def _reset_schema() -> None:
    conninfo = get_settings().psycopg_conninfo
    # The suite drops the whole schema; never let it point at a real database.
    db_name = conninfo.rsplit("/", 1)[-1].split("?", 1)[0]
    if not db_name.endswith("_test"):
        raise RuntimeError(f"Refusing to run tests against database {db_name!r} (name must end in _test)")
    with psycopg.connect(conninfo, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session", autouse=True)
def database() -> Iterator[None]:
    _reset_schema()
    yield


@pytest.fixture(scope="session", autouse=True)
def jobs() -> Iterator[InMemoryConnector]:
    connector = InMemoryConnector()
    with job_app.replace_connector(connector):
        yield connector


@pytest.fixture(autouse=True)
def clean_tables(jobs: InMemoryConnector) -> Iterator[None]:
    yield
    jobs.reset()
    with psycopg.connect(get_settings().psycopg_conninfo, autocommit=True) as conn:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename NOT LIKE 'procrastinate%'"
            )
            if r[0] not in KEEP_TABLES
        ]
        if tables:
            conn.execute("TRUNCATE " + ", ".join(f'"{t}"' for t in tables) + " CASCADE")


@pytest.fixture
async def db() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session


ClientFactory = Callable[[], httpx.AsyncClient]


@pytest.fixture
async def make_client() -> AsyncIterator[ClientFactory]:
    clients: list[httpx.AsyncClient] = []

    def factory() -> httpx.AsyncClient:
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")
        clients.append(client)
        return client

    yield factory
    for client in clients:
        await client.aclose()


@pytest.fixture
async def client(make_client: ClientFactory) -> httpx.AsyncClient:
    return make_client()


async def signup(
    client: httpx.AsyncClient, email: str, name: str = "Test User", password: str = "correct-horse"
) -> dict[str, Any]:
    resp = await client.post("/api/auth/signup", json={"email": email, "name": name, "password": password})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def create_workspace(client: httpx.AsyncClient, name: str = "DC Engineering") -> dict[str, Any]:
    resp = await client.post("/api/workspaces", json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()


SignedIn = Callable[..., Awaitable[tuple[httpx.AsyncClient, dict[str, Any]]]]


@pytest.fixture
def signed_in(make_client: ClientFactory) -> SignedIn:
    """Returns a coroutine creating a signed-up client with its own workspace."""

    async def factory(
        email: str | None = None, workspace: str = "Acme Flanges"
    ) -> tuple[httpx.AsyncClient, dict[str, Any]]:
        c = make_client()
        await signup(c, email or f"user-{uuid.uuid4().hex[:8]}@example.com")
        ws = await create_workspace(c, workspace)
        return c, ws

    return factory
