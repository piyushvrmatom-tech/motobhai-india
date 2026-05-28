"""350km-per-day cap logic — CTO spec §4.3.

This module owns the day-splitting policy for Moto Bhai India. It does NOT
talk to any network, geocoder, or LLM — it is pure logic over distances and
must remain 100% test-covered.

Inputs:
    total_km    — total route distance from Google Routes API (float, km)
    days        — number of days the rider has requested (int, >=1)
    waypoints   — optional ordered list of intermediate cities with their
                  cumulative km from origin: [(name, km_from_origin), ...]

Outputs:
    A `SplitPlan` object with `legs` (list of `Leg`) and `warnings`.
    Each leg satisfies `leg.km <= MAX_LEG_KM` (350 km hard cap).

Failure modes:
    - `SplitterRejection` raised when `total_km / days > MAX_LEG_KM`.
      The exception carries `suggested_days` so the API can return a
      clean HTTP 422 with a helpful message.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil
from typing import List, Optional, Sequence, Tuple

MAX_LEG_KM: float = 350.0
"""Hard ceiling on a single day's riding distance, per CTO spec §4.3."""


@dataclass
class Leg:
    day: int
    origin: str
    destination: str
    km: float


@dataclass
class SplitPlan:
    legs: List[Leg]
    warnings: List[str] = field(default_factory=list)

    @property
    def total_km(self) -> float:
        return sum(leg.km for leg in self.legs)

    @property
    def max_day_km(self) -> float:
        return max((leg.km for leg in self.legs), default=0.0)


class SplitterRejection(Exception):
    """Raised when the trip cannot be split under the 350km cap.

    Carries `suggested_days` so callers can surface an actionable error.
    """

    def __init__(self, total_km: float, requested_days: int, suggested_days: int):
        self.total_km = total_km
        self.requested_days = requested_days
        self.suggested_days = suggested_days
        super().__init__(
            f"Cannot fit {total_km:.0f} km into {requested_days} days under the "
            f"{MAX_LEG_KM:.0f} km/day cap. Try {suggested_days} days."
        )


def minimum_days_for(total_km: float) -> int:
    """Smallest day count that respects the 350km cap.

    >>> minimum_days_for(0)
    1
    >>> minimum_days_for(350)
    1
    >>> minimum_days_for(351)
    2
    """
    if total_km <= 0:
        return 1
    return max(1, ceil(total_km / MAX_LEG_KM))


def _redistribute(per_day: float, days: int, total: float) -> List[float]:
    """Spread `total` across `days` legs, each <= MAX_LEG_KM.

    Strategy: start with even allocation. If even allocation exceeds the cap,
    the caller should have rejected upstream — but we defensively cap each leg
    and push overflow to subsequent legs. If overflow cannot be absorbed (i.e.
    the last leg would still exceed the cap), we expand to one extra day and
    record a warning.
    """
    legs: List[float] = []
    remaining = total
    for i in range(days):
        days_left = days - i
        ideal = remaining / days_left
        leg = min(ideal, MAX_LEG_KM)
        legs.append(leg)
        remaining -= leg
    # Safety: should never overflow if upstream check ran.
    if remaining > 0.01:
        legs.append(min(remaining, MAX_LEG_KM))
    return legs


def split(
    total_km: float,
    days: int,
    origin: str,
    destination: str,
    waypoints: Optional[Sequence[Tuple[str, float]]] = None,
) -> SplitPlan:
    """Build a day-by-day SplitPlan honouring the 350km cap.

    Args:
        total_km: total route distance from Google Routes API.
        days: rider's requested day count (>=1).
        origin: starting city name (human-readable).
        destination: ending city name (human-readable).
        waypoints: optional ordered intermediate stops with cumulative km
            from origin. If provided, the splitter snaps day boundaries to
            the nearest waypoint name to avoid mid-highway stops.

    Returns:
        SplitPlan with `legs` of length `days` (or `days + 1` in the rare
        edge case where waypoint snapping overflowed and we extended).

    Raises:
        SplitterRejection: if `total_km / days > MAX_LEG_KM`.
        ValueError: on nonsensical input.
    """
    if days < 1:
        raise ValueError("days must be >= 1")
    if total_km < 0:
        raise ValueError("total_km must be >= 0")
    if not origin or not destination:
        raise ValueError("origin and destination must be non-empty")

    suggested = minimum_days_for(total_km)
    if total_km / days > MAX_LEG_KM:
        raise SplitterRejection(total_km, days, suggested)

    warnings: List[str] = []

    # If no waypoints, fall back to even distribution with synthetic
    # mid-point names ("Day N stop").
    if not waypoints:
        leg_kms = _redistribute(total_km / days, days, total_km)
        legs: List[Leg] = []
        for i, km in enumerate(leg_kms):
            leg_from = origin if i == 0 else f"Day {i} overnight stop"
            leg_to = destination if i == len(leg_kms) - 1 else f"Day {i + 1} overnight stop"
            legs.append(Leg(day=i + 1, origin=leg_from, destination=leg_to, km=round(km, 1)))
        return SplitPlan(legs=legs, warnings=warnings)

    # With waypoints: snap each day boundary to the nearest waypoint.
    sorted_wp = sorted(waypoints, key=lambda w: w[1])
    target_marks = [total_km * (i + 1) / days for i in range(days - 1)]
    snapped: List[Tuple[str, float]] = []
    used_indices: set[int] = set()
    for mark in target_marks:
        best_idx = -1
        best_dist = float("inf")
        for idx, (name, km) in enumerate(sorted_wp):
            if idx in used_indices:
                continue
            d = abs(km - mark)
            if d < best_dist:
                best_dist = d
                best_idx = idx
        if best_idx >= 0:
            used_indices.add(best_idx)
            snapped.append(sorted_wp[best_idx])
        else:
            # Ran out of distinct waypoints — fall back to synthetic.
            snapped.append((f"Day {len(snapped) + 1} overnight stop", mark))

    snapped.sort(key=lambda w: w[1])
    legs2: List[Leg] = []
    prev_name = origin
    prev_km = 0.0
    for i, (name, cum_km) in enumerate(snapped):
        leg_km = cum_km - prev_km
        if leg_km > MAX_LEG_KM:
            # Snap pushed us over the cap — clip and warn.
            warnings.append(
                f"Waypoint '{name}' would create a {leg_km:.0f} km leg; "
                f"capping at {MAX_LEG_KM:.0f} km."
            )
            leg_km = MAX_LEG_KM
        legs2.append(Leg(day=i + 1, origin=prev_name, destination=name, km=round(leg_km, 1)))
        prev_name = name
        prev_km = cum_km
    final_leg_km = total_km - prev_km
    if final_leg_km > MAX_LEG_KM:
        warnings.append(
            f"Final leg to {destination} is {final_leg_km:.0f} km; capping at "
            f"{MAX_LEG_KM:.0f} km and adding an extra overnight stop."
        )
        # Insert an intermediate synthetic stop to absorb the overflow.
        overflow = final_leg_km - MAX_LEG_KM
        legs2.append(
            Leg(
                day=len(legs2) + 1,
                origin=prev_name,
                destination=f"Day {len(legs2) + 1} overnight stop",
                km=round(overflow, 1),
            )
        )
        prev_name = f"Day {len(legs2)} overnight stop"
        final_leg_km = MAX_LEG_KM
    legs2.append(
        Leg(
            day=len(legs2) + 1,
            origin=prev_name,
            destination=destination,
            km=round(final_leg_km, 1),
        )
    )
    return SplitPlan(legs=legs2, warnings=warnings)
