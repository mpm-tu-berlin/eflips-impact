
from utilslcca import *
from lca import *


logging.basicConfig(level=logging.INFO)


@dataclass
class Cases:
    case_data: dict = field(init=False)
    case_lca: dict = field(init=False)
    case_name: dict = field(init=False)
    data: str = None
    parameters: str = "scenario_parameters"
    lca_system: str = "lca_systems"
    cases: str = 'case_name'
    lca_results: dict = field(init=False)
    results_json: str = None


    def __post_init__(self):
        """
        Initialize the Cases object by parsing the data and performing LCA calculations.
        """
        if self.data is None:
            raise ValueError("Data must not be None.")

        self.case_data = self._parse_section(self.parameters, convert_to_float=True)
        self.case_name = self._parse_section(self.cases)
        self.case_lca = self._parse_section(self.lca_system)

        self.lca_results = self._get_lca_results()

        return self.lca_results

    def _parse_section(self, section_name: str, convert_to_float: bool = False) -> dict:
        """
        Parse a section from the data and return a dictionary with the section's key-value pairs.

        Parameters:
        section_name (str): The name of the section to parse.
        convert_to_float (bool, optional): Whether to convert the section's values to float. Defaults to False.

        Returns:
        dict: A dictionary with the section's key-value pairs.
        """
        section_dict = {}
        parse_section(self.data, section_name, section_dict, convert_to_float)
        return section_dict

    def _get_lca_results(self) -> pd.DataFrame:
        """
        Get the LCA results from a JSON file or calculate them if the file does not exist or contains invalid JSON.

        Returns:
        pd.DataFrame: The LCA results.
        """
        if self.results_json is not None:
            try:
                return pd.read_json(self.results_json, orient="split")
            except (FileNotFoundError, json.JSONDecodeError):
                pass

        lca_results = LCA(self.case_lca, first_calc=False).lcaproductsystem()
        lca_results.to_json(self.results_json, orient="split")
        return lca_results

