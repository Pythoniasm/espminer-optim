# ⚡️ ESPminer Optimizer

Tweak your ESPminer for max hashrate, minimum watts, and thermally clean operation - automagically.
Built for the modern sovereign miner, optimized for freedom.

> “Don’t trust. Verify. Solo-mine. Then autotune.”  -  Satoshi, probably

---

## 🛠 What Is This?

A CLI-based tuner that runs multi-objective optimization on your ESPminer.
It finds the best balance of:
- 🧠 **Hashrate** (TH/s)
- 🔌 **Efficiency** (J/TH)
- 🌡 **Thermal Constraints**

All in real-time using [Optuna](https://optuna.org/) and your device’s REST API.

---

## 🚀 Features

- 🎛 Optimizes frequency & core voltage
- 🧪 Runs real-time stats collection from the ESPminer
- 🧯 Aborts trials if temps go too high
- 📈 Logs every trial to a CSV
- 📚 Saves study results to a local SQLite DB
- 🌈 Uses `rich` for pretty CLI output

---

## ☠️ Warnings

- This directly modifies your ESPminer settings and restarts the miner every trial.
- Know your thermal + voltage limits.

To enhance your ESPminer optimization workflow, consider integrating the Optuna Dashboard for real-time visualization and analysis of your optimization runs. This tool provides interactive graphs and detailed trial data, allowing you to monitor the optimization process effectively.

---

## ⚙️ Requirements

- Python 3
- A ESPminer running firmware with the `/api/system` endpoints

Install dependencies:
```bash
pip install .
```

---

## 🧪 Running the Optimizer

```bash
python optimize.py
```

You’ll be prompted for:
- ESPminer IP address
- Frequency & voltage range
- Trial count & duration
- Temperature limits

Then the tuner gets to work - configuring, restarting, collecting stats, and evolving toward greatness. 🙌

Each trial logs:
- Frequency (MHz)
- Core Voltage (mV)
- Avg Hashrate (TH/s)
- Avg Power (W)
- Efficiency (J/TH)
- Objective Score

---

## 🛠️ Setting Up Optuna Dashboard

1. **Install Optuna Dashboard**:

   ```bash
   pip install optuna-dashboard
   ```

2. **Run Your Optimization Script**

3. **Launch the Dashboard**:

   In a separate terminal, start the dashboard:

   ```bash
   optuna-dashboard sqlite:///espminer-optim-db.sqlite3
   ```

   This will start a local server, typically accessible at `http://localhost:8080/`.

### 📊 Features of Optuna Dashboard

- **Interactive Visualization**: Monitor optimization history, parameter importances, and trial details through dynamic graph.

- **Real-Time Updates**: Observe the optimization progress as new trials are complete.

- **Trial Management**: Filter, sort, and inspect individual trials to gain insights into the optimization proces.

For more information and advanced usage, refer to [Optuna Dashboard documentation](https://optuna-dashboard.readthedocs.io/).
By incorporating the Optuna Dashboard into your workflow, you can gain deeper insights into your optimization process, leading to more efficient and effective tuning of your ESPminer device.

---

⚡️⛏️ Built for Bitaxe
