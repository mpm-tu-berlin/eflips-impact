"""TCO-specific plotting helpers.

The legacy ``create_session`` helper that lived here has been removed; entry
points resolve their ``scenario`` argument inline (see
:mod:`eflips.impact.utils.fleet_init` for the canonical pattern). Domain-
specific value types and plotting utilities continue to live here.
"""

import matplotlib.pyplot as plt
import numpy as np


def plot_tco_comparison(
    all_tco: list[dict], all_names: list[str], colors
) -> plt.Figure:
    """Stacked bar chart comparing TCO breakdowns across scenarios.

    :param all_tco: One ``dict[str, float]`` per scenario, mapping cost-category
        label to value. Missing keys are treated as zero.
    :param all_names: Per-scenario x-axis labels (same length as ``all_tco``).
    :param colors: Mapping from cost-category label to matplotlib color.
    :returns: The matplotlib ``Figure`` (caller is responsible for showing/saving).
    """
    # Collect all possible keys
    all_keys = sorted({k for d in all_tco for k in d.keys()})

    # Convert dicts to aligned arrays
    values = np.array([[d.get(k, 0) for k in all_keys] for d in all_tco])

    # Plot
    fig, ax = plt.subplots(figsize=(15, 10), constrained_layout=True)

    x = np.arange(len(all_tco))
    bottom = np.zeros(len(all_tco))

    for i, key in enumerate(all_keys):
        current_bar = ax.bar(
            x, values[:, i], bottom=bottom, label=key, color=colors[key]
        )
        bottom += values[:, i]
        ax.bar_label(current_bar, label_type="center", padding=3, fmt="%.2f")

    totals = values.sum(axis=1)
    for xi, total in zip(x, totals):
        ax.text(
            round(xi, 2),
            total + 0.3,
            str(round(total, 2)),
            ha="center",
            va="bottom",
            fontweight="bold",
        )

    ax.set_xticks(x)
    ax.set_xticklabels([all_names[i] for i in range(len(all_tco))])
    ax.set_ylabel("Value")
    ax.legend(title="Keys", loc="upper left", bbox_to_anchor=(1.05, 1))
    return fig
