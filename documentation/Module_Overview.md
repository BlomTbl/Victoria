# FIFO Module 🚰

## Overview  
The FIFO module implements first-in–first-out parcel tracking for links in a hydraulic network. It optimizes parcel handling by using a cumulative offset system and merges adjacent parcels with identical quality. This design reduces complexity from O(n²) to O(n) for continuous simulation.

## Key Classes  

### Parcel  
- Represents a water parcel segment in a pipe.  
- Attributes:  
  - `x0` (float): Normalized start position (0 – 1).  
  - `x1` (float): Normalized end position (0 – 1).  
  - `q` (Dict[int, float]): Mapping of PHREEQC solution numbers to fractions.  
- Method:  
  - `to_dict()` → `Dict[str, Any]`: Serialize parcel data.  

### FIFO  
- Base class for all link models.  
- Attributes:  
  - `volume` (float): Link storage capacity (m³).  
  - `state` (List[Dict]): Current parcels inside link.  
  - `output_state` (List[Dict]): Parcels exiting link this step.  
  - `offset` (float): Cumulative shift for optimized indexing.  
  - `ready` (bool): Flag indicating if link has been updated.  
  - `upstream_node`, `downstream_node`: References to connected nodes.  
- Methods:  
  - `connections(downstream, upstream)`: Set link endpoints.  
  - `reverse_parcels(new_down, new_up)`: Mirror parcel positions on flow reversal.  
  - `push_in(volumes)`: Insert new parcels without shifting existing ones.  
  - `push_pull(flow, volumes)`: Advance parcels, compute `output_state`, mark `ready`.  
  - `_materialize()`: Apply offset to parcel positions before operations.  

### Pipe (FIFO)  
- Models a physical pipe with volume-based parcel tracking.  
- Methods:  
  - `fill(input_sol)`: Initialize pipe with a uniform parcel of background solution.  
  - `push_pull(flow, volumes)`: Advance parcels by hydraulic flow, flush as needed.  

### ZeroLengthFIFO, Pump, Valve  
- Represent instantaneous links with zero storage.  
- Inherit common interface (`fill`, `push_pull`) from `ZeroLengthFIFO`.  
- `Pump` and `Valve` pass parcels through immediately with no internal state.  

---

# MIX Module

## Overview  
The MIX module provides node mixing strategies for water quality simulation. It defines a base mixing class and specialized subclasses for junctions, reservoirs, and tanks, each implementing a `mix` method.

## Key Classes  

### MIX (Base)  
- Static methods handle quality merging and outflow distribution.  
- Responsibilities:  
  - `merge_load(existing_q, new_q, frac)` → `Dict[int, float]`: Combine quality dictionaries by fraction.  
  - `get_total_flow(parcels)` → `float`: Sum of parcel volumes.  
  - `parcels_out(flows)` → `List[List]`: Distribute mixed parcels into outflow segments.  

### Junction  
- Performs ideal mixing of all inflows.  
- Subtracts node demand from total volume before distribution.  

### Reservoir  
- Treats node as a constant source.  
- Ignores inflow; uses `input_sol[node.uid]` for quality.  

### Tank_CSTR  
- Continuous stirred tank reactor model.  
- Constructor: `Tank_CSTR(initvolume: float)`.  
- Implements exponential decay weighting based on inflow-to-volume ratio.  

### Tank_FIFO  
- Plug-flow tank (first-in–first-out).  
- Implements `mix` to shift parcels through a virtual FIFO buffer.  

### Tank_LIFO  
- Last-in–first-out tank.  
- Models stratification; newer water exits first.  

---

# Models Module

## Overview  
The Models module instantiates and stores FIFO and MIX models for every network component. It bridges EPyNet network objects to simulation models.

## Class: Models  

### Attributes  
- `nodes` (Dict[str, MIX]): All node models.  
- `junctions` (Dict[str, Junction])  
- `reservoirs` (Dict[str, Reservoir])  
- `tanks` (Dict[str, Any])  
- `links` (Dict[str, FIFO])  
- `pipes` (Dict[str, Pipe])  
- `pumps` (Dict[str, Pump])  
- `valves` (Dict[str, Valve])  

### Methods  
- `__init__(network)`: Initialize all models from EPyNet network.  
- `_load_links(network)`:  
  - Computes each pipe’s volume via `_calculate_pipe_volume`.  
  - Instantiates `Pipe`, `Pump`, `Valve` models.  
- `_load_nodes(network)`:  
  - Creates `Junction` and `Reservoir` models.  
  - Defaults tanks to `Tank_CSTR` unless overridden.  
- `_create_models(items, model_cls, model_dict, update_dict)`: Generic factory for a list of network objects.  
- `_calculate_pipe_volume(length_m, diameter_mm)` → `float`: Returns m³ volume using π/4·D²·L.  

---

# Solver Module

## Overview  
The Solver module traces water parcels through the network using a breadth-first fill algorithm and handles flow reversals. It manages ready states to coordinate link and node updates.

## Class: Solver  

### Attributes  
- `models`: Instance of `Models`.  
- `network`: EPyNet network reference.  
- Internal mappings:  
  - `_up_links`, `_down_links`: Node-to-link connectivity.  
  - `_link_obj`, `_node_obj`: UID lookup for link and node objects.  
  - `filled_links`: List of links filled in the current step.  
  - `_ready`: Set of link UIDs ready for processing.  

### Methods  
- `__init__(models, network)`: Build connectivity maps and initial state.  
- `reset_ready_state()`: Clear `_ready` set and `filled_links` list.  
- `fill_network(start_node, input_sol)`:  
  1. Traverse nodes whose upstream links are all ready.  
  2. Call each node’s `mix` with inflow parcels.  
  3. Select appropriate solution for each downstream link via `_select_fill_solution`.  
  4. Call link `fill` and mark it ready.  
- `check_connections()`: Detect links whose flow direction reversed and call `reverse_parcels`.  
- `_select_fill_solution(node_outflow, index, input_sol)` → solution dict: Choose correct PHREEQC solution for the given link.  
- `_get_links(node, direction)` → List[link]: Backward compatibility helper.  
- `_get_node_attr(obj, attr)` → Any: Invoke attribute or method.  
- `_all_upstream_links_ready(node)` → `bool`: Check readiness of all upstream links.  

---

# Quality Module

## Overview  
The Quality module calculates concentrations and properties by mixing PHREEQC solutions according to parcel distributions. It supports instantaneous and time-averaged queries.

## Class: Quality  

### Attributes  
- `pp`: `PhreeqPython` instance.  
- `models`: `Models` instance.  

### Methods  
- `get_parcels(link)` → `List[Dict[str, Any]]`: Return raw parcel list for a pipe.  
- `get_conc_node(node, element, units='mmol')` → `float`: Instantaneous concentration at node exit.  
- `get_conc_node_avg(node, element, units='mmol')` → `float`: Time-averaged node concentration.  
- `get_conc_pipe(link, element, units='mmol')` → `List[float]`: Concentration profile over pipe parcels.  
- `get_conc_pipe_avg(link, element, units='mmol')` → `float`: Volume-weighted average concentration in pipe.  
- `get_mixture_node(node)` → `Dict[int, float]`: Instantaneous solution fractions at node.  
- `get_mixture_node_avg(node)` → `Dict[int, float]`: Time-averaged solution fractions.  
- `get_properties_node(node)` → `List[Any]`: Instantaneous `[pH, conductivity, temperature]`.  
- `get_properties_node_avg(node)` → `List[Any]`: Time-averaged properties.  

---

# Segmentation Module 📐

## Overview  
The Segmentation module divides pipes into fixed-length segments and computes concentration statistics per segment. It supports one-off queries and time series recording.

## Class: PipeSegmentation  

### Attributes  
- `model`: `Victoria` instance.  
- `seg_length_m` (float): Segment length in metres.  

### Methods  
- `__init__(model, seg_length_m)`: Validate and store segment length.  
- `segment_pipe(pipe, species, units='mg')` → `List[Dict]`: Returns per-segment concentration data for one pipe.  
- `segment_network(network, species, units='mg')` → `pandas.DataFrame`: Tidy table for all pipes.  
- `record_step(network, species, units, time_s=None, step=None)`: Append current concentrations to internal buffer.  
- `to_dataframe()` → `pandas.DataFrame`: Retrieve recorded time-series data.  
- `reset()`: Clear internal time-series buffer.  
- `pipe_metadata()` → `Dict[str, int]`: Number of segments per pipe UID.  

---

# Victoria API

## Overview  
The `Victoria` class provides a high-level API to coordinate hydraulic and water quality simulation. It composes the Models, Solver, Quality, and Segmentation modules.

## Class: Victoria  

### Methods  

```python
vic = Victoria(network, pp)
```
- **Constructor**  
  - `network`: EPyNet network (solved hydraulically).  
  - `pp`: Initialized `PhreeqPython` instance.  
  - Instantiates `Models`, `Solver`, and `Quality`.  

```python
vic.fill_network(input_sol, from_reservoir=True)
```
- **Initialize all pipes**  
  - `input_sol`: Dict mapping reservoir UIDs and key `0` to PHREEQC solutions.  
  - `from_reservoir`: If `True`, starts fill from reservoirs; otherwise fills all from `input_sol[0]`.  

```python
vic.step(timestep, input_sol)
```
- **Advance one quality timestep**  
  - `timestep`: Duration in seconds.  
  - `input_sol`: Solution mapping for reservoirs.  
  - Internally resets solver state, checks flow reversals, and fills links.  

```python
vic.check_flow_direction()
```
- **Handle flow reversals** by invoking solver’s reversal logic.  

```python
vic.garbage_collect(input_sol)
```
- **Free unused PHREEQC solutions** in long simulations.  

```python
vic.get_conc_node(node, species, units)
```
- **Instantaneous concentration** at a node exit.  

```python
vic.get_conc_node_avg(node, species, units)
```
- **Time-averaged concentration** at a node exit.  

```python
vic.get_conc_pipe(link, species, units)
```
- **Parcel concentration profile** in a pipe.  

```python
vic.get_conc_pipe_avg(link, species, units)
```
- **Volume-weighted average concentration** in a pipe.  

```python
vic.get_mixture_node(node)
vic.get_mixture_node_avg(node)
```
- **Instantaneous and averaged solution fractions** at a node.  

```python
vic.get_properties_node(node)
vic.get_properties_node_avg(node)
```
- **Instantaneous and averaged** `[pH, conductivity, temperature]`.  

```python
seg = vic.segmentation(seg_length_m)
```
- **Create a recorder** for time-series segmentation.  

```python
vic.segment_pipe(pipe, species, units, seg_length_m)
vic.segment_network(network, species, units, seg_length_m)
```
- **One-off segmentation** for a pipe or the entire network.  

---

## Architecture Overview

```mermaid
flowchart TB
    subgraph Core
        Victoria["Victoria"]
        Models["Models"]
        Solver["Solver"]
        Quality["Quality"]
        PipeSegmentation["PipeSegmentation"]
    end
    subgraph Modules
        FIFO["FIFO module"]
        MIX["MIX module"]
    end

    Victoria --> Models
    Victoria --> Solver
    Victoria --> Quality
    Victoria --> PipeSegmentation
    Models --> FIFO
    Models --> MIX
    Solver --> Models
    Quality --> Models
    PipeSegmentation --> Models
```
