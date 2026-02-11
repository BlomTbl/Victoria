"""
Victoria - Water Quality Simulator for Hydraulic Networks.

Main module providing the high-level API for water quality simulation
using PHREEQC chemistry with EPyNet hydraulic networks.
"""
from typing import Any, Dict, List, Set, Optional
import logging

from .solver import Solver
from .quality import Quality
from .models import Models

logger = logging.getLogger(__name__)


class Victoria:
    """
    Main Victoria water quality simulator.
    
    Combines hydraulic network simulation (EPyNet) with water chemistry
    simulation (PHREEQC) to track water quality through distribution networks.
    """
    
    def __init__(self, network: Any, pp: Any):
        """
        Initialize Victoria simulator.
        
        Args:
            network: EPyNet network object (must be hydraulically solved)
            pp: PhreeqPython instance for chemistry calculations
        """
        self.net = network
        self.pp = pp
        self.models = Models(network)
        self.solver = Solver(self.models, network)
        self.quality = Quality(pp, self.models)
        self.output: List = []
        
        logger.info("Victoria simulator initialized")

    def step(self, timestep: float, input_sol: Dict) -> None:
        """
        Simulate one timestep of water quality evolution.
        
        Must be called after hydraulic simulation for the corresponding timestep.
        
        Args:
            timestep: Time step duration in seconds
            input_sol: Dictionary mapping node IDs to PHREEQC solutions
        """
        if timestep <= 0:
            raise ValueError(f"Timestep must be positive, got {timestep}")
            
        logger.debug(f"Running quality step for timestep={timestep}s")

        # Trace from each reservoir
        for emitter in self.net.reservoirs:
            try:
                self.solver.run_trace(emitter, timestep, input_sol)
            except Exception as e:
                logger.error(f"Error tracing from reservoir {emitter.uid}: {e}")
                raise

        # Reset ready state for next timestep
        self.solver.reset_ready_state()

    def fill_network(self, input_sol: Dict, from_reservoir: bool = True) -> None:
        """
        Initialize the network with starting water quality.
        
        Should be called once before starting the simulation.
        
        Args:
            input_sol: Dictionary mapping node IDs to PHREEQC solutions
            from_reservoir: If True, fill from reservoirs; if False, 
                          use solution 0 for all pipes
        """
        logger.info("Filling network with initial solutions")
        
        if from_reservoir:
            # Fill from each reservoir
            for emitter in self.net.reservoirs:
                try:
                    self.solver.fill_network(emitter, input_sol)
                except KeyError:
                    logger.error(f"No solution defined for reservoir {emitter.uid}")
                    raise

            # Fill remaining unfilled links with default solution
            link_list = set(self.net.links)
            link_filled = set(self.solver.filled_links)
            unfilled = link_list - link_filled

            if unfilled:
                logger.info(f"Filling {len(unfilled)} unfilled links with default solution")
                
                try:
                    default_sol = {input_sol[0].number: 1.0}
                    for link in unfilled:
                        if link.uid in self.solver.models.pipes:
                            self.solver.models.pipes[link.uid].fill(default_sol)
                except KeyError:
                    logger.error("No initial solution defined for key=0")
                    raise
                except AttributeError as e:
                    logger.error(f"Invalid solution object: {e}")
                    raise
        else:
            # Fill all pipes with default solution
            logger.info("Filling all pipes with default solution")
            
            try:
                default_sol = {input_sol[0].number: 1.0}
                for pipe in self.net.pipes:
                    self.solver.models.pipes[pipe.uid].fill(default_sol)
            except KeyError:
                logger.error("No initial solution defined for key=0")
                raise
            except AttributeError as e:
                logger.error(f"Invalid solution object: {e}")
                raise

        # Reset ready state
        self.solver.reset_ready_state()
        logger.info("Network filling complete")

    def check_flow_direction(self) -> None:
        """
        Check for flow reversals and update parcel positions.
        
        Should be called after each hydraulic timestep if flow reversals
        are possible.
        """
        self.solver.check_connections()

    def garbage_collect(self, input_sol: Optional[Dict] = None) -> None:
        """
        Remove unused PHREEQC solutions from memory.
        
        Should be called periodically to prevent memory buildup from
        unused solution objects.
        
        Args:
            input_sol: Dictionary of input solutions to preserve (optional)
        """
        # Collect all solution numbers currently in use
        registered_solutions: Set[int] = set()
        
        # Solutions in pipes
        for pipe in self.solver.models.pipes.values():
            for parcel in pipe.state:
                registered_solutions.update(parcel['q'].keys())
        
        # Solutions in tanks
        for tank in self.solver.models.tanks.values():
            if hasattr(tank, 'state'):
                for parcel in tank.state:
                    registered_solutions.update(parcel['q'].keys())
            if hasattr(tank, 'mixture') and tank.mixture:
                # For CSTR tanks, mixture dict might have solution numbers
                if isinstance(tank.mixture, dict):
                    registered_solutions.update(tank.mixture.keys())
        
        # Solutions in node outputs
        for node in self.solver.models.nodes.values():
            if hasattr(node, 'mixed_parcels'):
                for parcel in node.mixed_parcels:
                    registered_solutions.update(parcel['q'].keys())
        
        # Preserve input solutions - these should never be deleted
        if input_sol:
            for sol in input_sol.values():
                if hasattr(sol, 'number'):
                    registered_solutions.add(sol.number)

        # Get all solutions in PHREEQC
        phreeqc_solutions = set(self.pp.get_solution_list())
        
        # Find solutions to remove
        to_forget = phreeqc_solutions - registered_solutions
        
        if to_forget:
            logger.info(f"Removing {len(to_forget)} unused PHREEQC solutions")
            self.pp.remove_solutions(to_forget)

    # ========== Quality Query Methods ==========

    def get_conc_node(self, node: Any, element: str, units: str = 'mmol') -> float:
        """
        Get instantaneous concentration at node exit.
        
        Args:
            node: Node object
            element: Chemical element/species (e.g., 'Ca', 'Cl')
            units: Units for concentration (default: 'mmol')
            
        Returns:
            Concentration value
        """
        return self.quality.get_conc_node(node, element, units)

    def get_conc_node_avg(self, node: Any, element: str, units: str = 'mmol') -> float:
        """
        Get time-averaged concentration at node exit.
        
        Args:
            node: Node object
            element: Chemical element/species (e.g., 'Ca', 'Cl')
            units: Units for concentration (default: 'mmol')
            
        Returns:
            Time-averaged concentration
        """
        return self.quality.get_conc_node_avg(node, element, units)

    def get_mixture_node(self, node: Any) -> Dict[int, float]:
        """
        Get instantaneous solution mixture at node exit.
        
        Args:
            node: Node object
            
        Returns:
            Dictionary mapping solution numbers to volume fractions
        """
        return self.quality.get_mixture_node(node)

    def get_mixture_node_avg(self, node: Any) -> Dict[int, float]:
        """
        Get time-averaged solution mixture at node exit.
        
        Args:
            node: Node object
            
        Returns:
            Dictionary mapping solution numbers to time-averaged fractions
        """
        return self.quality.get_mixture_node_avg(node)

    def get_conc_pipe(self, link: Any, element: str, units: str = 'mmol') -> List[Dict]:
        """
        Get concentration profile along a pipe.
        
        Args:
            link: Pipe link object
            element: Chemical element/species (e.g., 'Ca', 'Cl')
            units: Units for concentration (default: 'mmol')
            
        Returns:
            List of parcels with positions and concentrations
        """
        return self.quality.get_conc_pipe(link, element, units)

    def get_conc_pipe_avg(self, link: Any, element: str, units: str = 'mmol') -> float:
        """
        Get volume-averaged concentration in a pipe.
        
        Args:
            link: Pipe link object
            element: Chemical element/species (e.g., 'Ca', 'Cl')
            units: Units for concentration (default: 'mmol')
            
        Returns:
            Volume-averaged concentration
        """
        return self.quality.get_conc_pipe_avg(link, element, units)

    def get_parcels(self, link: Any) -> List[Dict]:
        """
        Get all parcels in a pipe.
        
        Args:
            link: Pipe link object
            
        Returns:
            List of parcel dictionaries with positions and qualities
        """
        return self.quality.get_parcels(link)

    def get_properties_node(self, node: Any) -> List[float]:
        """
        Get instantaneous water properties at node exit.
        
        Args:
            node: Node object
            
        Returns:
            List of [pH, specific conductivity (μS/cm), temperature (°C)]
        """
        return self.quality.get_properties_node(node)

    def get_properties_node_avg(self, node: Any) -> List[float]:
        """
        Get time-averaged water properties at node exit.
        
        Args:
            node: Node object
            
        Returns:
            List of [pH, specific conductivity (μS/cm), temperature (°C)]
        """
        return self.quality.get_properties_node_avg(node)
