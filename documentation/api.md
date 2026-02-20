# Victoria — API Reference

This document covers the full public API of the `victoria` package (v1.1.0).
Internal helpers (prefixed `_`) are not documented here.

---

## Table of Contents

- [Package imports](#package-imports)
- [Victoria](#victoria)
  - [Constructor](#victorianetwork-pp)
  - [fill_network](#fill_networkinput_sol-from_reservoirtrue)
  - [step](#steptimestep-input_sol)
  - [check_flow_direction](#check_flow_direction)
  - [garbage_collect](#garbage_collectinput_solnone)
  - [get_conc_node](#get_conc_nodenode-element-unitsmmol)
  - [get_conc_node_avg](#get_conc_node_avgnode-element-unitsmmol)
  - [get_mixture_node](#get_mixture_nodenode)
  - [get_mixture_node_avg](#get_mixture_node_avgnode)
  - [get_conc_pipe](#get_conc_pipelink-element-unitsmmol)
  - [get_conc_pipe_avg](#get_conc_pipe_avglink-element-unitsmmol)
  - [get_properties_node](#get_properties_nodenode)
  - [get_properties_node_avg](#get_properties_node_avgnode)
  - [get_parcels](#get_parcelslink)
  - [segmentation](#segmentationseg_length_m60)
  - [segment_pipe](#segment_pipepipe-species-unitsmg-seg_length_m60)
  - [segment_network](#segment_networknetwork-species-unitsmg-seg_length_m60)
- [PipeSegmentation](#pipesegmentation)
  - [Constructor](#pipesegmentationmodel-seg_length_m60)
  - [segment_pipe](#segment_pipepipe-species-unitsmg-1)
  - [segment_network](#segment_networknetwork-species-unitsmg-1)
  - [record_step](#record_stepnetwork-species-unitsmg-time_snone-stepnone)
  - [to_dataframe](#to_dataframe)
  - [reset](#reset)
  - [pipe_metadata](#pipe_metadatanetwork)
- [FIFO classes](#fifo-classes)
  - [FIFO](#fifo-1)
  - [Pipe](#pipe)
  - [Pump / Valve](#pump--valve)
- [MIX classes](#mix-classes)
  - [Junction](#junction)
  - [Reservoir](#reservoir)
  - [Tank_CSTR](#tank_cstr)
  - [Tank_FIFO](#tank_fifo)
  - [Tank_LIFO](#tank_lifo)
- [Models](#models)
- [Solver](#solver)
- [Quality](#quality)
- [Units reference](#units-reference)

---

## Package imports

```python
from victoria import (
    Victoria,
    PipeSegmentation,
    Models, Solver, Quality,
    FIFO, Pipe, Pump, Valve,
    MIX, Junction, Reservoir, Tank_CSTR, Tank_FIFO, Tank_LIFO,
)

import victoria
print(victoria.__version__)   # '1.1.0'
```

---

## Victoria

Main simulator class. Combines EPyNet hydraulics with PHREEQC chemistry.

---

### `Victoria(network, pp)`

```python
vic = Victoria(network, pp)
```

| Parameter | Type | Description |
|---|---|---|
| `network` | `epynet.Network` | A hydraulically solved EPyNet network. |
| `pp` | `phreeqpython.PhreeqPython` | An initialised PhreeqPython instance. |

Internally creates a `Models`, `Solver`, and `Quality` instance.

---

### `fill_network(input_sol, from_reservoir=True)`

Initialise every pipe with a starting water quality. Call once before the simulation loop.

```python
vic.fill_network(input_sol, from_reservoir=True)
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `input_sol` | `dict` | — | Mapping of identifiers to PHREEQC solution objects. Key `0` (int) is the background/fallback solution; reservoir UIDs (strings) map to source solutions. |
| `from_reservoir` | `bool` | `True` | If `True`, push source water from each reservoir outward. If `False`, fill all pipes uniformly with `input_sol[0]`. |

**Raises:** `KeyError` if `from_reservoir=True` and a reservoir has no matching key in `input_sol`, or if key `0` is absent.

---

### `step(timestep, input_sol)`

Advance the water quality simulation by one timestep. Must be called **after** `network.solve()`.

```python
vic.step(timestep=3600, input_sol=solutions)
```

| Parameter | Type | Description |
|---|---|---|
| `timestep` | `float` | Duration of the step in **seconds**. Must be > 0. |
| `input_sol` | `dict` | Same dictionary passed to `fill_network`. Used to look up source solutions for each reservoir. |

**Raises:** `ValueError` if `timestep ≤ 0`.

---

### `check_flow_direction()`

Detect pipes where the flow direction has reversed since the last call and flip the parcel positions accordingly.

```python
vic.check_flow_direction()
```

Call this **before** `step()` whenever demand patterns, pump schedules, or tank
levels may cause flow reversals. Safe to call even when no reversals have
occurred.

Returns `None`.

---

### `garbage_collect(input_sol=None)`

Remove PHREEQC solution objects that are no longer referenced by any parcel from memory.

```python
vic.garbage_collect(solutions)
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `input_sol` | `dict` or `None` | `None` | Pass the same `input_sol` used in `step()` to protect source solutions from deletion. If `None`, source solutions may be removed. |

Call every 10–20 steps on long simulations to prevent unbounded RAM growth.

Returns `None`.

---

### `get_conc_node(node, element, units='mmol')`

Instantaneous concentration at the node exit — the concentration of the **first parcel** leaving the node during the last `step()`.

```python
ca_mg = vic.get_conc_node(node, 'Ca', 'mg')
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `node` | epynet node | — | Junction, reservoir, or tank object. |
| `element` | `str` | — | PHREEQC element or species name, e.g. `'Ca'`, `'Cl'`, `'Na'`. |
| `units` | `str` | `'mmol'` | Concentration units. See [Units reference](#units-reference). |

**Returns:** `float` — concentration in the requested units per litre. Returns `0.0` if the node has no parcel data.

---

### `get_conc_node_avg(node, element, units='mmol')`

Time-averaged concentration at the node exit — weighted average over all parcels that flowed through the node during the last `step()`.

```python
ca_avg = vic.get_conc_node_avg(node, 'Ca', 'mg')
```

Parameters and return value are identical to [`get_conc_node`](#get_conc_nodenode-element-unitsmmol).

---

### `get_mixture_node(node)`

Instantaneous solution mixture fractions at the node exit.

```python
mix = vic.get_mixture_node(node)
# e.g. {1: 0.65, 2: 0.35}  — solution numbers map to volume fractions
```

| Parameter | Type | Description |
|---|---|---|
| `node` | epynet node | Node object. |

**Returns:** `dict[int, float]` — PHREEQC solution number → volume fraction. Fractions sum to 1.0. Returns `{}` if no data.

---

### `get_mixture_node_avg(node)`

Time-averaged solution mixture fractions at the node exit.

```python
mix_avg = vic.get_mixture_node_avg(node)
```

Parameters and return value are identical to [`get_mixture_node`](#get_mixture_nodenode).

---

### `get_conc_pipe(link, element, units='mmol')`

Concentration profile along a pipe — one entry per FIFO parcel currently inside the pipe.

```python
profile = vic.get_conc_pipe(link, 'Ca', 'mg')
# [{'x0': 0.0, 'x1': 0.4, 'q': 3.2},
#  {'x0': 0.4, 'x1': 1.0, 'q': 1.7}]
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `link` | epynet pipe | — | Pipe object. |
| `element` | `str` | — | PHREEQC element or species name. |
| `units` | `str` | `'mmol'` | Concentration units. |

**Returns:** `list[dict]` — each dict has keys:
- `x0` (`float`): normalised start position in pipe (0 = inlet).
- `x1` (`float`): normalised end position in pipe (1 = outlet).
- `q` (`float`): concentration in requested units per litre.

Returns `[]` if no data.

---

### `get_conc_pipe_avg(link, element, units='mmol')`

Volume-weighted average concentration across the entire pipe.

```python
avg = vic.get_conc_pipe_avg(link, 'Ca', 'mg')
```

Parameters and return value (`float`) are analogous to `get_conc_pipe`.

---

### `get_properties_node(node)`

Instantaneous water properties at the node exit.

```python
ph, sc, temp = vic.get_properties_node(node)
```

| Parameter | Type | Description |
|---|---|---|
| `node` | epynet node | Node object. |

**Returns:** `list[float]` — `[pH, specific_conductance_µS/cm, temperature_°C]`. Returns `[0.0, 0.0, 0.0]` if no data.

---

### `get_properties_node_avg(node)`

Time-averaged water properties at the node exit.

```python
ph_avg, sc_avg, temp_avg = vic.get_properties_node_avg(node)
```

Parameters and return value are identical to [`get_properties_node`](#get_properties_nodenode).

---

### `get_parcels(link)`

Raw list of FIFO parcel dictionaries currently inside a pipe. Useful for debugging.

```python
parcels = vic.get_parcels(link)
# [{'x0': 0.0, 'x1': 0.6, 'q': {1: 0.8, 2: 0.2}}, …]
```

| Parameter | Type | Description |
|---|---|---|
| `link` | epynet pipe | Pipe object. |

**Returns:** `list[dict]` — raw parcel state. Each dict has `x0`, `x1` (normalised positions) and `q` (dict of PHREEQC solution number → fraction).

---

### `segmentation(seg_length_m=6.0)`

Create a `PipeSegmentation` recorder bound to this Victoria instance.

```python
seg = vic.segmentation(seg_length_m=6.0)
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `seg_length_m` | `float` | `6.0` | Physical length of each segment in metres. Must be > 0. |

**Returns:** `PipeSegmentation`

---

### `segment_pipe(pipe, species, units='mg', seg_length_m=6.0)`

One-off segment concentration profile for a single pipe at the current simulation state. Convenience wrapper around `PipeSegmentation.segment_pipe`.

```python
segs = vic.segment_pipe(pipe, 'Ca', units='mg', seg_length_m=10.0)
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `pipe` | epynet pipe | — | Must expose `.uid` and `.length`. |
| `species` | `str` | — | PHREEQC element or species name. |
| `units` | `str` | `'mg'` | Concentration units. |
| `seg_length_m` | `float` | `6.0` | Segment length in metres. |

**Returns:** `list[dict]` — see [`PipeSegmentation.segment_pipe`](#segment_pipepipe-species-unitsmg-1).

---

### `segment_network(network, species, units='mg', seg_length_m=6.0)`

One-off segment snapshot for all pipes in the network. Convenience wrapper around `PipeSegmentation.segment_network`.

```python
df = vic.segment_network(network, 'Ca', units='mg', seg_length_m=6.0)
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `network` | epynet Network | — | Used to iterate `network.pipes`. |
| `species` | `str` | — | PHREEQC element or species name. |
| `units` | `str` | `'mg'` | Concentration units. |
| `seg_length_m` | `float` | `6.0` | Segment length in metres. |

**Returns:** `pandas.DataFrame` — see [`PipeSegmentation.segment_network`](#segment_networknetwork-species-unitsmg-1).

---

## PipeSegmentation

Divides pipes into fixed-length physical segments and computes the
length-weighted average concentration in each segment from the FIFO parcel state.

Import directly if needed:

```python
from victoria import PipeSegmentation
from victoria.segmentation import PipeSegmentation   # also works
```

---

### `PipeSegmentation(model, seg_length_m=6.0)`

```python
seg = PipeSegmentation(model, seg_length_m=6.0)
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `model` | `Victoria` | — | Initialised Victoria instance. |
| `seg_length_m` | `float` | `6.0` | Segment length in metres. Must be > 0. |

**Raises:** `ValueError` if `seg_length_m ≤ 0`.

**Attributes:**
- `seg_length_m` (`float`): segment length in metres.
- `model`: bound Victoria instance.

---

### `segment_pipe(pipe, species, units='mg')`

Compute the concentration for every fixed-length segment of one pipe.

```python
segs = seg.segment_pipe(pipe, 'Ca', 'mg')
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `pipe` | epynet pipe | — | Must expose `.uid` and `.length`. |
| `species` | `str` | — | PHREEQC element or species name. |
| `units` | `str` | `'mg'` | Concentration units. |

**Returns:** `list[dict]` — one entry per segment:

| Key | Type | Description |
|---|---|---|
| `seg_id` | `int` | 1-based segment index. |
| `x_start_m` | `float` | Segment start [m from inlet]. |
| `x_end_m` | `float` | Segment end [m from inlet]. |
| `x_mid_m` | `float` | Segment midpoint [m from inlet]. |
| `length_m` | `float` | Actual segment length (last may be < `seg_length_m`). |
| `conc` | `float` | Length-weighted average concentration. |
| `n_parcels` | `int` | Number of FIFO parcels overlapping this segment. |

Returns `[]` when the pipe has zero length or no parcel data is available. (A `seg_length_m ≤ 0` value cannot occur at this point — the constructor raises `ValueError` first.)

---

### `segment_network(network, species, units='mg')`

Segment all pipes and return a tidy DataFrame.

```python
df = seg.segment_network(network, 'Ca', 'mg')
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `network` | epynet Network | — | Iterated via `network.pipes`. |
| `species` | `str` | — | PHREEQC element or species name. |
| `units` | `str` | `'mg'` | Concentration units. |

**Returns:** `pandas.DataFrame` with columns `pipe`, `seg_id`, `x_start_m`, `x_end_m`, `x_mid_m`, `length_m`, `conc`, `n_parcels`. Empty DataFrame if no parcel data exists.

---

### `record_step(network, species, units='mg', time_s=None, step=None)`

Record segment concentrations for the current simulation state. Call inside the simulation loop after `vic.step()`.

```python
seg.record_step(network, 'Ca', 'mg', time_s=3600, step=1)
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `network` | epynet Network | — | Iterated via `network.pipes`. |
| `species` | `str` | — | PHREEQC element or species name. |
| `units` | `str` | `'mg'` | Concentration units. |
| `time_s` | `float` or `None` | `None` | Elapsed simulation time in seconds. Stored as metadata if provided; also computes `time_min`. |
| `step` | `int` or `None` | `None` | Step counter. Stored as metadata if provided. |

Returns `None`. Data is appended to an internal buffer; retrieve with [`to_dataframe()`](#to_dataframe).

---

### `to_dataframe()`

Return all recorded time-series data as a tidy DataFrame.

```python
df = seg.to_dataframe()
```

**Returns:** `pandas.DataFrame`. Columns always include `pipe`, `seg_id`, `x_start_m`, `x_end_m`, `x_mid_m`, `length_m`, `conc`, `n_parcels`. Additional columns `step`, `time_s`, `time_min` are present if supplied to `record_step()`.

Returns an empty DataFrame if nothing has been recorded yet.

> **Note:** calling `to_dataframe()` does **not** clear the buffer. Call [`reset()`](#reset) to start fresh.

---

### `reset()`

Clear the internal recording buffer.

```python
seg.reset()
```

Returns `None`.

---

### `pipe_metadata(network)`

Return a summary of segment counts per pipe.

```python
meta = seg.pipe_metadata(network)
```

| Parameter | Type | Description |
|---|---|---|
| `network` | epynet Network | Iterated via `network.pipes`. |

**Returns:** `pandas.DataFrame` with columns:

| Column | Description |
|---|---|
| `pipe` | Pipe UID. |
| `pipe_length_m` | Total pipe length in metres. |
| `seg_length_m` | Configured segment length. |
| `n_segs` | Number of segments (`ceil(length / seg_length_m)`). |
| `last_seg_m` | Length of the final (possibly short) segment. |

Pipes with zero length are excluded.

---

## FIFO classes

Low-level classes for parcel tracking inside links. Normally you do not
instantiate these directly — `Models` creates them automatically.

---

### `FIFO`

Base class for all link objects.

```python
from victoria.fifo import FIFO
f = FIFO(volume=10.0)
```

**Attributes:**

| Attribute | Type | Description |
|---|---|---|
| `volume` | `float` | Physical volume in m³. |
| `state` | `list[dict]` | Current parcel list. Each dict: `{'x0', 'x1', 'q'}`. |
| `output_state` | `list[dict]` | Parcels exiting this link during last step. Each dict: `{'x0', 'x1', 'q', 'volume'}`. |
| `ready` | `bool` | `True` after `push_pull()` has been called for this step. |
| `upstream_node` | any | Upstream node object (set by solver). |
| `downstream_node` | any | Downstream node object (set by solver). |

**Methods:**

`connections(downstream, upstream)` — set node connections.

`reverse_parcels(downstream, upstream)` — mirror all parcel positions (called on flow reversal).

`push_in(volumes)` — push a list of `[volume, quality_dict]` pairs into the link from the inlet side.

---

### `Pipe`

FIFO subclass for pipes. Has physical length and volume; preserves parcel order.

```python
from victoria.fifo import Pipe
p = Pipe(volume=3.14)
p.fill({sol.number: 1.0})            # initialise
p.push_pull(flow_m3, volumes_list)   # advance one timestep
```

`fill(input_sol)` — fill the entire pipe with a single solution dict.

`push_pull(flow, volumes)` — push `volumes` in, pull output out proportional to `flow` (m³ for this timestep). Sets `ready = True`.

---

### `Pump / Valve`

Zero-length FIFO links. Water passes through instantaneously with no storage.

```python
from victoria.fifo import Pump, Valve
```

Both inherit from `ZeroLengthFIFO` and have the same `fill()` and `push_pull()` interface as `Pipe`, but `state` is always empty and only `output_state` is populated.

---

## MIX classes

Mixing models for nodes. Created automatically by `Models`.

---

### `Junction`

Ideal mixing at a junction node. Demand is subtracted from the mixed volume.

```python
from victoria.mix import Junction
j = Junction()
j.mix(inflow, node, timestep, input_sol)
# j.mixed_parcels  → mixed parcel list
# j.outflow        → [[volume, quality], …] per downstream link
```

---

### `Reservoir`

Source node. Generates a parcel of source water each timestep.

```python
from victoria.mix import Reservoir
r = Reservoir()
r.mix(inflow, node, timestep, input_sol)
```

Ignores `inflow`. The quality is taken from `input_sol[node.uid]`.

---

### `Tank_CSTR`

Continuous stirred tank — complete instantaneous mixing.

```python
from victoria.mix import Tank_CSTR
t = Tank_CSTR(initvolume=500.0)
t.mix(inflow, node, timestep, input_sol)
```

| Constructor parameter | Description |
|---|---|
| `initvolume` | Initial tank volume in m³. |

Uses an exponential decay weighting based on the inflow-to-volume ratio.

---

### `Tank_FIFO`

Plug-flow tank — first water in is first water out.

```python
from victoria.mix import Tank_FIFO
t = Tank_FIFO(volume=500.0)
t.mix(inflow, node, timestep, input_sol)
```

---

### `Tank_LIFO`

Last-in-first-out tank — models gravity stratification where newer (warmer/lighter) water sits on top and exits first.

```python
from victoria.mix import Tank_LIFO
t = Tank_LIFO(maxvolume=500.0)
t.mix(inflow, node, timestep, input_sol)
```

---

## Models

Container that creates and stores FIFO/MIX model objects for every network component.

```python
from victoria.models import Models
m = Models(network)
```

**Attributes:**

| Attribute | Type | Contents |
|---|---|---|
| `nodes` | `dict[uid, MIX]` | All node models (junctions + reservoirs + tanks). |
| `junctions` | `dict[uid, Junction]` | Junction models. |
| `reservoirs` | `dict[uid, Reservoir]` | Reservoir models. |
| `tanks` | `dict[uid, Tank_*]` | Tank models. |
| `links` | `dict[uid, FIFO]` | All link models (pipes + pumps + valves). |
| `pipes` | `dict[uid, Pipe]` | Pipe models. |
| `pumps` | `dict[uid, Pump]` | Pump models. |
| `valves` | `dict[uid, Valve]` | Valve models. |

**Methods:**

`get_node_model(uid)` → node model. Raises `KeyError` if not found.

`get_link_model(uid)` → link model. Raises `KeyError` if not found.

`Models._calculate_pipe_volume(length_m, diameter_mm)` → `float` — static helper: `π/4 × L × (D_mm / 1000)²` (diameter is converted from mm to m before squaring).

---

## Solver

Implements the recursive parcel tracing and network filling algorithm. Accessible via `vic.solver`.

```python
vic.solver.run_trace(node, timestep, input_sol)
vic.solver.fill_network(node, input_sol)
vic.solver.check_connections()
vic.solver.reset_ready_state()
```

In normal usage you do not call these directly — `Victoria.step()`,
`fill_network()`, and `check_flow_direction()` wrap them.

---

## Quality

Calculates concentrations and properties by querying the PHREEQC state.
Accessible via `vic.quality`.

In normal usage you call the query methods on the `Victoria` instance, which
delegates to `Quality` internally.

---

## Units reference

The `units` argument accepted by all concentration query methods is passed
directly to `PhreeqPython.Solution.total(element, units)`.

| Value | Meaning |
|---|---|
| `'mg'` | milligrams per litre (mg/L) |
| `'mmol'` | millimoles per litre — **default for most methods** |
| `'mol'` | moles per litre |
| `'ppm'` | parts per million (numerically ≈ mg/L for dilute water) |

> **Important:** Do not pass `'mg/L'` — PhreeqPython does not recognise the
> slash notation. Use `'mg'`.

PHREEQC element names are case-sensitive and follow standard chemical symbols:
`'Ca'`, `'Mg'`, `'Na'`, `'Cl'`, `'SO4'`, `'HCO3'`, etc. Species names
(e.g. `'Ca+2'`) are also accepted where PhreeqPython supports them.
