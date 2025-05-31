import json
import os
import time

import numpy as np
import optuna
import pandas as pd
import requests
from optuna.trial import Trial
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
console.print("[bold green]ESPminer Optimization Setup[/bold green]")

device_ip = Prompt.ask("Enter ESPminer device URI", default="192.168.1.4")
study_name = Prompt.ask("Enter trial name", default="espmineroptim")
n_trials = IntPrompt.ask("Enter number of trials", default=10, show_default=True)
trial_length_s = IntPrompt.ask("Enter trial duration (min.)", default=1, show_default=True) * 60

# Frequency bounds
min_frequency_MHz = IntPrompt.ask("Enter minimum frequency (MHz)", default=400, show_default=True)
max_frequency_MHz = IntPrompt.ask("Enter maximum frequency (MHz)", default=550, show_default=True)

# Voltage bounds
min_coreVoltage_mV = IntPrompt.ask("Enter minimum coreVoltage (mV)", default=1000, show_default=True)
max_coreVoltage_mV = IntPrompt.ask("Enter maximum coreVoltage (mV)", default=1100, show_default=True)

limit_temp_degC = IntPrompt.ask("Enter temp limit (°C)", default=68, show_default=True)
limit_vrTemp_degC = IntPrompt.ask("Enter voltage regulator temp limit coreVoltage (°C)", default=68, show_default=True)

console.print("[bold red]Double check that the parameter ranges are safe and don't lead to overheat![/bold red]")
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
    "min_hashRate_THps",
    "max_hashRate_THps",
    "avg_hashRate_THps",
    "min_power_W",
    "max_power_W",
    "avg_power_W",
    "min_efficiency_JpTH",
    "max_efficiency_JpTH",
    "avg_efficiency_JpTH",
    "min_temp_degC",
    "max_temp_degC",
    "avg_temp_degC",
    "min_vrTemp_degC",
    "max_vrTemp_degC",
    "avg_vrTemp_degC",
]

if os.path.exists(csv_file):
    results_df = pd.read_csv(csv_file)
else:
    results_df = pd.DataFrame(columns=df_columns)


def get_device_stats(stats_url: str = STATS_URL, timeout: float = 15):
    stats_response = requests.get(stats_url, timeout=timeout)
    return stats_response.json()


def set_device_parameters(
    settings_url: str = SETTINGS_URL,
    reset_url: str = RESET_URL,
    frequency_MHz: float = min_frequency_MHz,
    coreVoltage_mV: float = min_coreVoltage_mV,
):
    headers = {"Content-Type": "application/json"}
    payload = {"frequency": int(frequency_MHz), "coreVoltage": int(coreVoltage_mV)}
    response = requests.patch(settings_url, headers=headers, data=json.dumps(payload), timeout=10)
    response.raise_for_status()
    time.sleep(1)

    console.print("[cyan]→ Restarting device...[/cyan]")
    response = requests.post(reset_url, timeout=10)
    response.raise_for_status()


def run_trial(trial: Trial, frequency_MHz: float, coreVoltage_mV: float):
    trial_number = trial.number

    try:
        console.rule(
            f"[bold green]Trial {trial_number}: freq={frequency_MHz:.0f} MHz, Vcore={coreVoltage_mV:.0f} mV[/bold green]"
        )

        set_device_parameters(frequency_MHz=frequency_MHz, coreVoltage_mV=coreVoltage_mV)

        console.print("[yellow]⏳ Waiting 30 seconds for system stabilization...[/yellow]")
        time.sleep(30)

        hashRates_THps = list()
        powers_W = list()
        temps_degC = list()
        vrTemps_degC = list()

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TimeElapsedColumn(),
            transient=True,
        ) as progress:
            task = progress.add_task("[green]Collecting system stats...", total=trial_length_s // 10)

            for _ in range(trial_length_s // 10):
                stats = get_device_stats()

                hashRate_THps = stats.get("hashRate", 0) / 1000.0
                power_W = stats.get("power", 0)
                temp_degC = stats.get("temp", 0)
                vrTemp_degC = stats.get("vrTemp", 0)

                actual_frequency_MHz = stats.get("frequency", 0)
                actual_coreVoltage_mV = stats.get("coreVoltage", 0)

                try:
                    np.testing.assert_allclose(actual_frequency_MHz, frequency_MHz, rtol=3 * 1e-3)
                    np.testing.assert_allclose(actual_coreVoltage_mV, coreVoltage_mV, rtol=3 * 1e-3)
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

                    console.print("[cyan]→ Resetting device to cooler minimal fallback parameters...[/cyan]")

                    set_device_parameters(frequency_MHz=min_frequency_MHz, coreVoltage_mV=min_coreVoltage_mV)

                    return

                hashRates_THps.append(hashRate_THps)
                powers_W.append(power_W)
                temps_degC.append(temp_degC)
                vrTemps_degC.append(vrTemp_degC)

                progress.advance(task)
                time.sleep(10)

        if not hashRates_THps or not powers_W:
            console.print("[bold red]No valid stats – aborting trial.[/bold red]")
            return

        hashRates_THps = np.asarray(hashRates_THps)
        powers_W = np.asarray(powers_W)
        temps_degC = np.asarray(temps_degC)
        vrTemps_degC = np.asarray(vrTemps_degC)

        efficiencies_JpTH = np.divide(powers_W, hashRates_THps)

        min_hashRate_THps = float(hashRates_THps.min())
        max_hashRate_THps = float(hashRates_THps.max())
        avg_hashRate_THps = float(hashRates_THps.mean())
        min_power_W = float(powers_W.min())
        max_power_W = float(powers_W.max())
        avg_power_W = float(powers_W.mean())
        min_temp_degC = float(temps_degC.min())
        max_temp_degC = float(temps_degC.max())
        avg_temp_degC = float(temps_degC.mean())
        min_vrTemp_degC = float(vrTemps_degC.min())
        max_vrTemp_degC = float(vrTemps_degC.max())
        avg_vrTemp_degC = float(vrTemps_degC.mean())
        min_efficiency_JpTH = float(efficiencies_JpTH.min())
        max_efficiency_JpTH = float(efficiencies_JpTH.max())
        avg_efficiency_JpTH = float(efficiencies_JpTH.mean())

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
            min_hashRate_THps,
            max_hashRate_THps,
            avg_hashRate_THps,
            min_power_W,
            max_power_W,
            avg_power_W,
            min_efficiency_JpTH,
            max_efficiency_JpTH,
            avg_efficiency_JpTH,
            min_temp_degC,
            max_temp_degC,
            avg_temp_degC,
            min_vrTemp_degC,
            max_vrTemp_degC,
            avg_vrTemp_degC,
        ]
        results_df.to_csv(csv_file, index=False)

        summary = Table(title=f"Trial {trial_number} Summary", show_lines=True)
        summary.add_column("Metric", style="cyan")
        summary.add_column("Value", style="magenta")
        summary.add_row("Avg. Hashrate", f"{avg_hashRate_THps:.2f} TH/s")
        summary.add_row("Avg. Power", f"{avg_power_W:.2f} W")
        summary.add_row("Avg. Efficiency", f"{avg_efficiency_JpTH:.2f} J/TH")

        console.print(summary)

        trial.set_user_attr("min_hashRate_THps", min_hashRate_THps)
        trial.set_user_attr("max_hashRate_THps", max_hashRate_THps)
        trial.set_user_attr("avg_hashRate_THps", avg_hashRate_THps)
        trial.set_user_attr("min_power_W", min_power_W)
        trial.set_user_attr("max_power_W", max_power_W)
        trial.set_user_attr("avg_power_W", avg_power_W)
        trial.set_user_attr("min_efficiency_JpTH", min_efficiency_JpTH)
        trial.set_user_attr("max_efficiency_JpTH", max_efficiency_JpTH)
        trial.set_user_attr("avg_efficiency_JpTH", avg_efficiency_JpTH)
        trial.set_user_attr("min_temp_degC", min_temp_degC)
        trial.set_user_attr("max_temp_degC", max_temp_degC)
        trial.set_user_attr("avg_temp_degC", avg_temp_degC)
        trial.set_user_attr("min_vrTemp_degC", min_vrTemp_degC)
        trial.set_user_attr("max_vrTemp_degC", max_vrTemp_degC)
        trial.set_user_attr("avg_vrTemp_degC", avg_vrTemp_degC)

        return avg_hashRate_THps, avg_efficiency_JpTH

    except Exception as e:
        console.print(f"[bold red]Exception:[/bold red] {e}")
        return


def run_study(trial: Trial):
    frequency_MHz = trial.suggest_float("frequency", float(min_frequency_MHz), float(max_frequency_MHz))
    coreVoltage_mV = trial.suggest_float("coreVoltage", float(min_coreVoltage_mV), float(max_coreVoltage_mV))
    return run_trial(trial, frequency_MHz, coreVoltage_mV)


def entrypoint():
    try:
        console.print("[blue]Reading pre-optimization ESPminer parameters...[blue]")
        stats = get_device_stats()

        pre_optim_frequency_MHz = stats.get("frequency")
        pre_optim_coreVoltage_mV = stats.get("coreVoltage")
        console.rule(
            f"[bold blue]Pre-optimization parameters: freq={pre_optim_frequency_MHz:.0f} MHz, Vcore={pre_optim_coreVoltage_mV:.0f} mV[/bold blue]"
        )
    except Exception as e:
        console.print(f"[bold red]Exception:[/bold red] {e}")
        console.print("Have you configured the correct ESPminer device URI?")
        return

    try:
        study = optuna.create_study(
            directions=["maximize", "minimize"],
            storage="sqlite:///espminer-optim-db.sqlite3",  # Specify the storage URL here.
            study_name=study_name,
            load_if_exists=True,
        )

        study.set_user_attr("device_ip", device_ip)
        study.set_user_attr("study_name", device_ip)
        study.set_user_attr("trial_length_s", trial_length_s)
        study.set_user_attr("pre_optim_frequency_MHz", pre_optim_frequency_MHz)
        study.set_user_attr("pre_optim_coreVoltage_mV", pre_optim_coreVoltage_mV)
        study.set_user_attr("min_frequency_MHz", min_frequency_MHz)
        study.set_user_attr("max_frequency_MHz", max_frequency_MHz)
        study.set_user_attr("min_coreVoltage_mV", min_coreVoltage_mV)
        study.set_user_attr("max_coreVoltage_mV", max_coreVoltage_mV)
        study.set_user_attr("limit_temp_degC", limit_temp_degC)
        study.set_user_attr("limit_vrTemp_degC", limit_vrTemp_degC)

        console.print("[bold green]Starting ESPminer Optimization...[/bold green]")
        study.optimize(run_study, n_trials=n_trials)

        console.rule("[bold green]Optimization Complete[/bold green]")
        console.print("Best trials per objective from multi-objective optimization:")

        for i, trial in enumerate(study.best_trials, start=1):
            table = Table(
                title=f"Best Multi-Objective Result {i}/{len(study.best_trials)} - Trial {trial.number} ",
                show_lines=True,
            )
            table.add_column("Parameter", style="cyan")
            table.add_column("Value", style="magenta")
            for key, val in trial.params.items():
                table.add_row(key, str(val))
            table.add_section()
            table.add_row("Objectives: hashRate (TH/s), efficiency (J/TH)", f"{trial.values}")
            console.print(table)

        if study.best_trials:
            console.rule("[bold green]Committing the Best Multi-Objective Result 1/2 Parameters to Device[/bold green]")

            best_trial_frequency_MHz = study.best_trials[0].params.get("frequency", min_frequency_MHz)
            best_trial_coreVoltage_mV = study.best_trials[0].params.get("coreVoltage", min_coreVoltage_mV)

            console.print(
                f"Setting the parameters from best multi-objective result 1/2: freq={best_trial_frequency_MHz:.0f} MHz, Vcore={best_trial_coreVoltage_mV:.0f} mV"
            )

            set_device_parameters(frequency_MHz=best_trial_frequency_MHz, coreVoltage_mV=best_trial_coreVoltage_mV)

            console.print("[yellow]⏳ Waiting 30 seconds for system restart...[/yellow]")
            time.sleep(30)

            stats = get_device_stats()

            actual_frequency_MHz = stats.get("frequency", 0)
            actual_coreVoltage_mV = stats.get("coreVoltage", 0)

            try:
                np.testing.assert_allclose(actual_frequency_MHz, best_trial_frequency_MHz, rtol=3 * 1e-3)
                np.testing.assert_allclose(actual_coreVoltage_mV, best_trial_coreVoltage_mV, rtol=3 * 1e-3)
            except AssertionError:
                console.print_exception()
                console.print("[bold red]Real parameter not set within tolerance of 1%[/bold red]")
                console.print()
                raise Exception("Real parameter not set within tolerance of 1%")

            console.print("[bold green]Parameters from best multi-objective result 1/2 are now set.[/bold green]")

    except (KeyboardInterrupt, Exception) as e:
        if isinstance(e, KeyboardInterrupt):
            console.print("[bold yellow]Canceled by user keyboard interrupt.[/bold yellow]")
        else:
            console.print(f"[bold red]Exception:[/bold red] {e}")

        console.print(
            f"Reverting the parameters to pre-optimization configuration: freq={pre_optim_frequency_MHz:.0f} MHz, Vcore={pre_optim_coreVoltage_mV:.0f} mV"
        )

        set_device_parameters(frequency_MHz=pre_optim_frequency_MHz, coreVoltage_mV=pre_optim_coreVoltage_mV)

        console.print("[yellow]⏳ Waiting 30 seconds for system restart...[/yellow]")
        time.sleep(30)

        stats = get_device_stats()

        actual_frequency_MHz = stats.get("frequency", 0)
        actual_coreVoltage_mV = stats.get("coreVoltage", 0)

        try:
            np.testing.assert_allclose(actual_frequency_MHz, pre_optim_frequency_MHz, rtol=3 * 1e-3)
            np.testing.assert_allclose(actual_coreVoltage_mV, pre_optim_coreVoltage_mV, rtol=3 * 1e-3)
        except AssertionError:
            console.print_exception()
            console.print("[bold red]Real parameter not set within tolerance of 1%[/bold red]")
            console.print()
            raise Exception("Real parameter not set within tolerance of 1%")

        console.print("[bold green]Parameters reverted to pre-optimization configuration.[/bold green]")


if __name__ == "__main__":
    entrypoint()
