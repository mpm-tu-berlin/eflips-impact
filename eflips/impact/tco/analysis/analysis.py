# This file contains the sensitivity analysis and is only required for the Bachelor thesis.

import parameters as p
import eflips.impact.tco.tco_utils as f
import numpy as np
import matplotlib.pyplot as plt
from matplotlib import colormaps as cm
import json
import warnings as w


# Conduct a sensitivity analysis
def sensitivity_analysis(
    capex_input, opex_input, general_input, parameter_list, scenario_id, save_fig=False
):
    Fig = plt.figure(1, (8, 6))
    ax = Fig.add_subplot(111)

    resolution = 101

    for parameter in parameter_list:
        input_parameter = 0
        j = 0
        tco_array = np.zeros(resolution)
        x_array = np.linspace(-40, 40, num=resolution)

        if parameter == "useful_life" or parameter == "procurement":
            input_parameter = []
            keys = []
            for key, data in capex_input.items():
                if parameter == "useful_life":
                    input_parameter.append(data["useful_life"])
                else:
                    input_parameter.append(data["procurement_cost"])
                keys.append(key)

            input_array = np.array(input_parameter)
            analysis_array = np.linspace(
                input_array * 0.6, input_array * 1.4, num=resolution
            )

            for i in range(len(analysis_array)):
                for x in range(len(keys)):
                    if parameter == "procurement":
                        capex_input[keys[x]]["procurement_cost"] = analysis_array[i, x]
                    else:
                        # only interger values are permitted for the useful life
                        capex_input[keys[x]]["useful_life"] = int(analysis_array[i, x])

                tco_array[i] = f.tco_calculation(
                    capex_input, opex_input, general_input
                ).get("Specific_TCO_over_PD")

            # As the useful life can only be an integer, linear regression is used to obtain a linear graph.
            c = np.polyfit(x_array, tco_array, 1)
            tco_array = np.polyval(c, x_array)
        # For the other parameters the usual approach can be used.
        else:
            try:
                try:
                    input_parameter = opex_input[parameter].get("cost")
                    j = 2
                except KeyError:
                    pass
                try:
                    input_parameter = general_input[parameter]
                    j = 3
                except KeyError:
                    pass
                if input_parameter == 0:
                    raise KeyError(
                        "The parameter {} was not found in the input dictionary. Please check that your spelling "
                        "matches the spelling in the input dictionaries".format(
                            input_parameter
                        )
                    )
            except KeyError as e:
                print(e)

            analysis_array = np.linspace(
                input_parameter * 0.6, input_parameter * 1.4, num=resolution
            )

            for i in range(len(analysis_array)):
                if j == 2:
                    opex_input[parameter]["cost"] = analysis_array[i]
                if j == 3:
                    general_input[parameter] = analysis_array[i]
                tco_array[i] = f.tco_calculation(
                    capex_input, opex_input, general_input
                ).get("Specific_TCO_over_PD")
        # get the percent change
        base_tco = tco_array[np.where(x_array == 0)]
        tco_array /= base_tco * 0.01
        tco_array -= 100
        ax.plot(x_array, tco_array, label=parameter)
        plt.xlim(-40, 40)
        plt.ylim(-20, 20)

    plt.ylabel("Change of specific TCO in %")
    plt.xlabel("Change of parameter in %")
    plt.legend(bbox_to_anchor=(0.5, -0.11), loc="upper center", ncol=2)
    plt.title(
        "Sensitivity Analysis of the specific TCO in Scenario {}".format(scenario_id)
    )
    plt.axis("equal")
    plt.grid()
    plt.tight_layout()
    plt.show()
    if save_fig:
        Fig.savefig("sensitivity_analysis_scn_{}.png".format(scenario_id))


# Plot the different scenarios in bar charts side by side
def plot_scenarios(scenarios: [int], savefig=False):
    data = {}
    for scenario in scenarios:
        try:
            with open("result_scenario_{}.json".format(str(scenario)), "r") as f:
                # load data from the json files and append it to the list
                key = "scenario {}".format(str(scenario))
                data[key] = json.load(f)
        except FileNotFoundError:
            w.warn(
                "The file result_scenario_{}.json was not found and has been disregarded in the plot. "
                "Please pay attention to the correct spelling of the file.".format(
                    str(scenario)
                )
            )

    # Create a figure with fixed size.
    Fig = plt.figure(1, (10, 10))
    ax = Fig.add_subplot(1, 1, 1)

    plot_data = {
        "Infrastructure": [],
        "Vehicle": [],
        "Battery": [],
        "Other Cost": [],
        "Vehicle Maintenance Cost": [],
        "Infrastructure Maintenance Cost": [],
        "Staff Cost": [],
        "Energy Cost": [],
    }

    for name, result_dict in data.items():
        # save the data in a suitable dictionary.
        tco_data = {
            "Infrastructure": 0,
            "Vehicle": 0,
            "Battery": 0,
            "Other Cost": (
                result_dict["tco_by_type"]["insurance"]
                + result_dict["tco_by_type"]["taxes"]
            ),
            "Vehicle Maintenance Cost": result_dict["tco_by_type"][
                "maint_cost_vehicles"
            ],
            "Infrastructure Maintenance Cost": result_dict["tco_by_type"][
                "maint_cost_infra"
            ],
            "Staff Cost": result_dict["tco_by_type"]["staff_cost"],
            "Energy Cost": result_dict["tco_by_type"]["fuel_cost"],
        }
        for name, data in result_dict["tco_by_type"].items():
            if "INFRASTRUCTURE" in name:
                tco_data["Infrastructure"] += data
            elif "VEHICLE" in name:
                tco_data["Vehicle"] += data
            elif "BATTERY" in name:
                tco_data["Battery"] += data
        for key, value in tco_data.items():
            plot_data[key].append(value)

    # Use colormaps to choose the colors for the plot
    color = cm.get_cmap("managua")(np.linspace(0, 1, len(plot_data.keys())))

    name = ["Scenario {}".format(str(i)) for i in scenarios]
    bottom = np.zeros(len(scenarios))
    for color, [tco_categories, data] in zip(color, plot_data.items()):
        p = ax.bar(name, data, label=tco_categories, bottom=bottom, color=color)
        bottom += data
        ax.bar_label(p, label_type="center", padding=3, fmt="%.2f")
    # write the total tco over the bar
    x = np.arange(len(scenarios))
    for i, total in enumerate(bottom):
        ax.text(
            x[i],
            (total + 0.1),
            s=str("{:.2f}".format(np.round(total, 2))),
            ha="center",
            va="bottom",
            fontweight="bold",
        )

    # Set limit on y axis
    ax.set_ylim(top=np.max(bottom) + 0.5)
    # set title
    ax.set_title("Specific Total Cost of Ownership")
    # set the y-axis label
    ax.set_ylabel("TCO in €/km")

    ax.legend(bbox_to_anchor=(0.5, -0.05), loc="upper center", ncol=2)
    plt.tight_layout()
    plt.show()
    if savefig:
        Fig.savefig("tco_plot_scenarios.png")


# In this method the efficiency of the different scenarios is compared
def plot_efficiency(scenarios: [int], savefig=False):
    Fig = plt.figure(1, (16, 8))
    ax = 0
    annual_fleet_mileage = 0
    passenger_mileage = 0
    for i in range(len(scenarios)):
        data = {}
        ax = Fig.add_subplot(1, len(scenarios), (i + 1))
        with open("result_scenario_{}.json".format(str(scenarios[i])), "r") as f:
            # load data from the json files and append it to the list
            key = "scenario {}".format(str(scenarios[i]))
            data[key] = json.load(f)

        for name, result_dict in data.items():
            plot_data = {
                "Infrastructure": [],
                "Vehicle": [],
                "Battery": [],
                "Other Cost": [],
                "Vehicle Maintenance Cost": [],
                "Infrastructure Maintenance Cost": [],
                "Staff Cost": [],
                "Energy Cost": [],
            }
            # save the data in a suitable dictionary.
            tco_data = {
                "Infrastructure": 0,
                "Vehicle": 0,
                "Battery": 0,
                "Other Cost": (
                    result_dict["tco_by_type"]["insurance"]
                    + result_dict["tco_by_type"]["taxes"]
                ),
                "Vehicle Maintenance Cost": result_dict["tco_by_type"][
                    "maint_cost_vehicles"
                ],
                "Infrastructure Maintenance Cost": result_dict["tco_by_type"][
                    "maint_cost_infra"
                ],
                "Staff Cost": result_dict["tco_by_type"]["staff_cost"],
                "Energy Cost": result_dict["tco_by_type"]["fuel_cost"],
            }
            # Add the data for the assets
            for name_, data in result_dict["tco_by_type"].items():
                if "INFRASTRUCTURE" in name_:
                    tco_data["Infrastructure"] += data
                elif "VEHICLE" in name_:
                    tco_data["Vehicle"] += data
                elif "BATTERY" in name_:
                    tco_data["Battery"] += data

            # save tha data in the plot dict including the data per passenger km.
            for key, value in tco_data.items():
                plot_data[key].append(value)
                plot_data[key].append(
                    value
                    * result_dict["Annual_fleet_mileage"]
                    / result_dict["Annual_passenger_mileage"]
                )

            # Use colormaps to choose the colors for the plot
            color = cm.get_cmap("managua")(np.linspace(0, 1, len(plot_data.keys())))

            name = ["TCO per km", "TCO per passenger km"]
            bottom = np.zeros(len(name))
            for color, [tco_categories, data] in zip(color, plot_data.items()):
                p = ax.bar(name, data, label=tco_categories, bottom=bottom, color=color)
                bottom += data
                ax.bar_label(p, label_type="center", padding=3, fmt="%.2f")
            # write the total tco over the bar
            x = np.arange(len(scenarios))
            for j, total in enumerate(bottom):
                ax.text(
                    x[j],
                    (total + 0.1),
                    s=str("{:.2f}".format(np.round(total, 2))),
                    ha="center",
                    va="bottom",
                    fontweight="bold",
                )
            # Set limit on y axis
            ax.set_ylim(top=np.max(bottom) + 0.5)
            # set title
            ax.set_title("Efficiency Scenario {}".format(scenarios[i]))
            # set the y-axis label
            ax.set_ylabel("TCO in €/km")
            # plt.tight_layout()

    handles, labels = ax.get_legend_handles_labels()
    Fig.legend(
        handles,
        labels,
        bbox_to_anchor=(0.5, 0.05),
        loc="upper center",
        ncol=len(handles),
    )
    # Fig.tight_layout()
    Fig.suptitle("Efficiency of different Scenarios", y=0.95)
    Fig.show()
    if savefig:
        Fig.savefig("efficiency_scenarios.png")


def plot_scenario_info(scenarios: [int], savefig=False):
    """
    This function visualizes some metrics of the calculated scenario and plots it in bar charts in order to allow for
        more detailed analysis.
    :param scenarios: A list of the scenarios ids of which the plots should be created.
    :return: Nothing.
    """
    data = {}
    for scenario in scenarios:
        try:
            with open("results_scn_{}.json".format(str(scenario)), "r") as f:
                # load data from the json files and append it to the list
                key = "scenario {}".format(str(scenario))
                data[key] = json.load(f)
        except FileNotFoundError:
            w.warn(
                "The file result_scenario_{}.json was not found and has been disregarded in the plot. "
                "Please pay attention to the correct spelling of the file.".format(
                    str(scenario)
                )
            )

    # Create a figure with fixed size.
    Fig = plt.figure(1, (16, 5))

    scn = ["Scenario {}".format(str(scenario)) for scenario in scenarios]
    fleet_mileage = [
        data["scenario {}".format(str(scenario))]["Results"][
            "Total_annual_fleet_mileage"
        ][0]
        for scenario in scenarios
    ]
    passenger_mileage = [
        data["scenario {}".format(str(scenario))]["Results"][
            "Total_annual_passenger_mileage"
        ][0]
        for scenario in scenarios
    ]
    energy_consumption = [
        data["scenario {}".format(str(scenario))]["Results"][
            "Average_energy_consumption"
        ][0]
        for scenario in scenarios
    ]
    driver_hours = [
        data["scenario {}".format(str(scenario))]["Results"][
            "Total_annual_driver_hours"
        ][0]
        for scenario in scenarios
    ]
    titles = [
        "Annual Fleet Mileage",
        "Annual Passenger Mileage",
        "Annual Driver Hours",
        "Annual Energy Consumption",
    ]
    plot_data = [fleet_mileage, passenger_mileage, driver_hours, energy_consumption]
    units = [
        "Mileage in km",
        "Mileage in km",
        "Driver hours in h",
        "Energy consumption in kWh",
    ]

    color = cm.get_cmap("managua")(np.linspace(0.2, 0.9, len(scenarios)))
    ax = None
    for title, plot_d, unit in zip(titles, plot_data, units):
        ax = Fig.add_subplot(1, 4, (titles.index(title) + 1))
        bar_container = ax.bar(scn, plot_d, color=color, label=scn)
        ax.set(ylabel=unit, title=title, ylim=(0, (max(plot_d) * 1.15)))
        ax.bar_label(bar_container, label_type="edge", padding=3, fmt="%.2f")
    handles, labels = ax.get_legend_handles_labels()
    Fig.legend(
        handles,
        labels,
        bbox_to_anchor=(0.5, 0.075),
        loc="upper center",
        ncol=len(handles),
    )
    Fig.suptitle("Scenario Metrics", y=0.95)
    Fig.tight_layout()
    Fig.subplots_adjust(bottom=0.15)
    Fig.show()
    if savefig:
        Fig.savefig("scenario_metrics.png")
