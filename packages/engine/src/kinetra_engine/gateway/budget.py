"""Per-project call budget and the cost ledger (G-01).

Cost is the `usage.cost` (USD) the provider reports in each response; this module computes no prices.
`assumed_call_cost_usd` (`사용자 선언`, set by whoever creates the budget) does two jobs so a cost cap cannot be bypassed:
it is held back while a call is in flight, and it is what a call is charged when the provider reported no cost (no
`usage.cost`, or a transport failure after the request may have left). The charge goes in `charged_usd`; the record's
`cost_usd` stays `null` so the ledger says what was actually known.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .redact import redact


class GatewayError(Exception):
    """Base class. Messages never contain the API key."""


class BudgetExceeded(GatewayError):
    """The project has no call budget left (or no budget at all). The request was not sent."""


def _finite_nonneg(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0


@dataclass(frozen=True)
class Budget:
    """At least one limit is required. `max_cost_usd` also requires `assumed_call_cost_usd`."""

    max_calls: int | None = None
    max_cost_usd: float | None = None
    assumed_call_cost_usd: float | None = None

    def __post_init__(self) -> None:
        if self.max_calls is None and self.max_cost_usd is None:
            raise ValueError("Budget needs max_calls or max_cost_usd")
        if self.max_calls is not None and (isinstance(self.max_calls, bool) or not isinstance(self.max_calls, int) or self.max_calls < 0):
            raise ValueError(f"max_calls must be an int >= 0: {self.max_calls!r}")
        if self.max_cost_usd is not None and not _finite_nonneg(self.max_cost_usd):
            raise ValueError(f"max_cost_usd must be a finite number >= 0: {self.max_cost_usd!r}")
        if self.assumed_call_cost_usd is not None and not _finite_nonneg(self.assumed_call_cost_usd):
            raise ValueError(f"assumed_call_cost_usd must be a finite number >= 0: {self.assumed_call_cost_usd!r}")
        if self.max_cost_usd is not None and self.assumed_call_cost_usd is None:
            raise ValueError("max_cost_usd needs assumed_call_cost_usd (held while a call is in flight, charged when the provider reports no cost)")
        if self.max_cost_usd is None and self.assumed_call_cost_usd is not None:
            raise ValueError("assumed_call_cost_usd only makes sense with max_cost_usd")


@dataclass
class ProjectUsage:
    calls: int = 0  # requests sent (ok or error); rejected requests are not counted
    charged_usd: float = 0.0
    unknown_cost_calls: int = 0  # calls charged the declared assumption instead of a reported cost
    in_flight: int = 0
    reserved_usd: float = 0.0  # in-flight calls, held at the declared unknown-call cost until the real cost is known


class CostLedger:
    """Append-only JSONL, one line per request, `path=None` keeps nothing on disk.

    Replayed on start so the budget survives a restart. A line that does not parse stops the start-up: skipping it
    would forget spent budget.
    """

    def __init__(self, path: Path | None = None, secrets: tuple[str, ...] = ()):
        self.path = path
        self._secrets = secrets

    def append(self, entry: dict) -> None:
        if self.path is None:
            return
        line = json.dumps(entry, ensure_ascii=False)
        line = redact(line, self._secrets)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def replay(self) -> Iterator[dict]:
        if self.path is None or not self.path.exists():
            return
        with open(self.path, encoding="utf-8") as f:
            for n, line in enumerate(f, start=1):
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError as e:
                    raise GatewayError(f"cost ledger {self.path}:{n} is not JSON ({e.msg}); refusing to start with unknown spend") from None
                if not isinstance(entry, dict):
                    raise GatewayError(f"cost ledger {self.path}:{n} is not an object; refusing to start with unknown spend")
                yield entry
