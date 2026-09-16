"""Centralized, campaign-seeded RNG service (design doc Section 43).
Nothing in the engine calls Python's random module directly - everything
goes through an RNGService instance, so a fixed seed makes an entire
campaign (including every dice roll) reproducible for debugging, testing,
and save/load.
"""
import random


class RNGService:
    def __init__(self, seed: int | None = None):
        self.seed = seed
        self._random = random.Random(seed)

    def randint(self, low: int, high: int) -> int:
        return self._random.randint(low, high)

    def choice(self, sequence):
        return self._random.choice(sequence)

    def shuffle(self, sequence: list) -> None:
        self._random.shuffle(sequence)


_default_service: RNGService | None = None


def default() -> RNGService:
    """The process-wide default RNG service, for ad hoc rolls made outside
    any campaign (e.g. a bare CLI invocation). Campaign code should always
    use Campaign.rng() instead of this, so its rolls are reproducible from
    the campaign's own seed."""
    global _default_service
    if _default_service is None:
        _default_service = RNGService()
    return _default_service


def seeded(seed: int) -> RNGService:
    return RNGService(seed)
