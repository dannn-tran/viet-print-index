import unittest

from vie_doc_pipeline.sources.http import RequestGate


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
