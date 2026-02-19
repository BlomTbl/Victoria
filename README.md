# Victoria - Water Quality Simulator for Hydraulic Networks

[![CI/CD](https://github.com/BlomTbl/victoria/workflows/Victoria%20CI/CD/badge.svg)](https://github.com/BlomTbl/victoria/actions)
[![codecov](https://codecov.io/gh/BlomTbl/victoria/branch/main/graph/badge.svg)](https://codecov.io/gh/BlomTbl/victoria)
[![PyPI version](https://badge.fury.io/py/victoria.svg)](https://badge.fury.io/py/victoria)
[![Python versions](https://img.shields.io/pypi/pyversions/victoria.svg)](https://pypi.org/project/victoria/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

A Python package for simulating water quality in hydraulic distribution networks using PHREEQC chemistry coupled with EPyNet hydraulic simulation.

## 🌟 Features

- **FIFO Parcel Tracking**: First In First Out water parcel tracking through pipes, pumps, and valves
- **Multiple Mixing Models**: Support for different node types with appropriate mixing strategies
  - Junctions: Ideal mixing
  - Reservoirs: Source nodes
  - Tanks: CSTR, FIFO, or LIFO models
- **Water Chemistry**: Integration with PHREEQC for detailed water chemistry calculations
- **Pipe Segmentation**: Fixed-length segment concentration analysis with time-series recording via `PipeSegmentation`
- **EPyNet Compatible**: Works seamlessly with EPyNet hydraulic network models
- **Cross-Platform**: Windows, Linux, and macOS support

## 📦 Installation

### From GitHub

```bash
pip install git+https://github.com/BlomTbl/victoria.git
```

### From Source

```bash
git clone https://github.com/BlomTbl/victoria.git
cd victoria
pip install -e .
```

## 🚀 Quick Start

```python
import epynet
import phreeqpython
from victoria import Victoria

# Load hydraulic network
network = epynet.Network('network.inp')
network.solve()

# Initialize PHREEQC
pp = phreeqpython.PhreeqPython()

# Create Victoria simulator
vic = Victoria(network, pp)

# Define input solutions — key 0 is the background (pipe fill) solution,
# reservoir UIDs map to source solutions
solutions = {
    0:    pp.add_solution({'Ca': 0,  'Cl': 0}),    # background / pipe fill
    'R1': pp.add_solution({'Ca': 50, 'Cl': 100}),  # reservoir R1
    'R2': pp.add_solution({'Ca': 30, 'Cl': 60}),   # reservoir R2
}

# Fill network with initial conditions
vic.fill_network(solutions, from_reservoir=True)

# Run simulation loop
for hour in range(24):
    network.solve()
    vic.check_flow_direction()          # handle any flow reversals
    vic.step(timestep=3600, input_sol=solutions)

    # Query results
    for node in network.junctions:
        cl_conc = vic.get_conc_node(node, 'Cl', 'mg')
        print(f"Hour {hour}, Node {node.uid}: Cl = {cl_conc:.2f} mg/L")

    # Periodically free unused PHREEQC solutions from memory
    if hour % 6 == 0:
        vic.garbage_collect(solutions)
```

## 🔬 Pipe Segmentation

`PipeSegmentation` divides pipes into fixed-length physical segments and computes
the length-weighted average concentration in each segment from the FIFO parcel state.

```python
# One-off snapshot of all pipes at the current simulation state
df = vic.segment_network(network, species='Ca', units='mg', seg_length_m=6.0)

# Time-series recording inside a simulation loop
seg = vic.segmentation(seg_length_m=6.0)

for step in range(N_STEPS):
    network.solve()
    vic.check_flow_direction()
    vic.step(timestep=300, input_sol=solutions)
    seg.record_step(network, species='Ca', units='mg',
                    time_s=(step + 1) * 300, step=step + 1)

df_ts = seg.to_dataframe()   # tidy DataFrame: pipe × seg_id × time_s × conc
```

The returned DataFrame has columns: `pipe`, `seg_id`, `x_start_m`, `x_end_m`,
`x_mid_m`, `length_m`, `conc`, `n_parcels` (plus `time_s`, `time_min`, `step`
when recording a time-series).

## 📚 Documentation

- [Contributing Guide](CONTRIBUTING.md)
- [Changelog](CHANGELOG.md)

## 🧪 Requirements

- Python >= 3.7
- epynet >= 0.2.0
- phreeqpython >= 1.2.0

## 🧬 API Overview

| Method | Description |
|---|---|
| `Victoria(network, pp)` | Constructor |
| `fill_network(input_sol, from_reservoir)` | Initialise pipe water quality |
| `step(timestep, input_sol)` | Advance one quality timestep |
| `check_flow_direction()` | Detect and handle flow reversals |
| `garbage_collect(input_sol)` | Free unused PHREEQC solutions |
| `get_conc_node(node, species, units)` | Instantaneous concentration at node |
| `get_conc_node_avg(node, species, units)` | Time-averaged concentration at node |
| `get_conc_pipe(link, species, units)` | Parcel concentration profile in pipe |
| `get_conc_pipe_avg(link, species, units)` | Volume-averaged concentration in pipe |
| `get_properties_node(node)` | `[pH, SC, temperature]` at node |
| `get_parcels(link)` | Raw parcel list in pipe |
| `segmentation(seg_length_m)` | Create a `PipeSegmentation` recorder |
| `segment_pipe(pipe, species, units, seg_length_m)` | One-off segment profile for one pipe |
| `segment_network(network, species, units, seg_length_m)` | One-off segment snapshot for all pipes |

Valid `units` strings (passed to PhreeqPython): `'mg'`, `'mmol'`, `'mol'`, `'ppm'`.

## 🤝 Contributing

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for details.

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 📞 Support

- **Issues**: [GitHub Issues](https://github.com/BlomTbl/victoria/issues)
- **Discussions**: [GitHub Discussions](https://github.com/BlomTbl/victoria/discussions)

---

Made with ❤️ by the Victoria Contributors
