import logging
from dataclasses import dataclass, field
import olca_ipc as ipc
#import olca as ipc
#from olca import ipc
#from olca import schema as o
import pandas as pd
import olca_schema as o
from typing import List, Dict
import numpy as np
import json
import os
import sys

logging.basicConfig(level=logging.INFO)

@dataclass
class LCA:
    """Class for running LCA calculations with openLCA."""
    openLCA_product_systems: Dict[str, str]
    LCAImpactMethods: str = 'c99194f6-351f-425a-82eb-6cd9654cefca'
    product_systems: List[str] = field(default_factory=list)
    impact_categories: List[str] = field(default_factory=list)
    results: List[float] = field(default_factory=list)
    LCAResults: pd.DataFrame = field(default_factory=pd.DataFrame)
    first_calc: bool = False

    def lcaproductsystem(self) -> None:
        """
        Run LCA calculations with openLCA and store the results.

        Raises:
        ValueError: If the LCA can't run because 'self.results' is empty.
        """
        self.product_systems = list(self.openLCA_product_systems)
        self.impact_categories = []
        for productsystems, ids in self.openLCA_product_systems.items():
            logging.info(ids)
            setup = o.CalculationSetup(
                target=o.Ref(
                    ref_type=o.RefType.ProductSystem,
                    id=ids,
                ),
                impact_method=o.Ref(id=self.LCAImpactMethods),
                nw_set=o.Ref(id="867fe119-0b5c-38a0-a3e6-1d845ffaedd5")
            )

            client = ipc.Client()
            result: ipc.Result = client.calculate(setup)
            state = result.wait_until_ready()
            self.results = result.get_total_impacts()
            logging.info(self.results)
            if self.first_calc == False:
                if self.results != None:
                    self.first_calc = True
                    self.impact_categories = [(str(n.impact_category.name)) + ' ' + str(n.impact_category.ref_unit) for
                                              n in
                                              self.results]
                    self.LCAResults = pd.DataFrame(columns=self.product_systems, index=self.impact_categories)
                else:
                    raise ValueError(f"The LCA can't run,'{self.results}' is empty.")
            else:
                pass
            self.LCAResults[str(productsystems)] = [n.amount for n in self.results]
            result.dispose()
        return self.LCAResults