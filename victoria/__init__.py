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

    # Run simulation — with segment-level time-series recording
    seg = vic.segmentation(seg_length_m=6.0)

    for step in range(simulation_steps):
        network.solve()
        vic.check_flow_direction()          # recommended before step()
        vic.step(timestep=3600, input_sol=solutions)
        seg.record_step(network, species='Ca', units='mg',
                        time_s=(step + 1) * 3600, step=step + 1)

    df_ts  = seg.to_dataframe()           # full time-series DataFrame
    df_now = vic.segment_network(         # snapshot at current state
                 network, species='Ca', units='mg', seg_length_m=6.0)

    # Query node results
    conc = vic.get_conc_node(node, 'Cl', 'mg/L')

    # Periodic garbage collection to free unused PHREEQC solutions
    vic.garbage_collect(input_sol=solutions)

    # Configure specific tanks as FIFO or LIFO
    from victoria import Models, Tank_FIFO
    models = Models(network, tank_model_map={'T1': Tank_FIFO})
    ```
"""

from .victoria import Victoria
from .models import Models
from .solver import Solver, HydraulicCache
from .quality import Quality
from .segmentation import PipeSegmentation
from .fifo import FIFO, Pipe, Pump, Valve
from .mix import MIX, Junction, Reservoir, Tank_CSTR, Tank_FIFO, Tank_LIFO

__version__ = '1.2.0'
__author__ = 'Victoria Contributors'

__all__ = [
    # Main classes
    'Victoria',
    'Models',
    'Solver',
    'HydraulicCache',
    'Quality',

    # Segmentation
    'PipeSegmentation',

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
