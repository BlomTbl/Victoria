# Victoria — User Guide

Victoria is a Python package for simulating water quality in hydraulic distribution
networks. It couples **EPyNet** (hydraulic simulation) with **PHREEQC** (water
chemistry) using a FIFO (First In First Out) parcel model to track how water moves
and mixes through pipes and nodes.

---

## Table of Contents

1. [Concepts](#concepts)
2. [Installation](#installation)
3. [Setting up a simulation](#setting-up-a-simulation)
4. [The simulation loop](#the-simulation-loop)
5. [Querying results](#querying-results)
6. [Pipe segmentation](#pipe-segmentation)
7. [Memory management](#memory-management)
8. [Flow reversals](#flow-reversals)
9. [Tank models](#tank-models)
10. [Logging](#logging)
11. [Complete example](#complete-example)
12. [Common pitfalls](#common-pitfalls)

---

## Concepts

### FIFO parcel tracking

Water in a pipe is represented as a series of **parcels** — contiguous segments of
water, each carrying a normalised position `[x0, x1]` within the pipe (0 = inlet,
1 = outlet) and a mixture of PHREEQC solution numbers.

Each simulation step, parcels are **pushed** in from the upstream node and **pulled**
out at the downstream end proportionally to the hydraulic flow computed by EPyNet.
This preserves the first-in-first-out ordering of water and lets you track how a
quality signal (e.g. a tracer or chemical change) propagates through the network.

### PHREEQC solutions

Every distinct parcel of water is described by one or more **PHREEQC solution
objects** and their fractional contributions. When water from multiple sources mixes
at a junction, Victoria combines the solutions proportionally and queries the
resulting chemistry (concentration, pH, conductivity, temperature) via PhreeqPython.

### `input_sol` dictionary

The `input_sol` dictionary maps identifiers to PHREEQC solution objects:

| Key | Meaning |
|---|---|
| `0` | Background / pipe-fill solution. Used to initialise pipes that are not reachable from a reservoir, and as a fallback. **Required.** |
| `'R1'`, `'R2'`, … | Source water for each reservoir, keyed by the reservoir's `uid` string. |

---

## Installation

```bash
# From GitHub (latest develop branch)
pip install git+https://github.com/BlomTbl/victoria.git@develop

# Editable install from a local clone
git clone https://github.com/BlomTbl/victoria.git
cd victoria
pip install -e .
```

**Requirements:** Python ≥ 3.7, `epynet ≥ 0.2.0`, `phreeqpython ≥ 1.2.0`.

---

## Setting up a simulation

### 1. Load and solve the hydraulic network

Victoria needs a hydraulically solved EPyNet network before it can initialise:

```python
import epynet

network = epynet.Network('my_network.inp')
network.solve()   # run a steady-state or initial hydraulic solve
```

### 2. Initialise PHREEQC

```python
from phreeqpython import PhreeqPython

pp = PhreeqPython()
```

### 3. Define input solutions

```python
solutions = {
    0:    pp.add_solution({'units': 'mg/L', 'Ca': 0,   'Mg': 0,   'Cl': 0}),   # background
    'R1': pp.add_solution({'units': 'mg/L', 'Ca': 52,  'Mg': 8,   'Cl': 95}),  # source 1
    'R2': pp.add_solution({'units': 'mg/L', 'Ca': 28,  'Mg': 4,   'Cl': 55}),  # source 2
}
```

> **Tip:** The `units` key in `add_solution` sets the unit for the concentrations
> you pass in. It is **not** the same as the `units` argument to
> `get_conc_node()` / `get_conc_pipe()`, which controls what unit the query
> returns.

### 4. Create the Victoria simulator

```python
from victoria import Victoria

vic = Victoria(network, pp)
```

### 5. Fill the network with initial water quality

```python
vic.fill_network(solutions, from_reservoir=True)
```

`from_reservoir=True` (default) pushes the source solution from each reservoir
outward through all connected pipes. Pipes not reachable from any reservoir are
filled with `solutions[0]`.

Set `from_reservoir=False` to fill every pipe uniformly with `solutions[0]`
(useful when you want a blank-slate initial condition).

---

## The simulation loop

After filling, advance the simulation one timestep at a time:

```python
import epynet

TIMESTEP_S = 3600   # 1 hour

for hour in range(24):
    # 1. Update hydraulics (demand patterns, pump schedules, etc.)
    network.solve()

    # 2. Handle flow reversals (see section below)
    vic.check_flow_direction()

    # 3. Advance water quality by one timestep
    vic.step(timestep=TIMESTEP_S, input_sol=solutions)

    # 4. Query and use results …
```

> **Order matters:** always call `network.solve()` → `check_flow_direction()` →
> `step()`. Never call `step()` before the hydraulic solve.

---

## Querying results

All query methods are available directly on the `Victoria` instance. They
reflect the state **after** the most recent `step()` call.

### Concentration at a node

```python
# Instantaneous concentration at the node exit (first parcel leaving)
ca_mg = vic.get_conc_node(node, 'Ca', 'mg')

# Time-averaged over all parcels that passed through during the last step
ca_avg = vic.get_conc_node_avg(node, 'Ca', 'mg')
```

### Concentration profile along a pipe

```python
# List of dicts: {'x0': float, 'x1': float, 'q': float}
# x0/x1 are normalised positions (0=inlet, 1=outlet)
# q is the concentration in the requested units
profile = vic.get_conc_pipe(link, 'Ca', 'mg')

# Volume-averaged concentration over the entire pipe
avg = vic.get_conc_pipe_avg(link, 'Ca', 'mg')
```

### Water properties at a node

```python
# Returns [pH, specific_conductance_µS_cm, temperature_°C]
ph, sc, temp = vic.get_properties_node(node)
ph_avg, sc_avg, temp_avg = vic.get_properties_node_avg(node)
```

### Solution mixture fractions

Useful for tracing which source water is present at a node:

```python
# {solution_number: fraction, …}  — fractions sum to 1.0
mix = vic.get_mixture_node(node)
mix_avg = vic.get_mixture_node_avg(node)
```

### Valid `units` strings

The `units` argument is passed directly to `PhreeqPython.total()`. Common values:

| `units` | Meaning |
|---|---|
| `'mg'` | milligrams per litre |
| `'mmol'` | millimoles per litre (default for most methods) |
| `'mol'` | moles per litre |
| `'ppm'` | parts per million (≈ mg/L for dilute solutions) |

---

## Pipe segmentation

`PipeSegmentation` converts the normalised FIFO parcel positions back to
real metres and bins them into fixed-length physical segments. This is useful
for understanding where in a pipe a quality change is located, or for comparing
simulation output with field measurements at known distances.

### One-off snapshot

```python
# All pipes, all segments, current simulation state
df = vic.segment_network(network, species='Ca', units='mg', seg_length_m=6.0)
# Returns a pandas DataFrame with columns:
#   pipe, seg_id, x_start_m, x_end_m, x_mid_m, length_m, conc, n_parcels

# Single pipe
segs = vic.segment_pipe(pipe, species='Ca', units='mg', seg_length_m=6.0)
# Returns a list of dicts with the same keys
```

### Time-series recording

Create a `PipeSegmentation` recorder with `vic.segmentation()` and call
`record_step()` inside your simulation loop:

```python
seg = vic.segmentation(seg_length_m=6.0)

for step in range(N_STEPS):
    network.solve()
    vic.check_flow_direction()
    vic.step(timestep=300, input_sol=solutions)

    seg.record_step(
        network,
        species='Ca',
        units='mg',
        time_s=(step + 1) * 300,   # optional — stored as metadata
        step=step + 1,              # optional — stored as metadata
    )

# Retrieve everything as a tidy DataFrame
df_ts = seg.to_dataframe()
# Columns: pipe, seg_id, x_start_m, x_end_m, x_mid_m, length_m,
#          conc, n_parcels, step, time_s, time_min
```

### Pipe metadata

```python
meta = seg.pipe_metadata(network)
# Columns: pipe, pipe_length_m, seg_length_m, n_segs, last_seg_m
```

The last segment of a pipe may be shorter than `seg_length_m` when the pipe
length is not an exact multiple of the segment length.

---

## Memory management

Every time parcels mix at a junction, Victoria may create new PHREEQC solution
objects. Over long simulations this can consume significant RAM. Call
`garbage_collect()` periodically to remove solutions that are no longer
referenced by any parcel:

```python
for hour in range(168):    # one week at hourly timesteps
    network.solve()
    vic.check_flow_direction()
    vic.step(timestep=3600, input_sol=solutions)

    if hour % 12 == 0:
        vic.garbage_collect(solutions)   # pass input_sol to preserve source solutions
```

> **Always pass `input_sol`** to `garbage_collect()`. Without it the source
> solutions themselves may be deleted, corrupting the next `step()`.

---

## Flow reversals

By default Victoria assumes flow directions are stable. If your scenario includes
pumps switching on/off, tank filling/draining, or demand patterns that cause
flow to reverse in some pipes, call `check_flow_direction()` **before** each
`step()`:

```python
network.solve()
vic.check_flow_direction()   # detects reversals and flips parcel positions
vic.step(timestep=TIMESTEP_S, input_sol=solutions)
```

Calling `check_flow_direction()` when no reversals occur is harmless and has
negligible cost, so it is good practice to include it in all simulation loops.

---

## Tank models

Victoria supports three mixing models for tanks. The default is CSTR, but you
can change it by replacing the model object directly:

```python
from victoria.mix import Tank_FIFO, Tank_LIFO

# Switch tank 'T1' to FIFO model
tank = network.tanks['T1']
vic.models.tanks['T1'] = Tank_FIFO(volume=tank.initvolume)
vic.models.nodes['T1'] = vic.models.tanks['T1']
```

| Model | Class | Behaviour |
|---|---|---|
| CSTR | `Tank_CSTR` | Continuous stirred tank — instantaneous, complete mixing (default) |
| FIFO | `Tank_FIFO` | Plug flow — first water in is first out, stratified |
| LIFO | `Tank_LIFO` | Last in first out — newest water exits first (gravity stratification) |

---

## Logging

Victoria uses Python's standard `logging` module. Attach a handler to see
diagnostic output:

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
```

Set the level to `DEBUG` for detailed per-step tracing. PHREEQC oxygen
convergence messages are logged at `DEBUG` level by default (they are
non-fatal and very frequent in networks with near-zero dissolved oxygen).

---

## Complete example

```python
import epynet
from phreeqpython import PhreeqPython
from victoria import Victoria

# ── Network setup ─────────────────────────────────────────────────────────────
network = epynet.Network('trapo.inp')
network.solve()

pp = PhreeqPython()

solutions = {
    0:    pp.add_solution({'units': 'mg/L', 'Ca': 0,  'Cl': 0}),
    'R1': pp.add_solution({'units': 'mg/L', 'Ca': 52, 'Cl': 95}),
}

vic = Victoria(network, pp)
vic.fill_network(solutions, from_reservoir=True)

# ── Segmentation recorder ─────────────────────────────────────────────────────
seg = vic.segmentation(seg_length_m=6.0)

# ── Simulation loop ───────────────────────────────────────────────────────────
N_STEPS   = 48
TIMESTEP  = 1800    # 30 minutes

for step in range(N_STEPS):
    network.solve()
    vic.check_flow_direction()
    vic.step(timestep=TIMESTEP, input_sol=solutions)

    seg.record_step(
        network, species='Ca', units='mg',
        time_s=(step + 1) * TIMESTEP, step=step + 1,
    )

    # Garbage collect every 12 steps
    if (step + 1) % 12 == 0:
        vic.garbage_collect(solutions)

# ── Results ───────────────────────────────────────────────────────────────────
for node in network.junctions:
    ca = vic.get_conc_node(node, 'Ca', 'mg')
    print(f"Junction {node.uid}: Ca = {ca:.2f} mg/L")

df_seg = seg.to_dataframe()
print(df_seg.head())
```

---

## Common pitfalls

**`step()` called before `network.solve()`**
Victoria reads flow values from EPyNet. If the hydraulics are stale the parcel
movement will be wrong. Always solve hydraulics first.

**Missing key `0` in `input_sol`**
`fill_network()` and `garbage_collect()` both use `input_sol[0]` as the
fallback background solution. Omitting it raises a `KeyError`.

**`units='mg/L'` passed to query methods**
PhreeqPython does not recognise `'mg/L'` as a unit string. Use `'mg'`
(milligrams per litre) instead.

**Not calling `check_flow_direction()` with time-varying demands**
If flow reverses in a pipe and you do not call `check_flow_direction()`, the
parcel positions will be wrong and concentrations will drift silently.

**RAM growing unboundedly on long simulations**
Call `garbage_collect(solutions)` every 10–20 steps to free unused PHREEQC
solutions, always passing `input_sol` so source solutions are preserved.
