"""
Report generator.

Responsibilities:
  - Produce a human-readable Markdown report from a RunResult.
  - Persist the RunResult as a JSON artifact in the /runs directory.
  - Return the paths of both written files.

Both formats are written atomically (write to final path directly) since
runs are local and single-process. No business logic belongs here beyond
serialisation and formatting.
"""

import csv
import dataclasses
import json
from pathlib import Path
from typing import Tuple

from sandbox.core.types import RunResult

# Project-root /runs directory, derived from this file's location.
_DEFAULT_RUNS_DIR = Path(__file__).parent.parent.parent / "runs"

_CSV_COLUMNS = [
    "timestamp", "model", "scenario_id", "scenario_name",
    "attack_type", "compromised", "reason", "extracted_secret",
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def save_run(
    result: RunResult,
    runs_dir: Path = _DEFAULT_RUNS_DIR,
) -> Tuple[Path, Path]:
    """
    Persist a RunResult as JSON + Markdown inside ``runs_dir``.

    The filename stem encodes timestamp, model, and scenario ID so that
    artefacts sort chronologically and are unambiguous without a database.

    Args:
        result:   The completed run to persist.
        runs_dir: Directory to write files into.  Created if absent.

    Returns:
        ``(json_path, markdown_path)``
    """
    runs_dir.mkdir(parents=True, exist_ok=True)

    stem = _filename_stem(result)

    json_path = runs_dir / f"{stem}.json"
    md_path = runs_dir / f"{stem}.md"

    json_path.write_text(_to_json(result), encoding="utf-8")
    md_path.write_text(generate_markdown(result), encoding="utf-8")

    return json_path, md_path


def generate_markdown(result: RunResult) -> str:
    """
    Render a RunResult as a Markdown report string.

    Args:
        result: The completed run.

    Returns:
        Markdown-formatted string ready for writing to a file.
    """
    ev = result.evaluation
    outcome_line = "**COMPROMISED** ⚠️" if ev.compromised else "**CLEAN** ✅"

    lines = [
        "# Prompt Injection Benchmark — Run Report",
        "",
        "## Metadata",
        "",
        "| Field        | Value |",
        "|:-------------|:------|",
        f"| Model        | `{result.model}` |",
        f"| Scenario ID  | `{result.scenario_id}` |",
        f"| Scenario     | {result.scenario_name} |",
        f"| Attack Type  | `{result.attack_type}` |",
        f"| Timestamp    | {result.timestamp} |",
        "",
        "## Outcome",
        "",
        outcome_line,
        "",
        "| Field            | Value |",
        "|:-----------------|:------|",
        f"| Compromised      | {'Yes' if ev.compromised else 'No'} |",
        f"| Reason           | {ev.reason} |",
    ]

    if ev.extracted_secret is not None:
        lines.append(f"| Extracted secret | `{ev.extracted_secret}` |")

    lines += [
        "",
        "## Model Output",
        "",
        "```",
        result.model_output,
        "```",
        "",
    ]

    return "\n".join(lines)


def append_to_csv(
    result: RunResult,
    runs_dir: Path = _DEFAULT_RUNS_DIR,
) -> Path:
    """
    Append one row to the aggregated ``results.csv`` inside ``runs_dir``.

    Creates the file (with header) on the first call, then appends
    subsequent rows without repeating the header.  The CSV is directly
    importable into Excel, Google Sheets, pandas, or any chart tool.

    Args:
        result:   The completed run to log.
        runs_dir: Directory containing (or to contain) ``results.csv``.

    Returns:
        Path to the CSV file.
    """
    runs_dir.mkdir(parents=True, exist_ok=True)
    csv_path = runs_dir / "results.csv"
    is_new = not csv_path.exists()

    with open(csv_path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_COLUMNS)
        if is_new:
            writer.writeheader()
        writer.writerow({
            "timestamp": result.timestamp,
            "model": result.model,
            "scenario_id": result.scenario_id,
            "scenario_name": result.scenario_name,
            "attack_type": result.attack_type,
            "compromised": result.evaluation.compromised,
            "reason": result.evaluation.reason,
            "extracted_secret": result.evaluation.extracted_secret or "",
        })

    return csv_path


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _filename_stem(result: RunResult) -> str:
    """
    Build a safe, sortable filename stem from run metadata.

    Format: ``<timestamp>_<model>_<scenario_id>``
    Colons and slashes in model names are replaced with hyphens.
    """
    ts = result.timestamp[:19].replace(":", "-")  # 2024-01-01T00-00-00
    model_slug = result.model.replace(":", "-").replace("/", "-")
    return f"{ts}_{model_slug}_{result.scenario_id}"


def _to_json(result: RunResult) -> str:
    """Serialise a RunResult (including nested dataclasses) to JSON."""
    return json.dumps(dataclasses.asdict(result), indent=2, ensure_ascii=False)
