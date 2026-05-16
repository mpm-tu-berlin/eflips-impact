"""Fleet topology initialization for a scenario.

Reads a ``fleet.json`` file and brings the BatteryType and ChargingPointType
rows of a scenario into the state described by the file. Owns *only* row
creation, deletion, and FK assignment; never writes ``tco_parameters`` or
``lca_parameters`` columns. Pair this with :mod:`eflips.impact.tco` and
:mod:`eflips.impact.lca` to populate parameter columns afterwards.

Cross-file matching is by string keys (``vehicle_name_short``, ``type``);
database-assigned integer ids are not stable across rebuilds.
"""

from __future__ import annotations

import json
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional, Union

from sqlalchemy import distinct
from sqlalchemy.orm import Session

from eflips.model import (
    Area,
    BatteryType,
    ChargingPointType,
    EnergySource,
    Event,
    EventType,
    Process,
    Scenario,
    Station,
    VehicleType,
)
from eflips.impact.utils.session import create_session

_ALLOWED_CHEMISTRIES = frozenset({"lfp", "nmc"})


@dataclass(frozen=True)
class _BatteryEntry:
    """One battery entry from fleet.json (private to this module)."""

    vehicle_name_short: str
    specific_mass: float
    chemistry: str


@dataclass(frozen=True)
class _ChargingPointEntry:
    """One charging-point-type entry from fleet.json (private to this module)."""

    type: str
    name: str
    name_short: Optional[str]


@dataclass(frozen=True)
class _FleetConfig:
    """Parsed contents of fleet.json (private to this module)."""

    battery_types: List[_BatteryEntry]
    charging_point_types: List[_ChargingPointEntry]


def complete_fleet(
    scenario: Union[Scenario, int, Any],
    filepath: Path,
    delete_existing_data: bool,
    database_url: Optional[str] = None,
) -> None:
    """Initialize BatteryType and ChargingPointType rows for a scenario.

    Reads ``filepath`` (a ``fleet.json``) and either creates new rows or
    replaces the existing ones according to ``delete_existing_data``. Assigns
    the new ``BatteryType`` rows to matching ``VehicleType.battery_type_id``
    and the new ``ChargingPointType`` rows to all charging Areas (depot type)
    and all opportunity-charging Stations (opportunity type) in the scenario.

    Pre-flight validation runs before any mutation. On any validation failure
    a ``UserWarning`` is emitted and the function returns without changing the
    database.

    :param scenario: A :class:`eflips.model.Scenario` (uses its bound session;
        caller owns the transaction), an ``int`` scenario id, or any
        object with an ``id`` attribute. For the latter two cases,
        ``database_url`` (or ``$DATABASE_URL``) is used to open a fresh
        session that is committed and closed before return.
    :param filepath: Path to the ``fleet.json`` file.
    :param delete_existing_data: If ``False`` and any BatteryType or
        ChargingPointType already exists in the scenario, warn and
        return without mutation. If ``True``, NULL the FKs on
        VehicleType / Area / Station, delete the existing rows, and
        recreate from ``fleet.json`` — all in one transaction.

    .. note::

        When ``delete_existing_data=True``, any existing ``tco_parameters``
        or ``lca_parameters`` JSONB content on VehicleType / Area / Station rows
        becomes stale (it referenced the deleted rows). The caller is
        responsible for re-running the relevant ``init_*`` / ``populate_*``
        functions afterwards. ``complete_fleet`` does not auto-clear or warn
        about stale params.
    """
    config = _load_fleet_config(filepath)
    if config is None:
        return

    with create_session(scenario, database_url) as (session, scenario_obj):
        if not _validate(session, scenario_obj, config):
            return

        if not delete_existing_data:
            existing_bt = (
                session.query(BatteryType.id)
                .filter(BatteryType.scenario_id == scenario_obj.id)
                .first()
            )
            existing_cpt = (
                session.query(ChargingPointType.id)
                .filter(ChargingPointType.scenario_id == scenario_obj.id)
                .first()
            )
            if existing_bt is not None or existing_cpt is not None:
                warnings.warn(
                    f"Existing BatteryType / ChargingPointType found in scenario "
                    f"{scenario_obj.id}; pass delete_existing_data=True to replace, "
                    f"or skip this call if topology is already initialized.",
                    UserWarning,
                    stacklevel=2,
                )
                return
        else:
            _clear_existing(session, scenario_obj)

        _create_battery_types(session, scenario_obj, config.battery_types)
        _create_charging_point_types(session, scenario_obj, config.charging_point_types)


# ---------------------------------------------------------------------------
# fleet.json parsing
# ---------------------------------------------------------------------------


def _load_fleet_config(filepath: Path) -> Optional[_FleetConfig]:
    """Parse fleet.json into an internal config object.

    Returns ``None`` (after warning) on schema-shape errors.
    """
    with open(filepath, "r", encoding="utf-8") as f:
        raw = json.load(f)

    battery_entries: List[_BatteryEntry] = []
    for raw_bt in raw.get("battery_types", []):
        try:
            battery_entries.append(
                _BatteryEntry(
                    vehicle_name_short=str(raw_bt["vehicle_name_short"]),
                    specific_mass=float(raw_bt["specific_mass"]),
                    chemistry=str(raw_bt["chemistry"]),
                )
            )
        except KeyError as e:
            warnings.warn(
                f"fleet.json battery entry missing required field {e}; "
                f"chemistry and specific_mass are mandatory. No changes made.",
                UserWarning,
                stacklevel=3,
            )
            return None

    cpt_entries: List[_ChargingPointEntry] = []
    for raw_cpt in raw.get("charging_point_types", []):
        try:
            cpt_entries.append(
                _ChargingPointEntry(
                    type=str(raw_cpt["type"]),
                    name=str(raw_cpt["name"]),
                    name_short=(
                        str(raw_cpt["name_short"])
                        if raw_cpt.get("name_short") is not None
                        else None
                    ),
                )
            )
        except KeyError as e:
            warnings.warn(
                f"fleet.json charging_point_types entry missing required field {e}. "
                f"No changes made.",
                UserWarning,
                stacklevel=3,
            )
            return None

    return _FleetConfig(battery_types=battery_entries, charging_point_types=cpt_entries)


# ---------------------------------------------------------------------------
# Pre-flight validation
# ---------------------------------------------------------------------------


def _validate(session: Session, scenario: Scenario, config: _FleetConfig) -> bool:
    """Run all pre-flight validation rules. Warn-and-return-False on failure.

    Order: chemistry → at-most-one-CPT-per-type → BEB coverage → CPT topology.
    The function returns ``False`` on the *first* failure to keep error
    messages focused.
    """
    # Chemistry allow-list.
    for bt in config.battery_types:
        if bt.chemistry not in _ALLOWED_CHEMISTRIES:
            warnings.warn(
                f"fleet.json battery entry for '{bt.vehicle_name_short}' has "
                f"chemistry='{bt.chemistry}' which is not in the allowed set "
                f"{sorted(_ALLOWED_CHEMISTRIES)}. No changes made to scenario "
                f"{scenario.id}.",
                UserWarning,
                stacklevel=3,
            )
            return False

    # At most one CPT entry per type in the JSON.
    cpt_types = [c.type for c in config.charging_point_types]
    if len(cpt_types) != len(set(cpt_types)):
        warnings.warn(
            f"fleet.json declares multiple charging_point_types entries with the "
            f"same 'type'. At most one entry per type is supported. No changes "
            f"made to scenario {scenario.id}.",
            UserWarning,
            stacklevel=3,
        )
        return False

    # BatteryType coverage: every BEB VehicleType.name_short must be present
    # in the JSON's vehicle_name_short set.
    beb_name_shorts = {
        ns
        for (ns,) in session.query(VehicleType.name_short)
        .filter(
            VehicleType.scenario_id == scenario.id,
            VehicleType.energy_source == EnergySource.BATTERY_ELECTRIC,
        )
        .all()
    }
    json_battery_keys = {bt.vehicle_name_short for bt in config.battery_types}
    missing = beb_name_shorts - json_battery_keys
    if missing:
        warnings.warn(
            f"fleet.json has no battery entry for BEB VehicleType(s) "
            f"{sorted(missing)} in scenario {scenario.id}. No changes made.",
            UserWarning,
            stacklevel=3,
        )
        return False

    # CPT topology: JSON 'type' set must match the scenario's actual topology.
    has_depot = (
        session.query(Area.id)
        .filter(
            Area.scenario_id == scenario.id,
            Area.processes.any(Process.electric_power.isnot(None)),
        )
        .first()
        is not None
    )
    has_opportunity = (
        session.query(Event.id)
        .filter(
            Event.scenario_id == scenario.id,
            Event.event_type == EventType.CHARGING_OPPORTUNITY,
        )
        .first()
        is not None
    )

    expected: set[str] = set()
    if has_depot:
        expected.add("depot")
    if has_opportunity:
        expected.add("opportunity")

    actual = set(cpt_types)
    if actual != expected:
        warnings.warn(
            f"fleet.json charging_point_types {sorted(actual)} do not match the "
            f"scenario's actual charging topology {sorted(expected)} (depot iff "
            f"any Area has a Process with electric_power; opportunity iff any "
            f"CHARGING_OPPORTUNITY event exists). No changes made to scenario "
            f"{scenario.id}.",
            UserWarning,
            stacklevel=3,
        )
        return False

    return True


# ---------------------------------------------------------------------------
# Mutation helpers
# ---------------------------------------------------------------------------


def _clear_existing(session: Session, scenario: Scenario) -> None:
    """NULL FKs and delete existing BatteryType / ChargingPointType rows.

    Scoped to the given scenario; never touches other scenarios in the same DB.
    """
    session.query(VehicleType).filter(VehicleType.scenario_id == scenario.id).update(
        {VehicleType.battery_type_id: None}, synchronize_session="fetch"
    )

    session.query(Area).filter(Area.scenario_id == scenario.id).update(
        {Area.charging_point_type_id: None}, synchronize_session="fetch"
    )
    session.query(Station).filter(Station.scenario_id == scenario.id).update(
        {Station.charging_point_type_id: None}, synchronize_session="fetch"
    )

    session.flush()

    session.query(BatteryType).filter(BatteryType.scenario_id == scenario.id).delete(
        synchronize_session="fetch"
    )
    session.query(ChargingPointType).filter(
        ChargingPointType.scenario_id == scenario.id
    ).delete(synchronize_session="fetch")

    session.flush()


def _create_battery_types(
    session: Session, scenario: Scenario, entries: List[_BatteryEntry]
) -> None:
    """Create BatteryType rows and assign each to its matching VehicleType.

    JSON entries whose ``vehicle_name_short`` does not match any BEB
    VehicleType in the scenario are silently skipped.
    """
    vts_by_name = {
        vt.name_short: vt
        for vt in session.query(VehicleType)
        .filter(
            VehicleType.scenario_id == scenario.id,
            VehicleType.energy_source == EnergySource.BATTERY_ELECTRIC,
        )
        .all()
    }

    for entry in entries:
        vt = vts_by_name.get(entry.vehicle_name_short)
        if vt is None:
            # Extra JSON entry — silently skipped per spec.
            continue
        bt = BatteryType(
            scenario_id=scenario.id,
            specific_mass=entry.specific_mass,
            chemistry=entry.chemistry,
        )
        session.add(bt)
        session.flush()
        vt.battery_type_id = bt.id


def _create_charging_point_types(
    session: Session, scenario: Scenario, entries: List[_ChargingPointEntry]
) -> None:
    """Create ChargingPointType rows and assign each to its targets.

    ``depot`` rows are assigned to every Area with a charging Process; ``opportunity``
    rows to every Station referenced by a CHARGING_OPPORTUNITY event.
    """
    for entry in entries:
        kwargs: dict[str, Any] = {
            "scenario_id": scenario.id,
            "name": entry.name,
        }
        if entry.name_short is not None:
            kwargs["name_short"] = entry.name_short
        cpt = ChargingPointType(**kwargs)
        session.add(cpt)
        session.flush()

        if entry.type == "depot":
            depot_areas = (
                session.query(Area)
                .filter(
                    Area.scenario_id == scenario.id,
                    Area.processes.any(Process.electric_power.isnot(None)),
                )
                .all()
            )
            for area in depot_areas:
                area.charging_point_type_id = cpt.id

        elif entry.type == "opportunity":
            station_ids = [
                sid
                for (sid,) in session.query(distinct(Event.station_id))
                .filter(
                    Event.scenario_id == scenario.id,
                    Event.event_type == EventType.CHARGING_OPPORTUNITY,
                )
                .all()
                if sid is not None
            ]
            if station_ids:
                session.query(Station).filter(Station.id.in_(station_ids)).update(
                    {Station.charging_point_type_id: cpt.id},
                    synchronize_session="fetch",
                )

        else:
            # Validation rejected unknown types upstream, but be defensive.
            raise ValueError(
                f"Internal error: unrecognised charging_point_type 'type' "
                f"'{entry.type}' reached creation step."
            )

    session.flush()
