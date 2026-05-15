"""Tests for the intermediate openLCA data layer.

Covers:
1. ``YearSeries`` interpolation (exact, between, clamping, single point)
2. ``OpenLCAData`` dict roundtrip and ``from_json_lca``
3. Population logic
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from eflips.impact.lca.open_lca_data import (
    ChargingPointTypeOverrides,
    OpenLCAData,
    VehicleTypeOverrides,
    YearSeries,
    init_lca_params,
    populate_lca_parameters_from_data,
)
from eflips.impact.lca.util import DefaultImpactVector

DEFAULTS_DIR = Path(__file__).parent / "data"

# ===================================================================
# Helpers
# ===================================================================


def _iv(gwp: float) -> DefaultImpactVector:
    """Create a ``DefaultImpactVector`` with only gwp set."""
    return DefaultImpactVector(gwp=gwp)


def _make_open_lca_data() -> OpenLCAData:
    """Build a minimal ``OpenLCAData`` for testing."""
    return OpenLCAData(
        ecoinvent_version="3.9.1",
        lcia_method_set="EF 3.1",
        description="Test dataset",
        created_at="2025-01-01T00:00:00Z",
        chassis_per_kg=_iv(10.0),
        electric_motor_per_kg=_iv(5.0),
        diesel_motor_per_unit=_iv(8000.0),
        lfp_battery_per_kg=_iv(100.0),
        nmc_battery_per_kg=_iv(120.0),
        electricity_per_kwh=YearSeries(
            data={
                2025: _iv(0.4),
                2030: _iv(0.3),
                2035: _iv(0.2),
            }
        ),
        diesel_per_kg=_iv(3.7),
        maintenance_iceb_per_year=_iv(1000.0),
        maintenance_beb_per_year=_iv(750.0),
        control_unit=_iv(500.0),
        power_unit=_iv(9000.0),
        user_unit=_iv(500.0),
        transformer=_iv(2000.0),
        concrete_per_m3=_iv(300.0),
        diesel_motor_mass_kg=1900.0,
        efficiency_mv_to_lv=0.99,
        efficiency_lv_ac_to_dc=0.95,
        battery_lifetime_years=8.0,
        beb_maintenance_reduction_factor=0.75,
        power_unit_rated_power_kw=150.0,
        transformer_ref_power_kw=315.0,
        eta_avail=0.9,
    )


# ===================================================================
# YearSeries tests
# ===================================================================


class TestYearSeries:
    """Tests for ``YearSeries`` interpolation."""

    def test_exact_match(self) -> None:
        """Exact year returns the stored vector."""
        ys = YearSeries(data={2025: _iv(0.4), 2030: _iv(0.3)})
        result = ys.at_year(2025)
        assert result.gwp == pytest.approx(0.4)

    def test_interpolation_midpoint(self) -> None:
        """Midpoint between two years returns the average."""
        ys = YearSeries(data={2020: _iv(1.0), 2030: _iv(0.0)})
        result = ys.at_year(2025)
        assert result.gwp == pytest.approx(0.5)

    def test_interpolation_quarter(self) -> None:
        """Quarter point interpolation."""
        ys = YearSeries(data={2020: _iv(0.0), 2030: _iv(1.0)})
        result = ys.at_year(2022)  # t = 0.2
        assert result.gwp == pytest.approx(0.2)

    def test_clamp_below(self) -> None:
        """Year before range clamps to first and warns."""
        ys = YearSeries(data={2025: _iv(0.4), 2030: _iv(0.3)})
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = ys.at_year(2020)
            assert len(w) == 1
            assert "before the earliest" in str(w[0].message)
        assert result.gwp == pytest.approx(0.4)

    def test_clamp_above(self) -> None:
        """Year after range clamps to last and warns."""
        ys = YearSeries(data={2025: _iv(0.4), 2030: _iv(0.3)})
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = ys.at_year(2040)
            assert len(w) == 1
            assert "after the latest" in str(w[0].message)
        assert result.gwp == pytest.approx(0.3)

    def test_single_point_exact(self) -> None:
        """Single data point returns it for exact match."""
        ys = YearSeries(data={2025: _iv(0.4)})
        result = ys.at_year(2025)
        assert result.gwp == pytest.approx(0.4)

    def test_single_point_clamp(self) -> None:
        """Single data point clamps for any other year."""
        ys = YearSeries(data={2025: _iv(0.4)})
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = ys.at_year(2030)
            assert len(w) == 1
        assert result.gwp == pytest.approx(0.4)

    def test_empty_raises(self) -> None:
        """Empty series raises ValueError."""
        ys = YearSeries(data={})
        with pytest.raises(ValueError, match="empty"):
            ys.at_year(2025)

    def test_roundtrip(self) -> None:
        """to_dict/from_dict roundtrip preserves data."""
        ys = YearSeries(data={2025: _iv(0.4), 2030: _iv(0.3)})
        restored = YearSeries.from_dict(ys.to_dict())
        assert restored.at_year(2025).gwp == pytest.approx(0.4)
        assert restored.at_year(2030).gwp == pytest.approx(0.3)

    def test_all_categories_interpolated(self) -> None:
        """All 8 categories are interpolated, not just gwp."""
        iv_lo = DefaultImpactVector(
            gwp=1.0,
            pm=2.0,
            pocp=3.0,
            ap=4.0,
            ep_freshwater=5.0,
            ep_marine=6.0,
            fuel=7.0,
            water=8.0,
        )
        iv_hi = DefaultImpactVector(
            gwp=2.0,
            pm=4.0,
            pocp=6.0,
            ap=8.0,
            ep_freshwater=10.0,
            ep_marine=12.0,
            fuel=14.0,
            water=16.0,
        )
        ys = YearSeries(data={2020: iv_lo, 2030: iv_hi})
        result = ys.at_year(2025)
        assert result.gwp == pytest.approx(1.5)
        assert result.pm == pytest.approx(3.0)
        assert result.water == pytest.approx(12.0)


# ===================================================================
# OpenLCAData JSON roundtrip tests
# ===================================================================


class TestOpenLCADataRoundtrip:
    """Tests for ``OpenLCAData`` serialization."""


# ===================================================================
# from_json_lca tests
# ===================================================================


class TestFromJsonLca:
    """Tests for ``OpenLCAData.from_json_lca``."""

    LCA_JSON = Path(__file__).parent / "data" / "lca.json"

    def test_loads_without_error(self) -> None:
        """File parses and constructs an OpenLCAData."""
        d = OpenLCAData.from_json_lca(self.LCA_JSON)
        assert d is not None

    def test_metadata(self) -> None:
        """Metadata fields are populated from the metadata section."""
        d = OpenLCAData.from_json_lca(self.LCA_JSON)
        assert d.ecoinvent_version == "3.9.1"
        assert d.lcia_method_set == "EF 3.1"

    def test_chassis_matches_bus_results(self) -> None:
        """chassis_per_kg is copied verbatim from the source."""
        d = OpenLCAData.from_json_lca(self.LCA_JSON)
        assert d.chassis_per_kg.gwp == pytest.approx(7.1450240595)

    def test_lfp_battery_sums_production_and_eol(self) -> None:
        """lfp_battery_per_kg = production + eol_transport + eol_disassembly."""
        d = OpenLCAData.from_json_lca(self.LCA_JSON)
        expected_gwp = 14.3224443242 + 0.6391297263 + (-0.2070739303)
        assert d.lfp_battery_per_kg.gwp == pytest.approx(expected_gwp)

    def test_nmc_battery_sums_production_and_eol(self) -> None:
        """nmc_battery_per_kg = production + eol_transport + eol_disassembly."""
        d = OpenLCAData.from_json_lca(self.LCA_JSON)
        expected_gwp = 20.1705783869 + 0.6391297263 + (-0.1142217733)
        assert d.nmc_battery_per_kg.gwp == pytest.approx(expected_gwp)

    def test_electricity_converted_to_per_kwh(self) -> None:
        """Electricity values are multiplied by 3.6 (MJ → kWh)."""
        d = OpenLCAData.from_json_lca(self.LCA_JSON)
        assert d.electricity_per_kwh.at_year(2023).gwp == pytest.approx(
            0.1353671996 * 3.6
        )

    def test_electricity_year_series_has_three_years(self) -> None:
        """All three years (2023, 2030, 2050) are present."""
        d = OpenLCAData.from_json_lca(self.LCA_JSON)
        assert set(d.electricity_per_kwh.data.keys()) == {2023, 2030, 2050}

    def test_control_unit_sums_production_and_eol(self) -> None:
        """control_unit = production + EoL."""
        d = OpenLCAData.from_json_lca(self.LCA_JSON)
        expected_gwp = 1345.9444964049 + (-695.6806515338)
        assert d.control_unit.gwp == pytest.approx(expected_gwp)

    def test_power_unit_sums_production_and_eol(self) -> None:
        """power_unit = production + EoL."""
        d = OpenLCAData.from_json_lca(self.LCA_JSON)
        expected_gwp = 6103.5150927163 + (-1586.3434417575)
        assert d.power_unit.gwp == pytest.approx(expected_gwp)

    def test_infrastructure_scalars(self) -> None:
        """Ref-power scalars and battery lifetime are read correctly."""
        d = OpenLCAData.from_json_lca(self.LCA_JSON)
        assert d.power_unit_rated_power_kw == pytest.approx(350.0)
        assert d.transformer_ref_power_kw == pytest.approx(315.0)
        assert d.battery_lifetime_years == pytest.approx(8.0)
        assert d.diesel_motor_mass_kg == pytest.approx(1900.0)


# ===================================================================
# Population logic tests
# ===================================================================


class TestPopulationLogic:
    """Tests for ``populate_lca_parameters_from_data``."""

    def test_populate_from_data(self, db_session: pytest.fixture) -> None:  # type: ignore[type-arg]
        """Populating from OpenLCAData writes expected lca_parameters."""
        from eflips.model import VehicleType

        data = _make_open_lca_data()
        overrides = {
            "EN": VehicleTypeOverrides(
                motor_rated_power_kw=200.0,
                vehicle_lifetime_years=12.0,
                motor_power_to_weight_ratio_kw_per_kg=2.0,
                average_consumption_kwh_per_km=1.2,
            ),
            "GN": VehicleTypeOverrides(
                motor_rated_power_kw=300.0,
                vehicle_lifetime_years=12.0,
                motor_power_to_weight_ratio_kw_per_kg=2.0,
                average_consumption_kwh_per_km=1.8,
            ),
            "DD": VehicleTypeOverrides(
                motor_rated_power_kw=250.0,
                vehicle_lifetime_years=12.0,
                motor_power_to_weight_ratio_kw_per_kg=2.0,
                average_consumption_kwh_per_km=1.5,
            ),
        }

        populate_lca_parameters_from_data(
            session=db_session,
            scenario_id=1,
            open_lca_data=data,
            year=2025,
            vehicle_type_overrides=overrides,
            cpt_overrides=ChargingPointTypeOverrides(
                infrastructure_lifetime_years=20.0,
                foundation_volume_per_point_m3=3.96,
            ),
        )

        vtype = db_session.query(VehicleType).filter_by(id=12).one()
        assert vtype.lca_parameters is not None
        params = vtype.lca_parameters
        # Chassis EF should match openLCA data
        assert params["chassis_emission_factors_per_kg"]["gwp"] == pytest.approx(10.0)
        # Motor EF should match
        assert params["motor_emission_factors_per_kg"]["gwp"] == pytest.approx(5.0)
        # Electricity should be from year 2025
        assert params["electricity_emission_factors_per_kwh"]["gwp"] == pytest.approx(
            0.4
        )
        # BEB motor mass is not stored (derived at calc time from power/ratio)
        assert params["motor_mass_kg"] is None
        # Consumption override applied
        assert params["average_consumption_kwh_per_km"] == pytest.approx(1.2)

    def test_interpolated_electricity_year(self, db_session: pytest.fixture) -> None:  # type: ignore[type-arg]
        """Populating with an interpolated year uses correct electricity EF."""
        from eflips.model import VehicleType

        data = _make_open_lca_data()
        overrides = {
            "EN": VehicleTypeOverrides(
                motor_rated_power_kw=200.0,
                vehicle_lifetime_years=12.0,
                motor_power_to_weight_ratio_kw_per_kg=2.0,
                average_consumption_kwh_per_km=1.2,
            ),
        }

        populate_lca_parameters_from_data(
            session=db_session,
            scenario_id=1,
            open_lca_data=data,
            year=2027,  # Between 2025 (0.4) and 2030 (0.3) → t=0.4 → 0.36
            vehicle_type_overrides=overrides,
            cpt_overrides=ChargingPointTypeOverrides(
                infrastructure_lifetime_years=20.0,
                foundation_volume_per_point_m3=3.96,
            ),
        )

        vtype = db_session.query(VehicleType).filter_by(id=12).one()
        assert vtype.lca_parameters is not None
        expected_gwp = 0.4 * (1 - 0.4) + 0.3 * 0.4  # = 0.36
        assert vtype.lca_parameters["electricity_emission_factors_per_kwh"][
            "gwp"
        ] == pytest.approx(expected_gwp)

    def test_missing_override_warns(self, db_session: pytest.fixture) -> None:  # type: ignore[type-arg]
        """VehicleTypes absent from vehicle_type_overrides emit a UserWarning."""
        data = _make_open_lca_data()
        # Only override EN (id=12); GN (id=13) and DD (id=14) are omitted.
        overrides = {
            "EN": VehicleTypeOverrides(
                motor_rated_power_kw=200.0,
                vehicle_lifetime_years=12.0,
                motor_power_to_weight_ratio_kw_per_kg=2.0,
                average_consumption_kwh_per_km=1.2,
            ),
        }

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            populate_lca_parameters_from_data(
                session=db_session,
                scenario_id=1,
                open_lca_data=data,
                year=2025,
                vehicle_type_overrides=overrides,
                cpt_overrides=ChargingPointTypeOverrides(
                    infrastructure_lifetime_years=20.0,
                    foundation_volume_per_point_m3=3.96,
                ),
            )

        missing_name_shorts = {"GN", "DD"}
        warned_name_shorts = {
            w.message.args[0].split()[1].strip("'")  # type: ignore[union-attr]
            for w in caught
            if issubclass(w.category, UserWarning)
            and "vehicle_type_overrides" in str(w.message)
        }
        assert warned_name_shorts == missing_name_shorts

    def test_zero_transformer_concrete_warns(self) -> None:
        """make_charging_point_type_lca_parameters warns when transformer or concrete_per_m3 are zero."""
        data = _make_open_lca_data()
        data = OpenLCAData(
            **{
                **data.__dict__,
                "transformer": DefaultImpactVector.zero(),
                "concrete_per_m3": DefaultImpactVector.zero(),
            }
        )

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            data.make_charging_point_type_lca_parameters(
                ChargingPointTypeOverrides(
                    infrastructure_lifetime_years=20.0,
                    foundation_volume_per_point_m3=3.96,
                )
            )

        user_warnings = [
            str(w.message) for w in caught if issubclass(w.category, UserWarning)
        ]
        assert any("transformer" in msg for msg in user_warnings)
        assert any("concrete" in msg for msg in user_warnings)

    def test_cpt_overrides_applied(self) -> None:
        """make_charging_point_type_lca_parameters applies ChargingPointTypeOverrides."""
        data = _make_open_lca_data()
        overrides = ChargingPointTypeOverrides(
            infrastructure_lifetime_years=25.0,
            foundation_volume_per_point_m3=5.0,
        )
        params = data.make_charging_point_type_lca_parameters(overrides)
        assert params.infrastructure_lifetime_years == pytest.approx(25.0)
        assert params.foundation_volume_per_point_m3 == pytest.approx(5.0)

    def test_cpt_overrides_values_used(self) -> None:
        """make_charging_point_type_lca_parameters uses the values from ChargingPointTypeOverrides."""
        data = _make_open_lca_data()
        overrides = ChargingPointTypeOverrides(
            infrastructure_lifetime_years=15.0,
            foundation_volume_per_point_m3=0.0,
        )
        params = data.make_charging_point_type_lca_parameters(overrides)
        assert params.infrastructure_lifetime_years == pytest.approx(15.0)
        assert params.foundation_volume_per_point_m3 == pytest.approx(0.0)


class TestInitLCAParams:
    """Tests for ``init_lca_params``."""

    def test_writes_all_entity_lca_parameters(
        self, db_session: pytest.fixture  # type: ignore[type-arg]
    ) -> None:
        """init_lca_params writes lca_parameters to VehicleType, BatteryType, and CPT."""
        from eflips.model import BatteryType, ChargingPointType, VehicleType

        from tests.tests_lca.conftest import SCENARIO_ID

        scenario = (
            db_session.query(__import__("eflips.model", fromlist=["Scenario"]).Scenario)
            .filter_by(id=SCENARIO_ID)
            .one()
        )

        init_lca_params(
            scenario=scenario,
            lca_json_path=DEFAULTS_DIR / "lca.json",
            overrides_json_path=DEFAULTS_DIR / "lca_overrides.json",
        )

        vtypes = db_session.query(VehicleType).filter_by(scenario_id=SCENARIO_ID).all()
        for vt in vtypes:
            assert (
                vt.lca_parameters is not None
            ), f"VehicleType {vt.name_short!r} has no lca_parameters"

        bt = db_session.query(BatteryType).filter_by(scenario_id=SCENARIO_ID).first()
        assert bt is not None and bt.lca_parameters is not None

        cpt = (
            db_session.query(ChargingPointType)
            .filter_by(scenario_id=SCENARIO_ID)
            .first()
        )
        assert cpt is not None and cpt.lca_parameters is not None

    def test_vehicle_type_override_values_applied(
        self, db_session: pytest.fixture  # type: ignore[type-arg]
    ) -> None:
        """init_lca_params writes the correct consumption from lca_overrides.json."""
        from eflips.model import VehicleType

        from tests.tests_lca.conftest import SCENARIO_ID

        scenario = (
            db_session.query(__import__("eflips.model", fromlist=["Scenario"]).Scenario)
            .filter_by(id=SCENARIO_ID)
            .one()
        )

        init_lca_params(
            scenario=scenario,
            lca_json_path=DEFAULTS_DIR / "lca.json",
            overrides_json_path=DEFAULTS_DIR / "lca_overrides.json",
        )

        # EN has average_consumption_kwh_per_km: 1.48 in lca_overrides.json
        en = (
            db_session.query(VehicleType)
            .filter_by(scenario_id=SCENARIO_ID, name_short="EN")
            .one()
        )
        assert en.lca_parameters["average_consumption_kwh_per_km"] == pytest.approx(1.48)

    def test_cpt_overrides_infrastructure_lifetime(
        self, db_session: pytest.fixture  # type: ignore[type-arg]
    ) -> None:
        """init_lca_params applies infrastructure_lifetime_years from opportunity overrides."""
        from eflips.model import ChargingPointType

        from tests.tests_lca.conftest import SCENARIO_ID

        scenario = (
            db_session.query(__import__("eflips.model", fromlist=["Scenario"]).Scenario)
            .filter_by(id=SCENARIO_ID)
            .one()
        )

        init_lca_params(
            scenario=scenario,
            lca_json_path=DEFAULTS_DIR / "lca.json",
            overrides_json_path=DEFAULTS_DIR / "lca_overrides.json",
        )

        cpt = (
            db_session.query(ChargingPointType)
            .filter_by(scenario_id=SCENARIO_ID)
            .first()
        )
        assert cpt is not None
        # lca_overrides.json sets infrastructure_lifetime_years: 20.0
        assert cpt.lca_parameters["infrastructure_lifetime_years"] == pytest.approx(20.0)

    def test_missing_beb_override_warns_and_returns(
        self, db_session: pytest.fixture, tmp_path: Path  # type: ignore[type-arg]
    ) -> None:
        """init_lca_params warns and returns None if a BEB VehicleType lacks overrides."""
        import json

        from tests.tests_lca.conftest import SCENARIO_ID

        # Write an overrides file that omits the 'EN' VehicleType
        partial_overrides = {
            "schema_version": 1,
            "year": 2025,
            "vehicle_type_overrides": [
                {
                    "name_short": "DD",
                    "motor_rated_power_kw": 300.0,
                    "motor_power_to_weight_ratio_kw_per_kg": 1.5,
                    "vehicle_lifetime_years": 12.0,
                    "average_consumption_kwh_per_km": 2.16,
                    "diesel_consumption_kg_per_km": None,
                }
            ],
            "charging_point_type_overrides": [],
        }
        overrides_path = tmp_path / "partial_overrides.json"
        with open(overrides_path, "w") as f:
            json.dump(partial_overrides, f)

        scenario = (
            db_session.query(__import__("eflips.model", fromlist=["Scenario"]).Scenario)
            .filter_by(id=SCENARIO_ID)
            .one()
        )

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = init_lca_params(
                scenario=scenario,
                lca_json_path=DEFAULTS_DIR / "lca.json",
                overrides_json_path=overrides_path,
            )

        assert result is None
        user_warnings = [
            str(w.message) for w in caught if issubclass(w.category, UserWarning)
        ]
        assert any("lca_parameters will not be written" in msg for msg in user_warnings)
