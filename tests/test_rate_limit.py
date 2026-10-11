from __future__ import annotations

import unittest

from traceharbor.rate_limit import TokenBucketRateLimiter


class RateLimiterTests(unittest.TestCase):
    def test_enforces_capacity(self) -> None:
        limiter = TokenBucketRateLimiter(capacity=2, per_seconds=10)
        self.assertTrue(limiter.allow("key", now=0))
        self.assertTrue(limiter.allow("key", now=0))
        self.assertFalse(limiter.allow("key", now=0))

    def test_refills_over_time(self) -> None:
        limiter = TokenBucketRateLimiter(capacity=2, per_seconds=10)
        limiter.allow("key", now=0)
        limiter.allow("key", now=0)
        self.assertTrue(limiter.allow("key", now=5))

    def test_tracks_keys_independently(self) -> None:
        limiter = TokenBucketRateLimiter(capacity=1)
        self.assertTrue(limiter.allow("first", now=0))
        self.assertFalse(limiter.allow("first", now=0))
        self.assertTrue(limiter.allow("second", now=0))


if __name__ == "__main__":
    unittest.main()

