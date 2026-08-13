"""Migration notice for the retired full-integration demo."""

from integrated_calculator import demo_integrated_analysis


def main():
    """Do not run the historical synthetic comparisons."""
    return demo_integrated_analysis()


if __name__ == "__main__":
    main()
