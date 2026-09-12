"""Agent eval suite: replay a fixed web to the scan agent and score what it records.

See evals/README.md for what the cases cover and how to run them.
"""

from .runner import run_cli

__all__ = ["run_cli"]
