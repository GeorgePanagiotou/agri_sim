"""Compatibility command for the regional AgriSim decision engine."""
import sys

from agrisim.config import OUTPUTS
from agrisim.decision_engine import pipeline


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    # The old README command operates on the saved pilot outputs.
    source_options = {"--sowing-csv", "--risk-csv", "--power"}
    if "--skip-vegetation" in args and not any(arg.split("=")[0] in source_options for arg in args):
        args = [*args, "--sowing-csv", str(OUTPUTS / "sowing_weeks.csv"),
                "--risk-csv", str(OUTPUTS / "risk_daily.csv")]
    pipeline.main([arg for arg in args if arg != "--skip-vegetation"])


if __name__ == "__main__":
    main()
