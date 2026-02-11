"""
Victoria - Water Quality Simulator for Hydraulic Networks.

A Python package for simulating water quality in hydraulic distribution
networks using PHREEQC chemistry coupled with EPyNet hydraulic simulation.

Example usage:
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
"""

from .victoria import Victoria
from .models import Models
from .solver import Solver
from .quality import Quality
from .fifo import FIFO, Pipe, Pump, Valve
from .mix import MIX, Junction, Reservoir, Tank_CSTR, Tank_FIFO, Tank_LIFO

__version__ = '1.0.0'
__author__ = 'Victoria Contributors'

__all__ = [
    # Main classes
    'Victoria',
    'Models',
    'Solver',
    'Quality',
    
    # FIFO classes
    'FIFO',
    'Pipe',
    'Pump',
    'Valve',
    
    # MIX classes
    'MIX',
    'Junction',
    'Reservoir',
    'Tank_CSTR',
    'Tank_FIFO',
    'Tank_LIFO',
]
