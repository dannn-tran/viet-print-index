import unittest

from vie_doc_pipeline.config import AcquisitionConfig
from vie_doc_pipeline.sources.http import RequestGate, retry_policy


class RequestGateTest(unittest.TestCase):
    def test_reserves_evenly_spaced_request_starts(self) -> None:
        now = [0.0]
        sleeps: list[float] = []

        def sleep(delay: float) -> None:
            sleeps.append(delay)
            now[0] += delay

        gate = RequestGate(1.0, clock=lambda: now[0], sleep=sleep)
        gate.wait_for_turn()
        gate.wait_for_turn()
        gate.wait_for_turn()

        self.assertEqual(sleeps, [1.0, 1.0])

    def test_retry_policy_uses_the_configured_attempt_budget(self) -> None:
        policy = retry_policy(AcquisitionConfig(max_attempts=4, backoff_factor=0.5))

        self.assertEqual(policy.total, 3)
        self.assertEqual(policy.backoff_factor, 0.5)
