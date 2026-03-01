"""
Secret loader.

Reads the benchmark secret from the package's assets directory.
This value is used exclusively by the evaluator to detect leakage in model output.
It must never be logged or embedded in any prompt sent to the model.
"""

from pathlib import Path

_ASSETS_DIR = Path(__file__).parent.parent / "assets"
SECRET_PATH = _ASSETS_DIR / "secret.txt"


def load_secret() -> str:
    """
    Return the contents of secret.txt (stripped of trailing whitespace).

    Raises:
        FileNotFoundError: If secret.txt is missing from the assets directory.
    """
    return SECRET_PATH.read_text(encoding="utf-8").strip()
