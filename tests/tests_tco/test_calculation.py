"""Tests for eflips.impact.tco.calculation (TCOCalculator and calculate_tco)."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from eflips.model import Scenario
from eflips.impact.tco.calculation import TCOCalculator
from eflips.impact.tco import calculate_tco
from eflips.impact.tco.cost_items import CapexItemType, OpexItemType


# ---------------------------------------------------------------------------
# TCOCalculator — basic sanity
# ---------------------------------------------------------------------------


def test_calculator_runs(tco_session: Session, scenario: Scenario) -> None:
    calc = TCOCalculator(scenario)
    result = calc.calculate()
    assert result is not None


def test_capex_positive(tco_session: Session, scenario: Scenario) -> None:
    result = TCOCalculator(scenario).calculate()
    assert result.total_capex > 0.0


def test_opex_positive(tco_session: Session, scenario: Scenario) -> None:
    result = TCOCalculator(scenario).calculate()
    assert result.total_opex > 0.0


def test_total_tco_equals_capex_plus_opex(
    tco_session: Session, scenario: Scenario
) -> None:
    result = TCOCalculator(scenario).calculate()
    assert result.tco_over_project_duration == pytest.approx(
        result.total_capex + result.total_opex
    )


# ---------------------------------------------------------------------------
# TCOCalculator — cost categories
# ---------------------------------------------------------------------------


def test_expected_cost_categories_present(
    tco_session: Session, scenario: Scenario
) -> None:
    result = TCOCalculator(scenario).calculate()
    categories = set(result.tco_by_type.keys())
    assert CapexItemType.VEHICLE in categories
    assert CapexItemType.BATTERY in categories
    assert CapexItemType.INFRASTRUCTURE in categories
    assert OpexItemType.STAFF in categories
    assert OpexItemType.ENERGY in categories
    assert OpexItemType.MAINTENANCE in categories


def test_all_category_costs_positive(tco_session: Session, scenario: Scenario) -> None:
    result = TCOCalculator(scenario).calculate()
    for category, cost in result.tco_by_type.items():
        assert cost >= 0.0, f"Negative cost in category {category}: {cost}"


# ---------------------------------------------------------------------------
# TCOCalculator — mileage
# ---------------------------------------------------------------------------


def test_vehicle_km_geq_revenue_km(tco_session: Session, scenario: Scenario) -> None:
    calc = TCOCalculator(scenario)
    calc.calculate()
    assert calc.annual_vehicle_km > 0.0
    assert calc.annual_revenue_km > 0.0
    assert calc.annual_vehicle_km >= calc.annual_revenue_km


# ---------------------------------------------------------------------------
# TCOResult — specific cost
# ---------------------------------------------------------------------------


def test_tco_per_vehicle_km_positive(tco_session: Session, scenario: Scenario) -> None:
    result = TCOCalculator(scenario).calculate()
    assert result.tco_per_vehicle_km > 0.0


def test_tco_per_revenue_km_geq_per_vehicle_km(
    tco_session: Session, scenario: Scenario
) -> None:
    result = TCOCalculator(scenario).calculate()
    # Revenue km ≤ vehicle km → cost per revenue km ≥ cost per vehicle km.
    assert result.tco_per_revenue_km >= result.tco_per_vehicle_km


def test_tco_by_type_per_vehicle_km_sums_to_total(
    tco_session: Session, scenario: Scenario
) -> None:
    result = TCOCalculator(scenario).calculate()
    per_km = result.tco_by_type_per_vehicle_km
    total_km = result.annual_vehicle_km * result.project_duration
    reconstructed = sum(per_km.values()) * total_km
    assert reconstructed == pytest.approx(result.tco_over_project_duration, rel=1e-6)


def test_tco_by_type_per_revenue_km_sums_to_total(
    tco_session: Session, scenario: Scenario
) -> None:
    result = TCOCalculator(scenario).calculate()
    per_km = result.tco_by_type_per_revenue_km
    total_km = result.annual_revenue_km * result.project_duration
    reconstructed = sum(per_km.values()) * total_km
    assert reconstructed == pytest.approx(result.tco_over_project_duration, rel=1e-6)


# ---------------------------------------------------------------------------
# calculate_tco — public API
# ---------------------------------------------------------------------------


def test_calculate_tco_returns_result(tco_session: Session, scenario: Scenario) -> None:
    from eflips.impact.tco.dataclasses import TCOResult

    result = calculate_tco(scenario)
    assert isinstance(result, TCOResult)
    assert len(result.tco_by_type) > 0


def test_calculate_tco_all_values_positive(
    tco_session: Session, scenario: Scenario
) -> None:
    result = calculate_tco(scenario)
    for category, cost in result.tco_by_type.items():
        assert cost >= 0.0, f"Negative cost for {category}: {cost}"


def test_calculate_tco_revenue_km_geq_vehicle_km(
    tco_session: Session, scenario: Scenario
) -> None:
    """Revenue-km denominator yields higher per-km cost than vehicle-km."""
    result = calculate_tco(scenario)
    assert result.tco_per_revenue_km >= result.tco_per_vehicle_km
