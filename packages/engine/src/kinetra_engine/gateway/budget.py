"""Per-project call budget and the cost ledger (G-01).

Money is counted in integer micro-dollars so repeated adds never drift (0.1 + 0.1 + 0.1 > 0.3 in floats). Amounts that are
spent (a reported cost, the assumed cost) are rounded *up* to the next micro-dollar from their decimal text, so a non-zero
cost never counts as zero. The cap `max_cost_usd` is rounded *down*, so it is never above what the budget declared.

Cost semantics (this module computes no prices; `usage.cost` is what the provider reports):
    - `assumed_call_cost_usd` (`사용자 선언`, set by whoever creates the budget, must be > 0) is the least a call can cost us.
    - Before a request is sent the project needs `remaining >= assumed` (remaining = cap - charged - in-flight reservations),
      and once `charged >= cap` nothing more is sent.
    - After the reply the call is charged `max(reported, assumed)`; when the provider reported no cost, or the call failed
      after the request may have left, that is `assumed`. The record's `cost_usd` stays `null` in that case.
    - So one call can push the total past the cap by at most `reported - assumed` (when the reported cost is larger). That
      overshoot is written in the ledger line (`overshoot_micro_usd`) and the next call is refused.
    - The reservation is written to the ledger *before* sending (`reserved`) and the outcome after (`settled`). A `reserved`
      line with no `settled` line (the process died in between) counts as charged at its reserved amount on restart.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from pathlib import Path
from typing import Iterator

from .redact import mask_exact

MICRO = 1_000_000


class GatewayError(Exception):
    """Base class. Messages never contain the API key."""


class BudgetExceeded(GatewayError):
    """The project has no call budget left (or no budget at all). The request was not sent."""


def _finite_nonneg(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0


def to_micro(usd: float, rounding=ROUND_CEILING) -> int:
    """USD -> integer micro-dollars from the shortest decimal text of the float. Rounds up unless told otherwise (spent amounts)."""
    return int((Decimal(repr(float(usd))) * MICRO).to_integral_value(rounding=rounding))


@dataclass(frozen=True)
class Budget:
    """At least one limit is required. `max_cost_usd` also requires `assumed_call_cost_usd` > 0."""

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
        if self.max_cost_usd is not None and (self.assumed_call_cost_usd is None or to_micro(self.assumed_call_cost_usd) <= 0):
            raise ValueError("max_cost_usd needs assumed_call_cost_usd > 0 (held while a call is in flight, charged when the provider reports no cost)")
        if self.max_cost_usd is None and self.assumed_call_cost_usd is not None:
            raise ValueError("assumed_call_cost_usd only makes sense with max_cost_usd")

    @property
    def max_cost_micro(self) -> int | None:
        return None if self.max_cost_usd is None else to_micro(self.max_cost_usd, ROUND_FLOOR)  # never above the declared cap

    @property
    def assumed_micro(self) -> int:
        return 0 if self.assumed_call_cost_usd is None else to_micro(self.assumed_call_cost_usd)


@dataclass
class ProjectUsage:
    calls: int = 0  # requests sent (ok or error); rejected requests are not counted
    charged_micro: int = 0
    unknown_cost_calls: int = 0  # calls charged the declared assumption instead of a reported cost
    in_flight: int = 0
    reserved_micro: int = 0  # in-flight calls, held at the declared assumption until the real cost is known
    overshoot_micro: int = 0  # how far charged spend is past the cap (0 when within it)


class CostLedger:
    """Append-only JSONL, one line per request, `path=None` keeps nothing on disk.

    Replayed on start so the budget survives a restart. A line that does not parse stops the start-up: skipping it
    would forget spent budget. Only the exact key is masked (see `mask_exact`), never key-shaped text.
    """

    def __init__(self, path: Path | None = None, secrets: tuple[str, ...] = ()):
        self.path = path
        self._secrets = secrets

    def append(self, entry: dict) -> None:
        if self.path is None:
            return
        line = json.dumps(mask_exact(entry, self._secrets), ensure_ascii=False)
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
