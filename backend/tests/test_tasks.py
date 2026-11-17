"""Tests for the task runner. Uses only the standard library (no Django needed)."""
import threading
import unittest

from common.tasks import ThreadPoolTaskRunner


class ThreadPoolTaskRunnerTests(unittest.TestCase):
    def setUp(self):
        self.runner = ThreadPoolTaskRunner(max_workers=2)

    def tearDown(self):
        self.runner.shutdown()

    def test_returns_result(self):
        future = self.runner.submit(lambda a, b: a + b, 2, b=3)
        self.assertEqual(future.result(timeout=5), 5)

    def test_runs_off_the_calling_thread(self):
        future = self.runner.submit(threading.current_thread)
        self.assertIsNot(future.result(timeout=5), threading.current_thread())

    def test_exception_is_captured_in_future(self):
        def boom():
            raise RuntimeError("expected failure")

        future = self.runner.submit(boom)
        with self.assertRaises(RuntimeError):
            future.result(timeout=5)

    def test_rejects_invalid_worker_count(self):
        with self.assertRaises(ValueError):
            ThreadPoolTaskRunner(max_workers=0)


if __name__ == "__main__":
    unittest.main()
