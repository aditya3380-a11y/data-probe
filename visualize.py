"""Save the two charts used in the README and the interview."""
import matplotlib
matplotlib.use("Agg")  # draw to files, no window needed
import matplotlib.pyplot as plt


def plot_recall_by_type(recall_table, path):
    """Save a bar chart comparing recall for each anomaly type."""
    ax = recall_table.plot(kind="bar", figsize=(9, 5), color=["#4C72B0", "#DD8452"])
    ax.set_ylabel("Share of rows flagged")
    ax.set_title("What each detector flags, by true row type")
    ax.set_ylim(0, 1.05)
    plt.xticks(rotation=20)
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()


def plot_scatter(df, iqr_flag, if_flag, path, x="study_hours_per_day", y="exam_score"):
    """Save a scatter plot using the requested feature columns as its axes."""
    groups = [
        ("Not flagged", ~iqr_flag & ~if_flag, "lightgrey"),
        ("IQR only", iqr_flag & ~if_flag, "#4C72B0"),
        ("Isolation Forest only", ~iqr_flag & if_flag, "#DD8452"),
        ("Both", iqr_flag & if_flag, "#C44E52"),
    ]
    plt.figure(figsize=(8, 6))
    for label, mask, color in groups:
        plt.scatter(df.loc[mask, x], df.loc[mask, y], s=14, c=color, label=label)
    plt.xlabel(x)
    plt.ylabel(y)
    plt.title("Who flagged what")
    plt.legend()
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()
