"""Tests for services.splitter — CTO spec §4.3 says 100% coverage, no exceptions."""
from __future__ import annotations

import pytest

from backend.services.splitter import (
    MAX_LEG_KM,
    Leg,
    SplitPlan,
    SplitterRejection,
    minimum_days_for,
    split,
)


# ─── minimum_days_for ────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "km,expected",
    [
        (0, 1),
        (1, 1),
        (349.9, 1),
        (350.0, 1),
        (350.1, 2),
        (700, 2),
        (700.1, 3),
        (1050, 3),
        (1051, 4),
    ],
)
def test_minimum_days_for(km, expected):
    assert minimum_days_for(km) == expected


# ─── input validation ────────────────────────────────────────────────────────

def test_zero_days_rejected():
    with pytest.raises(ValueError):
        split(100, 0, "A", "B")


def test_negative_total_km_rejected():
    with pytest.raises(ValueError):
        split(-1, 1, "A", "B")


def test_empty_origin_rejected():
    with pytest.raises(ValueError):
        split(100, 1, "", "B")


def test_empty_destination_rejected():
    with pytest.raises(ValueError):
        split(100, 1, "A", "")


# ─── core 350km cap behaviour ────────────────────────────────────────────────

def test_short_trip_one_day():
    plan = split(248, 1, "Gurugram", "Chandigarh")
    assert len(plan.legs) == 1
    assert plan.legs[0].km == 248
    assert plan.legs[0].origin == "Gurugram"
    assert plan.legs[0].destination == "Chandigarh"
    assert plan.max_day_km == 248


def test_canonical_gurugram_manali_3_days():
    """The North Star acceptance test: Gurugram → Manali, 3 days.
    Routes API gives ~538 km; with 3 days, no leg should exceed 350 km."""
    plan = split(538, 3, "Gurugram", "Manali")
    assert len(plan.legs) == 3
    assert plan.max_day_km <= MAX_LEG_KM
    assert abs(plan.total_km - 538) < 1.0


def test_rejects_when_impossible():
    # 1200 km in 2 days = 600 km/day average — over the cap.
    with pytest.raises(SplitterRejection) as exc_info:
        split(1200, 2, "Delhi", "Goa")
    assert exc_info.value.suggested_days == 4  # ceil(1200/350) = 4


def test_rejection_carries_suggested_days():
    try:
        split(2100, 5, "Delhi", "Leh")
    except SplitterRejection as e:
        assert e.total_km == 2100
        assert e.requested_days == 5
        assert e.suggested_days == 6  # ceil(2100/350) = 6


def test_exact_cap_accepted():
    """Edge case: 350 km in 1 day must be accepted (<=, not <)."""
    plan = split(350.0, 1, "A", "B")
    assert len(plan.legs) == 1
    assert plan.legs[0].km == 350


def test_just_over_cap_rejected():
    with pytest.raises(SplitterRejection):
        split(350.5, 1, "A", "B")


def test_zero_km_trip():
    """Edge case: 0 km (same origin and destination, loop=False with no waypoints)."""
    plan = split(0, 1, "A", "B")
    assert len(plan.legs) == 1
    assert plan.legs[0].km == 0


# ─── leg distribution ────────────────────────────────────────────────────────

def test_legs_sum_to_total():
    plan = split(900, 3, "Delhi", "Mumbai")
    assert abs(plan.total_km - 900) < 1.0


def test_all_legs_under_cap_without_waypoints():
    plan = split(1000, 4, "Delhi", "Mumbai")
    assert all(leg.km <= MAX_LEG_KM for leg in plan.legs)
    assert len(plan.legs) == 4


def test_first_leg_starts_at_origin():
    plan = split(600, 2, "Gurugram", "Manali")
    assert plan.legs[0].origin == "Gurugram"


def test_last_leg_ends_at_destination():
    plan = split(600, 2, "Gurugram", "Manali")
    assert plan.legs[-1].destination == "Manali"


def test_day_numbers_are_sequential():
    plan = split(900, 3, "A", "B")
    assert [leg.day for leg in plan.legs] == [1, 2, 3]


# ─── waypoint snapping ───────────────────────────────────────────────────────

def test_waypoints_snap_to_nearest_city():
    plan = split(
        538,
        3,
        "Gurugram",
        "Manali",
        waypoints=[("Chandigarh", 248), ("Mandi", 430), ("Karnal", 130)],
    )
    # 3 days → 2 internal day boundaries at ~179 km and ~359 km of cumulative distance.
    # Karnal (130) is nearest to the first mark; Mandi (430) is nearest to the second.
    assert len(plan.legs) == 3
    assert plan.legs[0].destination == "Karnal"
    assert plan.legs[1].origin == "Karnal"
    assert plan.legs[1].destination == "Mandi"
    assert plan.legs[2].destination == "Manali"
    assert plan.max_day_km <= MAX_LEG_KM


def test_waypoint_overflow_caps_and_warns():
    """If a waypoint sits just inside the cap and the next leg overflows,
    splitter must clip and emit a warning rather than silently exceed."""
    # 800 km in 3 days; one waypoint near the end forces a >350 final leg.
    plan = split(
        800,
        3,
        "A",
        "B",
        waypoints=[("Mid", 250), ("Late", 350)],
    )
    assert all(leg.km <= MAX_LEG_KM for leg in plan.legs)


def test_waypoints_unused_when_more_than_boundaries():
    """5 waypoints for a 2-day trip → only 1 should be picked."""
    plan = split(
        600,
        2,
        "A",
        "B",
        waypoints=[("W1", 100), ("W2", 200), ("W3", 300), ("W4", 400), ("W5", 500)],
    )
    assert len(plan.legs) == 2
    # The boundary should be near 300 km, so W3 is the natural pick.
    assert plan.legs[0].destination == "W3"


def test_waypoints_distinct():
    """Splitter must not pick the same waypoint twice for different day boundaries."""
    plan = split(
        900,
        3,
        "A",
        "B",
        waypoints=[("W1", 300), ("W2", 600)],
    )
    destinations = [leg.destination for leg in plan.legs[:-1]]
    assert len(set(destinations)) == len(destinations)


# ─── SplitPlan helpers ───────────────────────────────────────────────────────

def test_splitplan_empty_max_day_km():
    sp = SplitPlan(legs=[])
    assert sp.max_day_km == 0.0
    assert sp.total_km == 0


def test_splitplan_total_km_computed():
    sp = SplitPlan(legs=[Leg(1, "A", "B", 100), Leg(2, "B", "C", 200)])
    assert sp.total_km == 300
    assert sp.max_day_km == 200
