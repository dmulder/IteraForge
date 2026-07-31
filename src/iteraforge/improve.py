from __future__ import annotations

import asyncio

from .events import EventBus
from .models import JobRequest
from .settings import load_settings
from .tabs import list_tabs
from .workflow import JobManager


async def run_once() -> None:
    settings = load_settings()
    if not settings.get("automatic_improvement_enabled"):
        return
    tabs = [tab for tab in list_tabs() if not tab.get("invalid") and tab.get("state", {}).get("automatic_improvement_enabled", True)]
    if not tabs:
        return
    tab = tabs[0]
    manager = JobManager(EventBus())
    job = await manager.submit(
        JobRequest(
            mode="modify",
            tab_id=tab["id"],
            prompt="Make one small, reversible improvement to usability, validation, accessibility, or reliability. Do not remove features or user data.",
        ),
        trigger="scheduled-improvement",
    )
    while manager.get_job(job["id"]) and manager.get_job(job["id"])["status"] in {"queued", "running"}:
        await asyncio.sleep(0.2)


def main() -> None:
    asyncio.run(run_once())


if __name__ == "__main__":
    main()
