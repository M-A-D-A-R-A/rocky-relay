from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from time import perf_counter
from typing import Iterator


@dataclass
class TurnTimer:
    timings_ms: dict[str, float] = field(default_factory=dict)

    @contextmanager
    def measure(self, name: str) -> Iterator[None]:
        start = perf_counter()
        try:
            yield
        finally:
            self.timings_ms[name] = round((perf_counter() - start) * 1000, 2)
