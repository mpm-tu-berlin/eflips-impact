"""Tests for eflips.impact.tco.calculation (TCOCalculator and calculate_tco)."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from eflips.model import Scenario
from eflips.impact.tco.calculation import TCOCalculator
from eflips.impact.tco import calculate_tco


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
    assert "VEHICLE" in categories
    assert "BATTERY" in categories
    assert "INFRASTRUCTURE" in categories
    assert "STAFF" in categories
    assert "ENERGY" in categories
    assert "MAINTENANCE" in categories


def test_all_category_costs_positive(
    tco_session: Session, scenario: Scenario
) -> None:
    result = TCOCalculator(scenario).calculate()
    for category, cost in result.tco_by_type.items():
        assert cost >= 0.0, f"Negative cost in category {category}: {cost}"


# ---------------------------------------------------------------------------
# TCOCalculator — mileage
# ---------------------------------------------------------------------------


def test_vehicle_km_geq_revenue_km(
    tco_session: Session, scenario: Scenario
) -> None:
    calc = TCOCalculator(scenario)
    calc.calculate()
    assert calc.annual_vehicle_mileage > 0.0
    assert calc.annual_revenue_mileage > 0.0
    assert calc.annual_vehicle_mileage >= calc.annual_revenue_mileage


# ---------------------------------------------------------------------------
# TCOResult — specific cost
# ---------------------------------------------------------------------------


def test_tco_per_vehicle_km_positive(
    tco_session: Session, scenario: Scenario
) -> None:
    result = TCOCalculator(scenario).calculate()
    assert result.tco_per_vehicle_km > 0.0


def test_tco_per_revenue_km_geq_per_vehicle_km(
    tco_session: Session, scenario: Scenario
) -> None:
    result = TCOCalculator(scenario).calculate()
    # Revenue km ≤ vehicle km → cost per revenue km ≥ cost per vehicle km.
    assert result.tco_per_revenue_km >= result.tco_per_vehicle_km


def test_tco_by_type_per_km_sums_to_total(
    tco_session: Session, scenario: Scenario
) -> None:
    result = TCOCalculator(scenario).calculate()
    per_km = result.tco_by_type_per_km(use_revenue_km=False)
    total_km = result.annual_vehicle_mileage * result.project_duration
    reconstructed = sum(per_km.values()) * total_km
    assert reconstructed == pytest.approx(result.tco_over_project_duration, rel=1e-6)


# ---------------------------------------------------------------------------
# calculate_tco — public API
# ---------------------------------------------------------------------------


def test_calculate_tco_returns_dict(
    tco_session: Session, scenario: Scenario
) -> None:
    result = calculate_tco(scenario)
    assert isinstance(result, dict)
    assert len(result) > 0


def test_calculate_tco_all_values_positive(
    tco_session: Session, scenario: Scenario
) -> None:
    result = calculate_tco(scenario)
    for category, cost_per_km in result.items():
        assert cost_per_km >= 0.0, f"Negative cost/km for {category}: {cost_per_km}"


def test_calculate_tco_revenue_km_flag(
    tco_session: Session, scenario: Scenario
) -> None:
    """Revenue-km denominator yields higher per-km cost than vehicle-km."""
    per_vkm = calculate_tco(scenario, use_revenue_km=False)
    per_rkm = calculate_tco(scenario, use_revenue_km=True)
    total_per_vkm = sum(per_vkm.values())
    total_per_rkm = sum(per_rkm.values())
    assert total_per_rkm >= total_per_vkm
