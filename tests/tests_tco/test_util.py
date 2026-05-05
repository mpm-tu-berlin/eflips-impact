import matplotlib.pyplot as plt

from eflips.impact.tco.util import plot_tco_comparison


class TestPlotTcoComparison:
    def test_returns_figure(self):
        data = [{"capex": 100.0, "opex": 50.0}, {"capex": 80.0, "opex": 60.0}]
        names = ["Scenario A", "Scenario B"]
        colors = {"capex": "blue", "opex": "orange"}
        fig = plot_tco_comparison(data, names, colors)
        assert isinstance(fig, plt.Figure)
        plt.close(fig)

    def test_missing_key_treated_as_zero(self):
        data = [{"capex": 100.0}, {"capex": 80.0, "opex": 60.0}]
        names = ["A", "B"]
        colors = {"capex": "blue", "opex": "orange"}
        fig = plot_tco_comparison(data, names, colors)
        assert isinstance(fig, plt.Figure)
        plt.close(fig)
