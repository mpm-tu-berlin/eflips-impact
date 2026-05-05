from dataclasses import dataclass
from enum import Enum, auto


def net_present_value(cash_flow, years_after_base_year: int, discount_rate):
    """
    This method is used to calculate the net present value of any cash flow, a default value for the discount rate is set.

    :param cash_flow: The cashflow of which the present value needs to be calculated.
    :param years_after_base_year: The year after the base year in which the cashflow occurs.
    :param discount_rate: The discount rate by which the cash flow should be discounted.
    :return: A tuple of the present value of the cashflow rounded on 2 decimals and the year after base year in which the cashflow occurs.
    """
    npv = cash_flow / ((1 + discount_rate) ** years_after_base_year)
    return npv


class CapexItemType(Enum):
    """ """

    VEHICLE = auto()
    "For a vehicle asset, annual mileage is required in the asset parameters."

    BATTERY = auto()

    "For a battery asset, the battery capacity is required in the asset parameters. The procurement cost is the cost "
    "per kWh."

    INFRASTRUCTURE = auto()

    "For infrastructure assets (station/depot installation and charging points), the procurement cost is per unit."


@dataclass
class CapexItem:
    """
    A general class describing an asset. It is used in the calculation of CAPEX and should include the following parameters:

    """

    name: str
    type: CapexItemType
    useful_life: int
    procurement_cost: float
    cost_escalation: float
    quantity: int

    @staticmethod
    def from_dict(item_dict: dict) -> "CapexItem":
        """
        Create a CapexItem instance from a dictionary.

        :param item_dict: Dictionary containing the parameters of the CapexItem.
        :return: An instance of CapexItem.
        """
        raise NotImplementedError(
            "This method should be implemented to create a CapexItem from a dictionary."
        )

    def replacement_cost(self, project_duration) -> list[tuple[float, int, bool]]:
        """
        In this method, the replacement costs of an asset are calculated considering the cost escalation. The cost escalation
        used in this method should be the nominal cost escalation which includes the general inflation. The results will be
        converted back to the base year to compensate for the inflation in the calculation of the total procurement cost.

        :param project_duration: The duration of the project as a timeframe that is considered in this calculation.
        :return: The replacement cost as well as the number of years after the base year in which the replacement is
                conducted are returned with a binary variable which shows whether the useful life of the replaced asset is
                still within the project duration.
        """
        replacement: list[tuple[float, int, bool]] = []
        base_price = self.procurement_cost
        # get the number of full replacements
        number_of_full_replacements = project_duration // self.useful_life
        for i in range(number_of_full_replacements + 1):
            # The new price is the baseprice multiplied by the cost escalation factor to the power of the years after the base year.
            new_price = base_price * (1 + self.cost_escalation) ** (
                i * self.useful_life
            )
            # If the project ends before the useful life if the next replacement, the binary variable is set true in order
            # to account for that in the total_proc_cef function.
            years_used = (i + 1) * self.useful_life
            if years_used <= project_duration:
                replacement.append((new_price, (i * self.useful_life), False))
                if years_used == project_duration:
                    break
            else:
                # The useful life is shorter than the remaining project duration
                replacement.append((new_price, (i * self.useful_life), True))
                break
        return replacement

    def calculate_total_procurement_cost(
        self,
        project_duration: int,
        interest_rate: float,
        net_discount_rate: float,
    ):
        """ """
        # Get a list with all procurements taking place over the project duration
        all_procurements = self.replacement_cost(
            project_duration,
        )
        # List with all annuities
        annuities: list[float] = []
        # List with the present value of all annuities
        annuities_pv: list[float] = []
        # Includes the scaled down present value of the last replacement in case the useful life is larger than the
        # remaining project duration.
        # Calculating all annuities over the project duration and saving them in a list

        # interest rate here should also be the nominal interest rate which includes the general inflation in order

        for new_price, years_after_base_year, partially_used in all_procurements:
            annuity_this_procurement = (
                new_price
                * interest_rate
                / (1 - (1 + interest_rate) ** (-self.useful_life))
            )
            if partially_used:
                # Calculate the present value of the last replacement, scaled for partial use
                annuities_last_replacement = [
                    annuity_this_procurement
                ] * self.useful_life
                pv_sum = sum(
                    net_present_value(ann, year, net_discount_rate)
                    for year, ann in enumerate(annuities_last_replacement)
                )
                fraction_used = (
                    project_duration - years_after_base_year
                ) / self.useful_life
                scaled_down_CF = pv_sum * fraction_used
                annuities.append(scaled_down_CF)
            else:
                # Add the annuity for each year of the asset's useful life
                annuities.extend([annuity_this_procurement] * self.useful_life)

        # Calculate the present value of all cashflows at the base year
        annuities_pv.extend(
            net_present_value(ann, year, net_discount_rate)
            for year, ann in enumerate(annuities)
        )
        # The total procurement cost is returned which is the sum of the annuities adjusted for inflation / discount
        # rate.
        return sum(annuities_pv)


class OpexItemType(Enum):
    """
    Enum for different types of OPEX items.
    """

    ENERGY = auto()
    "For fuel costs, the unit cost is the cost per unit of fuel."

    MAINTENANCE = auto()
    "For maintenance costs, the unit cost is the cost per maintenance event."

    STAFF = auto()
    "For staff costs, the unit cost is the cost per staff member per year."

    OTHER = auto()
    "For other OPEX items, the unit cost is defined by the specific item."


@dataclass
class OpexItem:
    """
    A general class describing an OPEX item. It is used in the calculation of OPEX and should include the following parameters:
    """

    name: str
    type: OpexItemType
    unit_cost: float
    usage_amount: float
    cost_escalation: float

    @staticmethod
    def from_dict(item_dict: dict) -> "OpexItem":
        raise NotImplementedError(
            "This method should be implemented to create an OpexItem from a dictionary."
        )

    def future_cost(self, years_after_base_year: int):
        """
        This method calculates the future cost of the OPEX item based on the cost escalation factor and the usage amount.

        :param years_after_base_year: The year after the base year in which the cost arises.
        :return: The future cost of the OPEX item in the respective year.
        """

        # The cost escalation should be the nominal cost escalation which includes the general inflation
        return (
            self.unit_cost
            * (1 + self.cost_escalation) ** years_after_base_year
            * self.usage_amount
        )
