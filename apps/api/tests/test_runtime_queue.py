import asyncio
import unittest

from ai.runtime.queue import BoundedRuntimeQueue, RuntimeQueueBlockedError, RuntimeQueueClosed


class RuntimeQueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_put_get_basic_fifo(self):
        queue = BoundedRuntimeQueue(maxsize=4, block_seconds=1)
        await queue.put("a")
        await queue.put("b")
        self.assertEqual(await queue.get(timeout=1), "a")
        self.assertEqual(await queue.get(timeout=1), "b")

    async def test_try_put_basic_fifo(self):
        queue = BoundedRuntimeQueue(maxsize=4, block_seconds=1)
        self.assertTrue(await queue.try_put("a"))
        self.assertTrue(await queue.try_put("b"))
        self.assertEqual(await queue.get(timeout=1), "a")
        self.assertEqual(await queue.get(timeout=1), "b")

    async def test_put_waits_then_succeeds_once_space_opens(self):
        queue = BoundedRuntimeQueue(maxsize=1, block_seconds=1)
        await queue.put("a")

        async def drain_after_delay():
            await asyncio.sleep(0.05)
            self.assertEqual(await queue.get(timeout=1), "a")

        drain_task = asyncio.create_task(drain_after_delay())
        await queue.put("b")
        await drain_task
        self.assertEqual(await queue.get(timeout=1), "b")

    async def test_put_raises_blocked_after_block_seconds_when_still_full(self):
        queue = BoundedRuntimeQueue(maxsize=1, block_seconds=0.05)
        await queue.put("a")
        with self.assertRaises(RuntimeQueueBlockedError):
            await queue.put("b")
        # 기존 item을 밀어내지 않았는지 확인.
        self.assertEqual(await queue.get(timeout=1), "a")

    async def test_try_put_returns_false_without_evicting_when_full(self):
        queue = BoundedRuntimeQueue(maxsize=1, block_seconds=1)
        self.assertTrue(await queue.try_put("a"))
        self.assertFalse(await queue.try_put("b"))
        self.assertEqual(await queue.get(timeout=1), "a")

    async def test_close_drains_pending_items_then_raises_closed(self):
        queue = BoundedRuntimeQueue(maxsize=4, block_seconds=1)
        await queue.put("a")
        await queue.put("b")
        await queue.close()
        self.assertEqual(await queue.get(timeout=1), "a")
        self.assertEqual(await queue.get(timeout=1), "b")
        with self.assertRaises(RuntimeQueueClosed):
            await queue.get(timeout=1)

    async def test_fail_discards_pending_items_and_raises_error_immediately(self):
        queue = BoundedRuntimeQueue(maxsize=4, block_seconds=1)
        await queue.put("a")
        error = ValueError("boom")
        await queue.fail(error)
        with self.assertRaises(ValueError) as ctx:
            await queue.get(timeout=1)
        self.assertIs(ctx.exception, error)

    async def test_fail_after_close_upgrades_to_error(self):
        queue = BoundedRuntimeQueue(maxsize=4, block_seconds=1)
        await queue.close()
        error = ValueError("boom")
        await queue.fail(error)
        with self.assertRaises(ValueError) as ctx:
            await queue.get(timeout=1)
        self.assertIs(ctx.exception, error)

    async def test_get_wakes_on_close_while_waiting(self):
        queue = BoundedRuntimeQueue(maxsize=4, block_seconds=1)

        async def close_after_delay():
            await asyncio.sleep(0.05)
            await queue.close()

        asyncio.create_task(close_after_delay())
        with self.assertRaises(RuntimeQueueClosed):
            await queue.get(timeout=1)

    async def test_get_wakes_on_fail_while_waiting(self):
        queue = BoundedRuntimeQueue(maxsize=4, block_seconds=1)
        error = ValueError("boom")

        async def fail_after_delay():
            await asyncio.sleep(0.05)
            await queue.fail(error)

        asyncio.create_task(fail_after_delay())
        with self.assertRaises(ValueError) as ctx:
            await queue.get(timeout=1)
        self.assertIs(ctx.exception, error)

    async def test_get_times_out_when_nothing_arrives(self):
        queue = BoundedRuntimeQueue(maxsize=4, block_seconds=1)
        with self.assertRaises(TimeoutError):
            await queue.get(timeout=0.05)

    async def test_pending_put_raises_closed_when_queue_closes_while_waiting(self):
        queue = BoundedRuntimeQueue(maxsize=1, block_seconds=1)
        await queue.put("a")

        async def close_after_delay():
            await asyncio.sleep(0.05)
            await queue.close()

        asyncio.create_task(close_after_delay())
        with self.assertRaises(RuntimeQueueClosed):
            await queue.put("b")

    async def test_concurrent_producer_consumer_preserves_order(self):
        queue = BoundedRuntimeQueue(maxsize=2, block_seconds=1)
        produced = list(range(50))
        consumed = []

        async def producer():
            for item in produced:
                await queue.put(item)
            await queue.close()

        async def consumer():
            while True:
                try:
                    consumed.append(await queue.get(timeout=1))
                except RuntimeQueueClosed:
                    return

        await asyncio.gather(producer(), consumer())
        self.assertEqual(consumed, produced)


if __name__ == "__main__":
    unittest.main()
