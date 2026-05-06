from eflips.impact.tco.calculation import TCOCalculator
from eflips.impact.tco.params import (
    init_tco_parameters_from_json,
    init_tco_parameters,
)
from typing import Union, Optional, Any, Dict
from eflips.model import Scenario
import logging


def calculate_tco(
    scenario: Union[Scenario, int, Any],
    database_url: Optional[str] = None,
    use_revenue_km: bool = False,
) -> Dict[str, float]:
    """
    This function calculates the Total Cost of Ownership (TCO) for a given scenario and returns a dictionary
    with the TCO values categorized by type.

    :param scenario: A :class:`eflips.model.Scenario` object, an int scenario id, or any object with an ``id``
        attribute.
    :param database_url: Optional database URL — only consulted when ``scenario`` is not a Scenario instance.
    :param use_revenue_km: If True, the TCO per kilometer will be calculated using the revenue kilometers instead
        of the total vehicle kilometers.
    :return: A dictionary with TCO values categorized by type: infrastructure, staff, battery, maintenance, vehicle,
        energy and other (e.g.taxes and insurance). The unit is EUR per vehicle kilometer over the project duration.
    """
    tco_calculator = TCOCalculator(
        scenario,
        database_url=database_url,
        energy_consumption_mode="constant",
    )
    result = tco_calculator.calculate()
    return result.tco_by_type_per_km(use_revenue_km)
