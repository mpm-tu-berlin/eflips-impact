import numpy as np
from typing import List, Dict, Union
import configparser
import platform
import pandas as pd


def parse_section(data: str, section_name: str, section_dict: Dict[str, Union[str, float]],
                  convert_to_float: bool = False) -> None:
    """
    Parse a section from a configuration file and update a dictionary with the section's key-value pairs.

    Parameters:
    data (str): The configuration file data.
    section_name (str): The name of the section to parse.
    section_dict (Dict[str, Union[str, float]]): The dictionary to update with the section's key-value pairs.
    convert_to_float (bool, optional): Whether to convert the section's values to float. Defaults to False.
    """
    config = configparser.ConfigParser()
    config.read(data)
    for key, value in config[section_name].items():
        section_dict[key] = float(value) if convert_to_float else value


def linear_interpolation_dataframe(wtt_results, start_year, inbetween_year, end_year):
    """
    Perform linear interpolation on given dataframe for the target_years.

    Parameters:
    df (pd.DataFrame): The dataframe for interpolation.
    start_year (int): The start year for interpolation.
    end_year (int): The end year for interpolation.

    Returns:
    pd.DataFrame: A dataframe with the interpolated values for each year from start_year to end_year.
    """
    wtt_results_copy = wtt_results.copy()  # Create a copy of the DataFrame
    wtt_results_copy = wtt_results_copy.T

    all_years = set(range(start_year, end_year+1))
    existing_years = {int(start_year), int(inbetween_year), int(end_year)}
    missing_years = list(all_years - existing_years)

    wtt_results_copy = wtt_results_copy.reindex(wtt_results_copy.index.union(missing_years))

    # Convert index to integer before sorting
    wtt_results_copy.index = wtt_results_copy.index.astype(int)

    # Sort the DataFrame by its index before interpolation
    wtt_results_copy = wtt_results_copy.sort_index()

    interpolated_df = wtt_results_copy.interpolate(method='linear', limit_direction='both')
    return interpolated_df.T