"""Setup script for Victoria water quality simulator."""

from setuptools import setup, find_packages
from pathlib import Path

# Read the README file
this_directory = Path(__file__).parent
long_description = """
Victoria - Water Quality Simulator for Hydraulic Networks
==========================================================

A Python package for simulating water quality in hydraulic distribution
networks using PHREEQC chemistry coupled with EPyNet hydraulic simulation.

Features
--------
- FIFO (First In First Out) parcel tracking through pipes
- Multiple mixing models for nodes (junctions, reservoirs, tanks)
- Support for CSTR, FIFO, and LIFO tank models
- Integration with PHREEQC for water chemistry calculations
- Compatible with EPyNet hydraulic network models

Installation
------------
```bash
pip install victoria-1.0.0.tar.gz
```

Requirements
------------
- Python >= 3.7
- epynet
- phreeqpython

Quick Start
-----------
```python
import epynet
import phreeqpython
from victoria import Victoria

# Load network and set up chemistry
network = epynet.Network('network.inp')
pp = phreeqpython.PhreeqPython()

# Create simulator
vic = Victoria(network, pp)

# Define input solutions
solutions = {...}
vic.fill_network(solutions)

# Run simulation
for t in range(simulation_steps):
    network.solve()
    vic.step(timestep=3600, input_sol=solutions)
    
    # Query results
    conc = vic.get_conc_node(node, 'Cl', 'mg/L')
```

License
-------
See LICENSE file for details.

Authors
-------
Victoria Contributors
"""

setup(
    name='victoria',
    version='1.1.0',
    author='Victoria Contributors',
    author_email='',
    description='Water Quality Simulator for Hydraulic Networks',
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='',
    packages=find_packages(),
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Science/Research',
        'Topic :: Scientific/Engineering :: Chemistry',
        'Topic :: Scientific/Engineering :: Hydrology',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
    ],
    python_requires='>=3.7',
    install_requires=[
        'epynet>=0.2.0',
        'phreeqpython>=1.2.0',
    ],
    extras_require={
        'dev': [
            'pytest>=6.0',
            'pytest-cov',
            'black',
            'flake8',
            'mypy',
        ],
    },
    keywords='water quality hydraulic networks PHREEQC simulation chemistry',
    project_urls={
        'Documentation': '',
        'Source': '',
        'Bug Reports': '',
    },
)
