🇳🇱 [Nederlands](README_NL.md) &nbsp;|&nbsp; 🇬🇧 [English](README.md)
# Victoria

**Water Quality Simulator for Hydraulic Distribution Networks**

[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/)
[![EPyNet](https://img.shields.io/badge/epynet-2025-orange)](https://github.com/pyepanet/epynet)
[![PhreeqPython](https://img.shields.io/badge/phreeqpython-required-red)](https://github.com/Vitens/phreeqpython)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Version](https://img.shields.io/badge/version-1.1.0-informational)](CHANGELOG.md)

Victoria simulates water chemistry quality in hydraulic distribution networks by coupling PHREEQC geochemistry with EPyNet hydraulics. Water is tracked as **discrete parcels** inside pipes (FIFO) and fully mixed at junctions and tanks — without the numerical diffusion inherent to Eulerian methods.

🇳🇱 [Nederlandse versie](README_NL.md)

---

## Table of Contents

- [Features](#features)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [API Reference](#api-reference)
  - [Victoria class](#victoria-class)
  - [Models](#models)
  - [Solver & HydraulicCache](#solver--hydrauliccache)
  - [Quality](#quality)
  - [FIFO & Pipe](#fifo--pipe)
  - [MIX & Node Models](#mix--node-models)
  - [PipeSegmentation](#pipesegmentation)
- [Advanced Usage](#advanced-usage)
- [Parcel Merging](#parcel-merging)
- [FAQ](#faq)
- [Glossary](#glossary)
- [Changelog](#changelog)

---

## Features

- **FIFO pipe model** with parcel merging — limits list growth in long pipes or at low flow velocities
- **Full PHREEQC geochemistry** at junctions via PhreeqPython (`pp.mix_solutions`)
- **Five node/tank models**: Junction, Reservoir, Tank\_CSTR, Tank\_FIFO, Tank\_LIFO
- **Flow reversal detection** — parcels are automatically mirrored when flow reverses
- **Iterative BFS traversal** from reservoirs — correct for looped networks
- **Precomputed adjacency** per hydraulic step — eliminates repeated ctypes calls
- **HydraulicCache** — pre-computes all hydraulic time steps in one pass for maximum speed
- **PipeSegmentation** — fixed-length segments for spatial analysis and time-series recording
- **Garbage collection** — removes unused PHREEQC solutions in long simulations
- **O(n log n) sweep** in junction mixing — reduces complexity compared to the naïve O(n²) approach

---

## Installation

```bash
pip install epynet phreeqpython pandas numpy
```

> **Requirements:** Python ≥ 3.9, EPyNet (2025 release), PhreeqPython, pandas, numpy

---

## Quick Start

### Basic simulation loop

```python
import epynet
import phreeqpython
from victoria import Victoria

network = epynet.Network('network.inp')
pp = phreeqpython.PhreeqPython()

sol_high = pp.add_solution({'units': 'mmol/kgw', 'Ca': 10})
sol_low  = pp.add_solution({})
input_sol = {
    'R1':  sol_high,  # reservoir R1 → calcium-rich water
    '_bg': sol_low,   # background solution
}

network.solve(simtime=0)
vic = Victoria(network, pp)
vic.fill_network(input_sol, from_reservoir=True)

hydstep = 3600  # 1 hour [s]
for step in range(24):
    network.solve(simtime=step * hydstep)
    vic.check_flow_direction()
    vic.step(timestep=hydstep, input_sol=input_sol)

node = network.nodes['J5']
print(vic.get_conc_node(node, 'Ca', 'mg/L'))
print(vic.get_properties_node(node))  # [pH, SC, temperature]
```

### With segmentation and time-series

```python
seg = vic.segmentation(seg_length_m=10.0)
seg.calibrate(sol_high, sc_high=600.0, sc_low=0.0, species='Ca', units='mg')

for step in range(24):
    network.solve(simtime=step * hydstep)
    vic.check_flow_direction()
    vic.step(timestep=hydstep, input_sol=input_sol)
    seg.record_step(network, species='Ca', units='mg',
                    time_s=(step + 1) * hydstep, step=step + 1)

df = seg.to_dataframe()
# Columns: pipe, step, time_s, time_min, seg_id, x_start_m, x_end_m,
#          x_mid_m, length_m, conc, sc, n_parcels
```

### With HydraulicCache (fastest variant)

```python
from victoria.solver import HydraulicCache

hcache = HydraulicCache(network)
hcache.precompute(hydstep_s=3600, n_steps=24)
vic.solver.set_hydraulic_cache(hcache)

for step in range(24):
    vic.check_flow_direction()  # loads step from cache; no network.solve() needed
    vic.step(timestep=hydstep, input_sol=input_sol)
```

---

## Architecture

### Transport model

Victoria uses a **Lagrangian parcel model** (FIFO). Per time step:

```
1. push_in()      — new water from upstream node enters the pipe
2. push_pull()    — shift all parcels; x > 1 → output_state (leaves pipe)
3. mix()          — junction receives output_state from upstream pipes
                    and computes chemical mixture (PHREEQC or analytical)
4. parcels_out()  — distribute mixture over downstream pipes by flow ratio
```

### Parcel merging

After each `push_pull()`, adjacent parcels are merged when all fractions in `q` are within `eps_merge` (default 0.5%) of each other. A hard cap `max_parcels` (default 50) guarantees bounded computation time. The same logic applies to junction output in `Junction.mix()`.

### Module overview

| Module | Class(es) | Responsibility |
|---|---|---|
| `victoria.py` | `Victoria` | Main API; orchestrates solver, quality and segmentation |
| `solver.py` | `Solver`, `HydraulicCache` | BFS traversal, adjacency, hydraulic caching |
| `models.py` | `Models` | Creates FIFO/MIX models for each network element |
| `fifo.py` | `FIFO`, `Pipe`, `Pump`, `Valve` | Pipe model with parcel push/pull and merging |
| `mix.py` | `MIX`, `Junction`, `Reservoir`, `Tank_*` | Junction mixing (PHREEQC or analytical) |
| `quality.py` | `Quality` | Querying concentrations and water properties |
| `segmentation.py` | `PipeSegmentation` | Fixed-length segments, time-series recording |

---

## API Reference

### Victoria (class)

```python
Victoria(network: epynet.Network, pp: PhreeqPython)
```

#### Simulation methods

| Method | Description |
|---|---|
| `step(timestep, input_sol)` | Execute one water quality time step. Call after `network.solve()`. |
| `fill_network(input_sol, from_reservoir=True)` | Initialise the network. Call once before the simulation loop. |
| `check_flow_direction()` | Detect flow reversals and build adjacency caches. Call after each hydraulic step. |
| `garbage_collect(input_sol=None, preserve=None)` | Remove unused PHREEQC solutions. Call periodically in long simulations. |

#### Concentration query methods

| Method | Return type | Description |
|---|---|---|
| `get_conc_node(node, element, units='mmol')` | `float` | Instantaneous concentration at node exit |
| `get_conc_node_avg(node, element, units='mmol')` | `float` | Time-averaged concentration at node exit |
| `get_mixture_node(node)` | `dict[int, float]` | Instantaneous solution mixture `{sol_nr: fraction}` |
| `get_mixture_node_avg(node)` | `dict[int, float]` | Time-averaged solution mixture |
| `get_conc_pipe(link, element, units='mmol')` | `list[dict]` | Concentration profile along a pipe |
| `get_conc_pipe_avg(link, element, units='mmol')` | `float` | Volume-averaged concentration in a pipe |
| `get_parcels(link)` | `list[dict]` | All parcels currently in a pipe |
| `get_properties_node(node)` | `list[float]` | `[pH, SC, temperature]` — instantaneous |
| `get_properties_node_avg(node)` | `list[float]` | `[pH, SC, temperature]` — time-averaged |

#### Segmentation methods

| Method | Description |
|---|---|
| `segmentation(seg_length_m=6.0)` | Create a `PipeSegmentation` object for time-series recording. |
| `segment_pipe(pipe, species, units='mg', seg_length_m=6.0)` | Concentration per segment for one pipe (snapshot). |
| `segment_network(network, species, units='mg', seg_length_m=6.0)` | Concentration per segment for all pipes (snapshot as DataFrame). |

---

### Models

```python
Models(network: epynet.Network)
```

Created internally by `Victoria`. Contains all FIFO/MIX models indexed by uid.

| Attribute | Type | Contents |
|---|---|---|
| `nodes` | `dict[str, MIX]` | All node models (junctions + reservoirs + tanks) |
| `junctions` | `dict[str, Junction]` | Junction models |
| `reservoirs` | `dict[str, Reservoir]` | Reservoir models |
| `tanks` | `dict[str, Tank_*]` | Tank models (default `Tank_CSTR`) |
| `links` | `dict[str, FIFO]` | All pipe models (pipes + pumps + valves) |
| `pipes` | `dict[str, Pipe]` | Pipe models |
| `pumps` | `dict[str, Pump]` | Pump models |
| `valves` | `dict[str, Valve]` | Valve models |
| `get_node_model(uid)` | `MIX` | Returns node model; raises `KeyError` if not found |
| `get_link_model(uid)` | `FIFO` | Returns pipe model; raises `KeyError` if not found |

---

### Solver & HydraulicCache

```python
Solver(models: Models, network: epynet.Network)
```

| Method | Description |
|---|---|
| `run_trace(start_node, timestep, input_sol)` | BFS from `start_node`; executes mix + push\_pull on all reachable elements |
| `fill_network(start_node, input_sol)` | Initialisation traversal; fills pipes with starting solution |
| `check_connections()` | Detect flow reversals and mirror parcels in reversed pipes |
| `reset_ready_state()` | Reset `ready` flags after each time step |
| `set_hydraulic_cache(hcache)` | Attach a `HydraulicCache` for pre-computed hydraulics |

```python
from victoria.solver import HydraulicCache
HydraulicCache(network: epynet.Network)
```

| Method / Attribute | Description |
|---|---|
| `precompute(hydstep_s, n_steps)` | Pre-compute flow, velocity, demand and tank volume for all time steps |
| `apply(step)` | Load time step `step` into the EPyNet `_values` cache of all objects |
| `n_steps` | Number of cached time steps |
| `flows_at(step)` | `dict[uid, float]` — flows at time step `step` |
| `velocities_at(step)` | `dict[uid, float]` — velocities at time step `step` |

---

### Quality

```python
Quality(pp: PhreeqPython, models: Models)
```

Computes concentrations and water properties by mixing PHREEQC solutions. Normally accessed via `Victoria` methods; also directly available on `victoria.quality`.

---

### FIFO & Pipe

```python
Pipe(volume: float)   # pipe volume [m³] — computed as π/4 · L · D²
Pump()                # zero-length FIFO (ZeroLengthFIFO)
Valve()               # zero-length FIFO (ZeroLengthFIFO)
```

**Parcel format (in `state` and `output_state`):**

```python
{
    'x0':     float,           # start position, normalised to pipe length [0.0–1.0]
    'x1':     float,           # end position
    'q':      dict[int,float], # {solution_number: fraction, ...}
    'volume': float,           # [m³] — only present in output_state
}
```

**Configurable class attributes:**

| Attribute | Default | Description |
|---|---|---|
| `Pipe.eps_merge` | `0.005` | Max concentration difference for parcel merging (0.5%) |
| `Pipe.max_parcels` | `50` | Hard cap on parcel list length |

**Methods:**

| Method | Description |
|---|---|
| `push_pull(flow, volumes)` | Shift parcels; send overflow to `output_state` |
| `push_in(volumes)` | Insert new parcels at the start (O(1) via cumulative offset) |
| `fill(input_sol)` | Initialise pipe with a single homogeneous solution |
| `connections(downstream, upstream)` | Store upstream/downstream node references |
| `reverse_parcels(downstream, upstream)` | Mirror parcel positions on flow reversal |

---

### MIX & Node Models

All models inherit from `MIX` and implement `mix(inflow, node, timestep, input_sol)`.

| Class | Mixing model | Application |
|---|---|---|
| `Junction` | O(n log n) boundary-point sweep + PHREEQC | Standard demand node |
| `Reservoir` | Fixed input solution | Water source / inlet |
| `Tank_CSTR` | Fully mixed (implicit Euler) | Tank with continuous throughflow |
| `Tank_FIFO` | First-In First-Out | Stratified tank |
| `Tank_LIFO` | Last-In First-Out | Tank with LIFO outflow |

**Attributes available after `mix()`:**

| Attribute | Type | Description |
|---|---|---|
| `mixed_parcels` | `list[dict]` | Output profile; input for downstream pipes |
| `outflow` | `list[list]` | Parcels per downstream pipe (filled by `parcels_out()`) |

**Class-wide configuration:**

```python
from victoria.mix import MIX
MIX.eps_merge   = 0.001  # tighter: 0.1% difference
MIX.max_parcels = 100
```

---

### PipeSegmentation

```python
PipeSegmentation(model: Victoria, seg_length_m: float = 6.0)
# Or via:
seg = vic.segmentation(seg_length_m=10.0)
```

#### Calibration (recommended — bypasses PHREEQC entirely)

```python
seg.calibrate(
    sol_high,          # PhreeqPython solution (high-concentration end-member)
    sc_high=600.0,     # specific conductance of sol_high [µS/cm]
    sc_low=0.0,        # specific conductance of background solution
    species='Ca',
    units='mg',
)
```

After calibration, concentration and SC are computed linearly from parcel fractions — no PHREEQC calls needed.

#### Methods

| Method | Description |
|---|---|
| `record_step(network, species, units, time_s, step)` | Record segment concentrations for the current time step |
| `to_dataframe()` | Return all recorded time steps as a pandas DataFrame |
| `segment_pipe(pipe, species, units)` | Concentration per segment for one pipe (snapshot) |
| `segment_network(network, species, units)` | Concentration per segment for all pipes (snapshot) |
| `pipe_metadata(network)` | DataFrame with pipe lengths, segment counts and last segment length |
| `reset()` | Clear all recorded time-step data |

#### DataFrame columns (`to_dataframe()`)

```
pipe        — pipe uid
step        — time step number
time_s      — simulation time [s]
time_min    — simulation time [min]
seg_id      — segment number within pipe (1-based)
x_start_m   — start position [m]
x_end_m     — end position [m]
x_mid_m     — midpoint position [m]
length_m    — segment length [m]
conc        — concentration [specified unit]
sc          — specific conductance [µS/cm]  (only after calibration)
n_parcels   — number of parcels contributing to this segment
```

#### Determining the recommended segment length

```python
from victoria.segmentation import suggest_seg_length, print_seg_advice

advice = suggest_seg_length(network, hydstep_s=3600, min_segs_per_pipe=5)
print_seg_advice(advice)
```

---

## Advanced Usage

### Changing the tank model

```python
from victoria.mix import Tank_FIFO

tank_vol = network.tanks['T1'].initvolume
vic.models.tanks['T1'] = Tank_FIFO(tank_vol)
vic.models.nodes['T1'] = vic.models.tanks['T1']
```

### Adjusting parcel merging thresholds

```python
from victoria.fifo import Pipe
from victoria.mix import MIX

Pipe.eps_merge   = 0.001   # tighter: 0.1% difference
Pipe.max_parcels = 100
MIX.eps_merge    = 0.001
MIX.max_parcels  = 100
```

### Garbage collection in long simulations

```python
for step in range(n_steps):
    network.solve(simtime=step * hydstep)
    vic.check_flow_direction()
    vic.step(timestep=hydstep, input_sol=input_sol)
    if step % 10 == 0:
        vic.garbage_collect(input_sol=input_sol)
```

### Multiple reservoirs with different water types

```python
sol_hard = pp.add_solution({'units': 'mmol/kgw', 'Ca': 10, 'Mg': 2})
sol_soft  = pp.add_solution({'units': 'mmol/kgw', 'Ca': 1})
input_sol = {
    'R_HARD': sol_hard,
    'R_SOFT': sol_soft,
    '_bg':    pp.add_solution({}),
}
```

### Profiling the simulation

```bash
python profile_victoria.py network.inp
# Writes sorted cProfile output to profile_output.txt
```

---

## Parcel Merging

Victoria uses two mechanisms to keep the parcel list manageable:

### `_merge_adjacent(state, eps_merge)`

Iterates through the parcel list and merges adjacent parcels when all fractions in `q` are within `eps_merge` of each other. Weight is `volume` (if present) or width (`x1 - x0`). Concentrations are volume-weighted averages.

### `_enforce_max_parcels(state, max_parcels)`

When the list exceeds `max_parcels`, repeatedly merges the two adjacent parcels with the smallest concentration difference until the limit is reached. Guarantees a hard upper bound on computation time at a small accuracy cost in regions with sharp quality gradients.

Both functions are applied in `Pipe.push_pull()` and in `Junction.mix()`.

---

## FAQ

**Q: In what order should I call the methods?**

```
1. network.solve(simtime=0)
2. vic.fill_network(input_sol)
3. Per time step:
   a. network.solve(simtime=t)      ← or via HydraulicCache
   b. vic.check_flow_direction()
   c. vic.step(timestep, input_sol)
   d. [optional] vic.garbage_collect(input_sol)
```

**Q: What is the difference between instantaneous and time-averaged?**

Instantaneous (`get_conc_node`) returns the concentration of the first parcel reaching the node — representative of the leading water quality. Time-averaged (`get_conc_node_avg`) is a volume-weighted average over all `mixed_parcels` — representative of the average delivered quality.

**Q: When should I use `garbage_collect()`?**

In simulations longer than ~1,000 time steps the number of PHREEQC solutions grows rapidly. Call `garbage_collect()` every 10–50 steps.

**Q: Can I use a different tank model?**

Yes — see [Changing the tank model](#changing-the-tank-model). `Tank_FIFO` suits stratified tanks; `Tank_LIFO` suits tanks with last-in-first-out outflow.

---

## Glossary

| Term | Description |
|---|---|
| **parcel** | Discrete water plug with fixed composition `{sol_nr: fraction}` |
| **FIFO** | First-In First-Out: water pumped in first leaves the pipe first |
| **CSTR** | Continuously Stirred Tank Reactor: perfectly mixed tank |
| **BFS** | Breadth-First Search: traversal strategy from reservoirs through the network |
| **adjacency** | Pre-computed upstream/downstream connections per node |
| **eps\_merge** | Max concentration difference within which adjacent parcels are merged |
| **max\_parcels** | Hard cap on parcel list length per pipe or node |
| **mixed\_parcels** | Output profile of a node after mixing; input for downstream pipes |
| **output\_state** | Buffer of parcels leaving a pipe in the current time step |
| **SC** | Specific conductance [µS/cm] — proxy for ionic strength |
| **flow reversal** | Reversal of flow direction in a pipe between two hydraulic time steps |

---

## Changelog

### 1.1.0
- Parcel merging on pipes (`_merge_adjacent`, `_enforce_max_parcels`)
- Parcel merging on junction output in `Junction.mix()`
- `HydraulicCache` for pre-computed hydraulics
- O(n log n) boundary-point sweep in `Junction.mix()`
- Linear segmentation via `PipeSegmentation.calibrate()`
- Precomputed adjacency per hydraulic step via `_build_adjacency()`

### 1.0.0
- Initial release — FIFO pipe model, PHREEQC mixing, BFS traversal
