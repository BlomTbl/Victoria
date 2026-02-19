# Victoria - Water Quality Simulator for Hydraulic Networks

[![CI/CD](https://github.com/USERNAME/victoria/workflows/Victoria%20CI/CD/badge.svg)](https://github.com/USERNAME/victoria/actions)
[![codecov](https://codecov.io/gh/USERNAME/victoria/branch/main/graph/badge.svg)](https://codecov.io/gh/USERNAME/victoria)
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
- **EPyNet Compatible**: Works seamlessly with EPyNet hydraulic network models
- **Cross-Platform**: Windows, Linux, and macOS support

## 📦 Installation

### From GitHub

```bash
pip install git+https://github.com/USERNAME/victoria.git
```

### From Source

```bash
git clone https://github.com/USERNAME/victoria.git
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

# Initialize PHREEQC
pp = phreeqpython.PhreeqPython()

# Create Victoria simulator
vic = Victoria(network, pp)

# Define input solutions for each reservoir
solutions = {
    reservoir1: pp.add_solution({'Ca': 50, 'Cl': 100}),
    reservoir2: pp.add_solution({'Ca': 30, 'Cl': 60}),
}

# Fill network with initial conditions
vic.fill_network(solutions)

# Run simulation loop
for hour in range(24):
    network.solve()
    vic.step(timestep=3600, input_sol=solutions)
    
    # Query results
    for node in network.junctions:
        cl_conc = vic.get_conc_node(node, 'Cl', 'mg/L')
        print(f"Hour {hour}, Node {node.uid}: Cl = {cl_conc:.2f} mg/L")
```

## 📚 Documentation

- [API Reference](docs/api.md)
- [Examples](examples/)
- [Contributing Guide](CONTRIBUTING.md)
- [Changelog](CHANGELOG.md)

## 🧪 Requirements

- Python >= 3.7
- epynet >= 0.2.0
- phreeqpython >= 1.2.0

## 🤝 Contributing

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for details.

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 📞 Support

- **Issues**: [GitHub Issues](https://github.com/USERNAME/victoria/issues)
- **Discussions**: [GitHub Discussions](https://github.com/USERNAME/victoria/discussions)

---

Made with ❤️ by the Victoria Contributors

Cover image for DeepWiki: Complete Guide + Hacks
Rishabh Singh
Rishabh Singh

Posted on 11 mei 2025 • Edited on 5 nov 2025
4
DeepWiki: Complete Guide + Hacks
#github
#ai
#productivity
#opensource
Introduction


#career #learning #ai #programmers

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/BlomTbl/victoria)
