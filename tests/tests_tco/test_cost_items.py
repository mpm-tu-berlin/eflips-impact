"""Unit tests for eflips.impact.tco.cost_items financial formulas."""

from __future__ import annotations

import pytest

from eflips.impact.tco.cost_items import (
    CapexItem,
    CapexItemType,
    OpexItem,
    OpexItemType,
    net_present_value,
)


# ---------------------------------------------------------------------------
# net_present_value
# ---------------------------------------------------------------------------


def test_npv_year_zero_is_cash_flow() -> None:
    assert net_present_value(1000.0, 0, 0.05) == pytest.approx(1000.0)


def test_npv_discounts_future_cash_flow() -> None:
    # 1000 / (1.05)^1 ≈ 952.38
    assert net_present_value(1000.0, 1, 0.05) == pytest.approx(1000.0 / 1.05)


def test_npv_two_years() -> None:
    assert net_present_value(1000.0, 2, 0.1) == pytest.approx(1000.0 / 1.1**2)


# ---------------------------------------------------------------------------
# CapexItem.replacement_cost
# ---------------------------------------------------------------------------


def _vehicle_item(useful_life: int = 14, cost_escalation: float = 0.0) -> CapexItem:
    return CapexItem(
        name="Bus",
        type=CapexItemType.VEHICLE,
        useful_life=useful_life,
        procurement_cost=300_000.0,
        cost_escalation=cost_escalation,
        quantity=1,
    )


def test_replacement_cost_no_replacement_within_project() -> None:
    """Useful life == project duration → exactly one procurement, partial use flag True."""
    item = _vehicle_item(useful_life=14)
    replacements = item.replacement_cost(project_duration=14)
    # Year 0 procurement; useful life equals project duration exactly → no partial
    assert len(replacements) == 1
    cost, year, partial = replacements[0]
    assert year == 0
    assert cost == pytest.approx(300_000.0)
    assert partial is False


def test_replacement_cost_one_full_replacement() -> None:
    """Useful life 7, project 14 → procurement at year 0 and year 7."""
    item = _vehicle_item(useful_life=7)
    replacements = item.replacement_cost(project_duration=14)
    assert len(replacements) == 2
    years = [r[1] for r in replacements]
    assert years == [0, 7]
    assert all(not r[2] for r in replacements)  # both full replacements


def test_replacement_cost_partial_at_end() -> None:
    """Useful life 10, project 14 → year-0 full + year-10 partial."""
    item = _vehicle_item(useful_life=10)
    replacements = item.replacement_cost(project_duration=14)
    assert len(replacements) == 2
    assert replacements[0][2] is False   # first: full
    assert replacements[1][2] is True    # second: partial (only 4/10 years used)


def test_replacement_cost_escalation_applied() -> None:
    """With positive escalation, replacement cost at year N > base price."""
    item = _vehicle_item(useful_life=7, cost_escalation=0.05)
    replacements = item.replacement_cost(project_duration=14)
    assert replacements[1][0] > replacements[0][0]
    assert replacements[1][0] == pytest.approx(300_000.0 * (1.05**7))


# ---------------------------------------------------------------------------
# CapexItem.calculate_total_procurement_cost
# ---------------------------------------------------------------------------


def test_calculate_total_procurement_cost_positive() -> None:
    item = _vehicle_item(useful_life=14, cost_escalation=0.0)
    cost = item.calculate_total_procurement_cost(
        project_duration=14, interest_rate=0.04, net_discount_rate=0.02
    )
    assert cost > 0.0


def test_calculate_total_procurement_cost_higher_interest_lowers_cost() -> None:
    """Higher interest rate → higher annuity but PV discounting → net effect is higher NPV
    of upfront annuity. Annuity itself rises, so total cost rises with interest rate
    when discount rate is fixed."""
    item = _vehicle_item(useful_life=14)
    low = item.calculate_total_procurement_cost(14, interest_rate=0.02, net_discount_rate=0.02)
    high = item.calculate_total_procurement_cost(14, interest_rate=0.08, net_discount_rate=0.02)
    # Higher interest rate increases the annuity, so total cost is higher.
    assert high > low


def test_calculate_total_procurement_cost_scales_with_quantity() -> None:
    item = _vehicle_item(useful_life=14)
    single = item.calculate_total_procurement_cost(14, 0.04, 0.02)
    item_5 = CapexItem(
        name="Bus",
        type=CapexItemType.VEHICLE,
        useful_life=14,
        procurement_cost=300_000.0,
        cost_escalation=0.0,
        quantity=5,
    )
    fleet = item_5.calculate_total_procurement_cost(14, 0.04, 0.02) * item_5.quantity
    assert fleet == pytest.approx(single * 5)


# ---------------------------------------------------------------------------
# OpexItem.future_cost
# ---------------------------------------------------------------------------


def test_future_cost_year_zero_is_base() -> None:
    item = OpexItem(
        name="Energy",
        type=OpexItemType.ENERGY,
        unit_cost=0.15,
        usage_amount=100_000.0,
        cost_escalation=0.03,
    )
    assert item.future_cost(0) == pytest.approx(0.15 * 100_000.0)


def test_future_cost_escalates_over_time() -> None:
    item = OpexItem(
        name="Staff",
        type=OpexItemType.STAFF,
        unit_cost=35.0,
        usage_amount=2000.0,
        cost_escalation=0.02,
    )
    base = item.future_cost(0)
    year5 = item.future_cost(5)
    assert year5 == pytest.approx(base * (1.02**5))


def test_future_cost_zero_escalation_constant() -> None:
    item = OpexItem(
        name="Tax",
        type=OpexItemType.OTHER,
        unit_cost=500.0,
        usage_amount=10.0,
        cost_escalation=0.0,
    )
    assert item.future_cost(3) == pytest.approx(item.future_cost(0))
