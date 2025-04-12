import json
import os
import time

import numpy as np
import optuna
import pandas as pd
import requests
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table


# Initialize rich console
console = Console()

# Prompt user for setup
console.print("[bold green]Bitaxe Optimization Setup[/bold green]")

device_ip = Prompt.ask("Enter Bitaxe device URI", default="192.168.1.4")
study_name = Prompt.ask("Enter trial name", default="espmineroptim")
n_trials = IntPrompt.ask("Enter number of trials", default=10, show_default=True)
trial_length_s = IntPrompt.ask("Enter trial duration (min.)", default=1, show_default=True) * 60

# Frequency bounds
min_frequency_MHz = IntPrompt.ask("Enter minimum frequency (MHz)", default=400, show_default=True)
max_frequency_MHz = IntPrompt.ask("Enter maximum frequency (MHz)", default=625, show_default=True)

# Voltage bounds
min_coreVoltage_mV = IntPrompt.ask("Enter minimum coreVoltage (mV)", default=1000, show_default=True)
max_coreVoltage_mV = IntPrompt.ask("Enter maximum coreVoltage (mV)", default=1250, show_default=True)

limit_temp_degC = IntPrompt.ask("Enter temp limit (°C)", default=68, show_default=True)
limit_vrTemp_degC = IntPrompt.ask("Enter voltage regulator temp limit coreVoltage (°C)", default=78, show_default=True)
confirmed = Confirm.ask("Check your inputs above. Start optimizing?")
if not confirmed:
    exit(0)

# Endpoints
SETTINGS_URL = f"http://{device_ip}/api/system"
RESET_URL = f"http://{device_ip}/api/system/restart"
STATS_URL = f"http://{device_ip}/api/system/info"

# Scoring weights
# hashRate_factor = 20.0
# efficiency_factor = 1.0

# DataFrame setup
csv_file = f"{study_name}_results.csv"
df_columns = [
    "device_ip",
    "study_name",
    "n_trials",
    "trial_length_s",
    "min_frequency_MHz",
    "max_frequency_MHz",
    "min_coreVoltage_mV",
    "max_coreVoltage_mV",
    "limit_temp_degC",
    "limit_vrTemp_degC",
    "trial_number",
    "frequency_MHz",
    "coreVoltage_mV",
    "avg_hashRate_THps",
    "avg_power_W",
    "avg_efficiency_JpTH",
]

if os.path.exists(csv_file):
    results_df = pd.read_csv(csv_file)
else:
    results_df = pd.DataFrame(columns=df_columns)


def run_trial(frequency_MHz, coreVoltage_mV, trial_number):
    try:
        console.rule(
            f"[bold green]Trial {trial_number}: freq={frequency_MHz:.0f}MHz, Vcore={coreVoltage_mV:.0f}mV[/bold green]"
        )

        headers = {"Content-Type": "application/json"}
        payload = {"frequency": int(frequency_MHz), "coreVoltage": int(coreVoltage_mV)}

        response = requests.patch(SETTINGS_URL, headers=headers, data=json.dumps(payload), timeout=10)
        response.raise_for_status()
        time.sleep(1)

        console.print("[cyan]→ Restarting device...[/cyan]")
        restart_response = requests.post(RESET_URL, timeout=10)
        restart_response.raise_for_status()

        console.print("[yellow]⏳ Waiting 30 seconds for system stabilization...[/yellow]")
        time.sleep(30)

        hashRates_THps = []
        powers_W = []

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TimeElapsedColumn(),
            transient=True,
        ) as progress:
            task = progress.add_task("[green]Collecting system stats...", total=trial_length_s // 10)

            for _ in range(trial_length_s // 10):
                stats_response = requests.get(STATS_URL, timeout=10)
                stats = stats_response.json()
                temp_degC = stats.get("temp", 0)
                vrTemp_degC = stats.get("vrTemp", 0)
                hashRate_THps = stats.get("hashRate", 0) / 1000.0
                power_W = stats.get("power", 0)

                actual_frequency_MHz = stats.get("frequency", 0)
                actual_coreVoltage_mV = stats.get("coreVoltage", 0)

                try:
                    np.testing.assert_allclose(actual_frequency_MHz, frequency_MHz, rtol=1e-3)
                    np.testing.assert_allclose(actual_coreVoltage_mV, coreVoltage_mV, rtol=1e-3)
                except AssertionError:
                    console.print_exception()
                    console.print("[bold red]Real parameter not set within tolerance of 1%[/bold red]")
                    console.print()
                    return

                efficiency_JpTH = power_W / hashRate_THps
                console.print(
                    f"[blue] Stats:[/blue] temp={temp_degC:.1f}°C,vrTemp={vrTemp_degC:.1f}°C,hashRate={hashRate_THps:.2f}TH/s,power={power_W:.1f}W,eff={efficiency_JpTH:.1f}J/TH"
                )

                if temp_degC > limit_temp_degC or vrTemp_degC > limit_vrTemp_degC:
                    console.print("[bold red]❌ Temperature too high! Aborting.[/bold red]")
                    return

                hashRates_THps.append(hashRate_THps)
                powers_W.append(power_W)
                progress.advance(task)
                time.sleep(10)

        if not hashRates_THps or not powers_W:
            console.print("[bold red]No valid stats – aborting trial.[/bold red]")
            return

        avg_hashRate_THps = sum(hashRates_THps) / len(hashRates_THps)
        avg_power_W = sum(powers_W) / len(powers_W)
        avg_efficiency_JpTH = avg_power_W / avg_hashRate_THps if avg_hashRate_THps != 0 else 0
        # scoring = (
        #     hashRate_factor * avg_hashRate_THps
        #     - efficiency_factor * avg_efficiency_JpTH
        # )

        results_df.loc[len(results_df)] = [
            device_ip,
            study_name,
            n_trials,
            trial_length_s,
            min_frequency_MHz,
            max_frequency_MHz,
            min_coreVoltage_mV,
            max_coreVoltage_mV,
            limit_temp_degC,
            limit_vrTemp_degC,
            trial_number,
            frequency_MHz,
            coreVoltage_mV,
            avg_hashRate_THps,
            avg_power_W,
            avg_efficiency_JpTH,
        ]
        results_df.to_csv(csv_file, index=False)

        summary = Table(title=f"Trial {trial_number} Summary", show_lines=True)
        summary.add_column("Metric", style="cyan")
        summary.add_column("Value", style="magenta")
        summary.add_row("Avg Hashrate", f"{avg_hashRate_THps:.2f} TH/s")
        summary.add_row("Avg Power", f"{avg_power_W:.2f} W")
        summary.add_row("Efficiency", f"{avg_efficiency_JpTH:.2f} ")

        console.print(summary)

        return avg_hashRate_THps, avg_efficiency_JpTH

    except Exception as e:
        console.print(f"[bold red]Exception:[/bold red] {e}")
        return


def run_study(trial):
    frequency_MHz = trial.suggest_float("frequency", float(min_frequency_MHz), float(max_frequency_MHz))
    coreVoltage_mV = trial.suggest_float("coreVoltage", float(min_coreVoltage_mV), float(max_coreVoltage_mV))
    return run_trial(frequency_MHz, coreVoltage_mV, trial.number)


def entrypoint():
    console.print("[bold green]Starting Bitaxe Optimization...[/bold green]")
    study = optuna.create_study(
        directions=["maximize", "minimize"],
        storage="sqlite:///espminer-optim-db.sqlite3",  # Specify the storage URL here.
        study_name=study_name,
        load_if_exists=True,
    )

    study.set_user_attr("device_ip", device_ip)
    study.set_user_attr("study_name", device_ip)
    study.set_user_attr("trial_length_s", trial_length_s)
    study.set_user_attr("min_frequency_MHz", min_frequency_MHz)
    study.set_user_attr("max_frequency_MHz", max_frequency_MHz)
    study.set_user_attr("min_coreVoltage_mV", min_coreVoltage_mV)
    study.set_user_attr("max_coreVoltage_mV", max_coreVoltage_mV)
    study.set_user_attr("limit_temp_degC", limit_temp_degC)
    study.set_user_attr("limit_vrTemp_degC", limit_vrTemp_degC)

    study.optimize(run_study, n_trials=n_trials)

    console.rule("[bold green]Optimization Complete[/bold green]")
    final = Table(title="Best Trial Results", show_lines=True)
    final.add_column("Parameter", style="cyan")
    final.add_column("Value", style="magenta")
    for trial in study.best_trials:
        for key, val in trial.params.items():
            final.add_row(key, str(val))

    final.add_row("objectives", f"{trial.values}")

    console.print(final)


if __name__ == "__main__":
    entrypoint()
