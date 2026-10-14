import asyncio

from app.config import get_settings
from app.core.logging import configure_logging
from app.jobs.app import job_app


async def main() -> None:
    configure_logging(get_settings().log_level)
    async with job_app.open_async():
        await job_app.run_worker_async(queues=["sync", "pipeline"], concurrency=4)


if __name__ == "__main__":
    asyncio.run(main())
