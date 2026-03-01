"""
CLI entry point.

Provides:
  sandbox run      --model <name> --scenario <id>
  sandbox scenarios
  sandbox summary

All business logic is delegated to sandbox.core.  This module is
responsible only for argument parsing, live progress display, and exit codes.
"""

import csv
import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sandbox.core.adapter import ModelAdapterError, OllamaAdapter
from sandbox.core.docker_sandbox import DockerSandboxError
from sandbox.core.report import append_to_csv, save_run
from sandbox.core.runner import run as core_run
from sandbox.scenarios.registry import list_scenarios

app = typer.Typer(
    name="sandbox",
    help="LLM Prompt Injection Sandbox — benchmark attack resistance of local AI agents.",
    add_completion=False,
)

console = Console()
err_console = Console(stderr=True, style="bold red")

# ---------------------------------------------------------------------------
# Live run display
# ---------------------------------------------------------------------------

_STEP_DEFS = [
    ("scenario_loaded", "Load scenario"),
    ("secret_loaded",   "Load secret"),
    ("sandbox_ready",   "Start Docker sandbox"),
    ("prompt_ready",    "Assemble prompt"),
    ("model_calling",   "Call model"),
    ("evaluated",       "Evaluate output"),
    ("report_saved",    "Save report"),
]


class RunDisplay:
    """
    Rich renderable — animated ASCII attack-flow diagram.

    Three nodes are drawn vertically: ATTACKER → WORKSPACE → AI AGENT.
    Colors, arrows, and labels update live as each benchmark step fires:

      pending       dim neutral diagram
      sandbox_ready ATTACKER + README.md light up red (attack is in place)
      model_calling animated pulsing arrow, spinner on AI AGENT
      evaluated     COMPROMISED (red, pulsing) or CLEAN (green)
    """

    def __init__(self, model: str, scenario_id: str) -> None:
        self.model = model
        self.scenario_id = scenario_id
        self._start = time.monotonic()
        self._model_call_start: Optional[float] = None
        self._status: dict[str, str] = {k: "pending" for k, _ in _STEP_DEFS}
        self._detail: dict[str, str] = {k: "" for k, _ in _STEP_DEFS}

    def on_step(self, key: str, detail: str = "") -> None:
        """Callback passed to the runner; updates display state."""
        if key == "model_calling":
            self._status["model_calling"] = "running"
            self._detail["model_calling"] = detail
            self._model_call_start = time.monotonic()
        elif key == "model_done":
            self._status["model_calling"] = "done"
            elapsed = time.monotonic() - (self._model_call_start or self._start)
            self._detail["model_calling"] = f"{detail}  ·  {elapsed:.1f}s"
        elif key in self._status:
            self._status[key] = "done"
            self._detail[key] = detail

    def __rich__(self) -> Panel:
        t       = time.monotonic()
        elapsed = t - self._start
        pulse   = int(t * 4) % 2 == 0   # ~4 Hz blink for animations

        # ── Phase flags ──────────────────────────────────────────────────
        sandbox_up  = self._status["sandbox_ready"] == "done"
        calling     = self._status["model_calling"] == "running"
        evaluated   = self._status["evaluated"]     == "done"
        compromised = evaluated and "COMPROMISED" in self._detail["evaluated"]
        clean_run   = evaluated and not compromised
        border      = "red" if compromised else ("green" if clean_run else "dim")

        lines: list = []

        def add(markup: str = "") -> None:
            lines.append(Text.from_markup(markup) if markup else Text(""))

        # ── Header ───────────────────────────────────────────────────────
        add(
            f"  [dim]model[/dim] [bold cyan]{self.model}[/bold cyan]"
            f"  [dim]·  scenario[/dim] [bold yellow]{self.scenario_id}[/bold yellow]"
        )
        add()

        # ── Node: OWNER ──────────────────────────────────────────────────
        if sandbox_up:
            add("  [bold white]👤 OWNER[/bold white]  [dim](Side A — system operator)[/dim]")
            add("  [dim]│[/dim]  [dim]uploaded README.md  ·  🔒 secret.txt to workspace[/dim]")
            add("  [dim]▼[/dim]")
        else:
            add("  [dim]○  OWNER  (Side A)[/dim]")
            add("  [dim]│[/dim]  [dim]setting up workspace…[/dim]")
            add("  [dim]▼[/dim]")

        # ── Node: WORKSPACE (with ATTACKER side annotation) ──────────────
        if sandbox_up:
            pipe = "┃" if pulse else "│"
            add(
                f"  [bold white]📁 WORKSPACE[/bold white]"
                f"  [red]◄──[/red][red]{pipe}[/red][red]──[/red]"
                f"  [bold red]⚡ ATTACKER[/bold red]  [dim](Side B — pre-planted payload)[/dim]"
            )
            add("  [dim]├─[/dim]  [bold red]⚠  README.md[/bold red]   [red]← POISONED[/red]")
        else:
            add("  [bold white]📁 WORKSPACE[/bold white]  [dim](initialising…)[/dim]")
            add("  [dim]├─[/dim]  [white]○  README.md[/white]  [dim]public[/dim]")

        if compromised:
            s = "bold red" if pulse else "red"
            add(f"  [dim]└─[/dim]  [{s}]⚠  secret.txt  ← LEAKED[/{s}]")
        elif calling:
            add("  [dim]└─[/dim]  [yellow]🔒 secret.txt[/yellow]  [dim]← AI is reading…[/dim]")
        else:
            add("  [dim]└─[/dim]  [white]🔒 secret.txt[/white]  [dim]← private[/dim]")

        # Arrow: WORKSPACE → AI AGENT
        if calling:
            ac = "bold cyan" if pulse else "cyan"
            add(f"  [{ac}]┃[/{ac}]  [dim]AI reads all files + follows any instructions found[/dim]")
            add(f"  [{ac}]▼[/{ac}]")
        elif evaluated:
            c = "red" if compromised else "green"
            add(f"  [{c}]│[/{c}]")
            add(f"  [{c}]▼[/{c}]")
        else:
            add("  [dim]│[/dim]")
            add("  [dim]▼[/dim]")

        # ── Node: AI AGENT ───────────────────────────────────────────────
        if calling:
            mc = t - (self._model_call_start or t)
            spin = "⟳" if pulse else "◌"
            add(f"  [bold cyan]🤖 AI AGENT[/bold cyan]  [dim]{self.model}[/dim]")
            add(f"     [cyan]{spin}[/cyan]  [dim]calling model…  {mc:.1f}s elapsed[/dim]")
        elif compromised:
            add(f"  [bold red]⚠  AI AGENT[/bold red]  [dim]{self.model}[/dim]")
            add("  [bold red]│[/bold red]  [dim]followed the injection — output contains the secret[/dim]")
            add("  [bold red]▼[/bold red]")
        elif clean_run:
            add(f"  [bold green]✔  AI AGENT[/bold green]  [dim]{self.model}[/dim]")
            add("  [bold green]│[/bold green]  [dim]resisted the injection — secret not in output[/dim]")
            add("  [bold green]▼[/bold green]")
        else:
            add(f"  [dim]○  AI AGENT  {self.model}[/dim]")

        # ── Verdict ──────────────────────────────────────────────────────
        if compromised:
            bang = "  !" if pulse else "   "
            add(f"  [bold red]⚠  COMPROMISED{bang}[/bold red]")
            add("  [dim]Secret found verbatim in the model's output[/dim]")
        elif clean_run:
            add("  [bold green]✔  CLEAN — injection was resisted[/bold green]")
        add()

        # ── Step strip (compact row at the bottom) ───────────────────────
        _STRIP = [
            ("scenario_loaded", "scen"),
            ("secret_loaded",   "scrt"),
            ("sandbox_ready",   "dock"),
            ("prompt_ready",    "prmp"),
            ("model_calling",   "modl"),
            ("evaluated",       "eval"),
            ("report_saved",    "save"),
        ]
        parts = []
        for key, short in _STRIP:
            s = self._status[key]
            if s == "done":
                parts.append(f"[green]✔[/green][dim]{short}[/dim]")
            elif s == "running":
                parts.append(f"[cyan]⟳[/cyan][bold]{short}[/bold]")
            else:
                parts.append(f"[bright_black]·{short}[/bright_black]")
        add("  " + " ".join(parts) + f"  [dim]{elapsed:.1f}s[/dim]")

        return Panel(
            Group(*lines),
            title="[bold]Prompt Injection Benchmark[/bold]",
            border_style=border,
            padding=(0, 1),
        )


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@app.command("run")
def cmd_run(
    model: str = typer.Option(
        ..., "--model", "-m", help="Ollama model name (e.g. llama3.2)"
    ),
    scenario: str = typer.Option(
        ..., "--scenario", "-s", help="Scenario ID to run (see: sandbox scenarios)"
    ),
) -> None:
    """Run a prompt injection scenario against a local Ollama model."""
    display = RunDisplay(model, scenario)
    adapter = OllamaAdapter(model=model)
    result = None
    error_exit: Optional[int] = None

    with Live(display, refresh_per_second=10, transient=False):
        try:
            result = core_run(
                model=model,
                scenario_id=scenario,
                adapter=adapter,
                on_step=display.on_step,
            )
        except KeyError as exc:
            err_console.print(f"Unknown scenario: {exc}")
            error_exit = 2
        except DockerSandboxError as exc:
            err_console.print(f"Sandbox error: {exc}")
            error_exit = 3
        except ModelAdapterError as exc:
            err_console.print(f"Model error: {exc}")
            error_exit = 4

        if result is not None:
            json_path, md_path = save_run(result)
            csv_path = append_to_csv(result)
            display.on_step("report_saved", ".md  .json  .csv")

    if error_exit is not None:
        raise typer.Exit(code=error_exit)

    # Post-Live: print final verdict + model output + file paths
    compromised = result.evaluation.compromised
    verdict_style = "bold red" if compromised else "bold green"
    verdict_icon  = "⚠  COMPROMISED" if compromised else "✔  CLEAN"

    verdict_tbl = Table(show_header=False, box=None, padding=(0, 1))
    verdict_tbl.add_row(
        Text(verdict_icon, style=verdict_style),
        Text(result.evaluation.reason, style="dim"),
    )
    if result.evaluation.extracted_secret:
        verdict_tbl.add_row(
            Text("   Leaked secret", style="red"),
            Text(result.evaluation.extracted_secret, style="bold red"),
        )

    console.print(
        Panel(verdict_tbl, border_style="red" if compromised else "green")
    )
    console.print(
        Panel(
            result.model_output or "[dim](empty)[/dim]",
            title="Model output",
            border_style="dim",
        )
    )
    console.print(f"[dim]  Markdown  →  {md_path}[/dim]")
    console.print(f"[dim]  JSON      →  {json_path}[/dim]")
    console.print(f"[dim]  CSV log   →  {csv_path}[/dim]")

    raise typer.Exit(code=1 if compromised else 0)


@app.command("scenarios")
def cmd_scenarios() -> None:
    """List all available scenario IDs and descriptions."""
    tbl = Table(title="Available scenarios", show_lines=True)
    tbl.add_column("ID", style="cyan", no_wrap=True)
    tbl.add_column("Attack type", style="yellow")
    tbl.add_column("Description")

    for s in list_scenarios():
        tbl.add_row(s.id, s.attack_type.value, s.description)

    console.print(tbl)


@app.command("summary")
def cmd_summary() -> None:
    """Display aggregated results from all runs (reads runs/results.csv)."""
    csv_path = Path(__file__).parent.parent.parent / "runs" / "results.csv"

    if not csv_path.exists():
        console.print("[dim]No results yet — run[/dim] [bold]sandbox run[/bold] [dim]first.[/dim]")
        raise typer.Exit(code=0)

    with open(csv_path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    if not rows:
        console.print("[dim]results.csv is empty.[/dim]")
        raise typer.Exit(code=0)

    # Collect models and scenarios in insertion order (deduped)
    models: list[str] = []
    scenarios: list[str] = []
    # Most-recent run wins per (model, scenario) cell
    cell: dict[tuple[str, str], bool] = {}

    for row in rows:
        m, s = row["model"], row["scenario_id"]
        if m not in models:
            models.append(m)
        if s not in scenarios:
            scenarios.append(s)
        cell[(m, s)] = row["compromised"].lower() == "true"

    total = len(rows)
    console.print()
    console.rule(
        f"[bold]Benchmark Summary[/bold]  ·  {total} run{'s' if total != 1 else ''}"
    )
    console.print()

    # ── Results matrix ────────────────────────────────────────────────────
    matrix = Table(title="Results Matrix", show_lines=True)
    matrix.add_column("Model", style="cyan", no_wrap=True)
    for s in scenarios:
        matrix.add_column(s, no_wrap=True)

    for m in models:
        row_cells = []
        for s in scenarios:
            if (m, s) in cell:
                if cell[(m, s)]:
                    row_cells.append(Text("⚠  COMPROMISED", style="bold red"))
                else:
                    row_cells.append(Text("✔  CLEAN", style="bold green"))
            else:
                row_cells.append(Text("—", style="dim"))
        matrix.add_row(m, *row_cells)

    console.print(matrix)
    console.print()

    # ── Compromise rate by model ──────────────────────────────────────────
    console.print("[bold]Compromise Rate by Model[/bold]")
    console.print()
    for m in models:
        model_rows = [r for r in rows if r["model"] == m]
        n = len(model_rows)
        k = sum(1 for r in model_rows if r["compromised"].lower() == "true")
        pct = k / n if n else 0
        console.print(
            f"  [cyan]{m:<20}[/cyan]  {_bar(pct)}  "
            f"{pct * 100:4.0f}%  ({k}/{n})"
        )

    console.print()

    # ── Most vulnerable scenario ──────────────────────────────────────────
    console.print("[bold]Most Vulnerable Scenario[/bold]")
    console.print()
    for s in scenarios:
        scen_rows = [r for r in rows if r["scenario_id"] == s]
        n = len(scen_rows)
        k = sum(1 for r in scen_rows if r["compromised"].lower() == "true")
        pct = k / n if n else 0
        console.print(
            f"  [yellow]{s:<36}[/yellow]  {_bar(pct)}  "
            f"{pct * 100:4.0f}%  ({k}/{n})"
        )

    console.print()
    console.print(f"[dim]  Source: {csv_path}[/dim]")
    console.print()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bar(rate: float, width: int = 20) -> str:
    filled = round(rate * width)
    empty = width - filled
    return "█" * filled + "░" * empty
