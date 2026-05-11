import asyncio

from app.bot.memory_jobs import MemoryJobQueue


def test_memory_job_queue_runs_one_job_at_a_time():
    async def scenario():
        queue = MemoryJobQueue()
        release = asyncio.Event()

        async def runner():
            await release.wait()

        first = await queue.start("refresh", runner)
        second = await queue.start("other", runner)

        assert first is not None
        assert second is None
        assert queue.active_snapshot() is not None
        assert "refresh" in queue.render()

        release.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        latest = queue.latest_snapshot()
        assert latest is not None
        assert latest.status == "completed"
        assert queue.active_snapshot() is None

    asyncio.run(scenario())


def test_memory_job_queue_can_cancel_active_job():
    async def scenario():
        queue = MemoryJobQueue()

        async def runner():
            await asyncio.sleep(60)

        started = await queue.start("refresh", runner)
        assert started is not None
        assert queue.cancel_current()
        for _ in range(5):
            await asyncio.sleep(0)
            if queue.latest_snapshot() and queue.latest_snapshot().status == "cancelled":
                break

        latest = queue.latest_snapshot()
        assert latest is not None
        assert latest.status == "cancelled"

    asyncio.run(scenario())
