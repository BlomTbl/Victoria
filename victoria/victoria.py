"""
Victoria - Water Quality Simulator for Hydraulic Networks.
Main module providing the high-level API for water quality simulation using PHREEQC chemistry with EPyNet hydraulic networks.
"""

from typing import Any, Dict, List, Set, Optional
import logging

from .solver import Solver
from .quality import Quality
from .models import Models
from .segmentation import PipeSegmentation

logger = logging.getLogger(__name__)


class Victoria:
    """
    Main Victoria water quality simulator.

    Combines hydraulic network simulation (EPyNet) with water chemistry simulation (PHREEQC)
    to track water quality through distribution networks.
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

        for reservoir in self.net.reservoirs:
            self._run_safe_trace(reservoir, timestep, input_sol)

        self.solver.reset_ready_state()

    def _run_safe_trace(self, emitter, timestep: float, input_sol: Dict):
        try:
            self.solver.run_trace(emitter, timestep, input_sol)
        except Exception as e:
            logger.error(f"Error tracing from reservoir {emitter.uid}: {e}")
            raise

    def fill_network(self, input_sol: Dict, from_reservoir: bool = True) -> None:
        """
        Initialize the network with starting water quality. Should be called once before starting the simulation.

        Args:
            input_sol: Dictionary mapping node IDs to PHREEQC solutions
            from_reservoir: If True, fill from reservoirs; if False, use solution 0 for all pipes
        """
        logger.info("Filling network with initial solutions")

        def _get_default_solution(input_sol):
            # Prefer integer key 0 for backward compatibility, but fall back to
            # the first available solution object if key 0 is absent.
            # This avoids errors when input_sol only uses node-uid string keys.
            candidate = input_sol.get(0, None)
            if candidate is None:
                for v in input_sol.values():
                    if hasattr(v, 'number'):
                        candidate = v
                        break
            if candidate is None:
                logger.error("No solution object found in input_sol for default fill")
                raise KeyError("No valid solution object in input_sol")
            return {candidate.number: 1.0}

        if from_reservoir:
            for emitter in self.net.reservoirs:
                try:
                    self.solver.fill_network(emitter, input_sol)
                except KeyError:
                    logger.error(f"No solution defined for reservoir {emitter.uid}")
                    raise

            # Fill remaining unfilled links with default solution
            link_list = {link.uid for link in self.net.links}
            filled_links = set(self.solver.filled_links)
            unfilled_uids = link_list - filled_links

            if unfilled_uids:
                logger.info(f"Filling {len(unfilled_uids)} unfilled links with default solution")
                default_sol = _get_default_solution(input_sol)
                for link in self.net.links:
                    if link.uid in unfilled_uids and link.uid in self.solver.models.pipes:
                        self.solver.models.pipes[link.uid].fill(default_sol)
        else:
            logger.info("Filling all pipes with default solution")
            default_sol = _get_default_solution(input_sol)
            for pipe in self.net.pipes:
                self.solver.models.pipes[pipe.uid].fill(default_sol)

        self.solver.reset_ready_state()
        logger.info("Network filling complete")

    def check_flow_direction(self) -> None:
        """
        Check for flow reversals and update parcel positions.
        Should be called after each hydraulic timestep if flow reversals are possible.
        """
        self.solver.check_connections()

    def garbage_collect(self, input_sol: Optional[Dict] = None) -> None:
        """
        Remove unused PHREEQC solutions from memory.
        Should be called periodically to prevent memory buildup from unused solution objects.

        Args:
            input_sol: Dictionary of input solutions to preserve (optional)
        """
        registered_solutions: Set[int] = set()

        # Collect solution numbers from all relevant objects
        def _collect_solutions_from_state(state_list):
            for parcel in state_list:
                registered_solutions.update(parcel.get('q', {}).keys())

        # Solutions in pipes
        for pipe in self.solver.models.pipes.values():
            if hasattr(pipe, 'state'):
                _collect_solutions_from_state(pipe.state)

        # Solutions in tanks
        for tank in self.solver.models.tanks.values():
            if hasattr(tank, 'state'):
                _collect_solutions_from_state(tank.state)
            # For CSTR tanks, mixture dict might have solution numbers
            if getattr(tank, 'mixture', None) and isinstance(tank.mixture, dict):
                registered_solutions.update(tank.mixture.keys())

        # Solutions in node outputs
        for node in self.solver.models.nodes.values():
            if hasattr(node, 'mixed_parcels'):
                _collect_solutions_from_state(node.mixed_parcels)

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
        """Get instantaneous concentration at node exit."""
        return self.quality.get_conc_node(node, element, units)

    def get_conc_node_avg(self, node: Any, element: str, units: str = 'mmol') -> float:
        """Get time-averaged concentration at node exit."""
        return self.quality.get_conc_node_avg(node, element, units)

    def get_mixture_node(self, node: Any) -> Dict[int, float]:
        """Get instantaneous solution mixture at node exit."""
        return self.quality.get_mixture_node(node)

    def get_mixture_node_avg(self, node: Any) -> Dict[int, float]:
        """Get time-averaged solution mixture at node exit."""
        return self.quality.get_mixture_node_avg(node)

    def get_conc_pipe(self, link: Any, element: str, units: str = 'mmol') -> List[Dict]:
        """Get concentration profile along a pipe."""
        return self.quality.get_conc_pipe(link, element, units)

    def get_conc_pipe_avg(self, link: Any, element: str, units: str = 'mmol') -> float:
        """Get volume-averaged concentration in a pipe."""
        return self.quality.get_conc_pipe_avg(link, element, units)

    def get_parcels(self, link: Any) -> List[Dict]:
        """Get all parcels in a pipe."""
        return self.quality.get_parcels(link)

    def get_properties_node(self, node: Any) -> List[float]:
        """Get instantaneous water properties at node exit."""
        return self.quality.get_properties_node(node)

    def get_properties_node_avg(self, node: Any) -> List[float]:
        """Get time-averaged water properties at node exit."""
        return self.quality.get_properties_node_avg(node)

    # ========== Pipe Segmentation Methods ==========

    def segmentation(self, seg_length_m: float = 6.0) -> 'PipeSegmentation':
        """
        Create a PipeSegmentation helper bound to this Victoria instance.

        The returned object can be used to compute fixed-length segment
        concentrations for individual pipes or the entire network, and
        to record segment-level time-series during a simulation loop.

        Parameters
        ----------
        seg_length_m : float
            Physical length of each segment in metres (default 6.0 m).

        Returns
        -------
        PipeSegmentation
            A new, empty segmentation recorder bound to *self*.

        Example
        -------
        ::

            seg = model.segmentation(seg_length_m=10.0)

            for step, mult in enumerate(demand_mults):
                net.solve()
                model.step(timestep, input_sol)
                seg.record_step(net, species='Ca', units='mg',
                                time_s=(step + 1) * timestep, step=step + 1)

            df_ts = seg.to_dataframe()   # full time-series DataFrame
        """
        return PipeSegmentation(self, seg_length_m=seg_length_m)

    def segment_pipe(
        self,
        pipe: Any,
        species: str,
        units: str = 'mg',
        seg_length_m: float = 6.0,
    ) -> List[Dict]:
        """
        Compute concentration for every fixed-length segment of one pipe.

        Convenience wrapper around :class:`PipeSegmentation` for one-off
        queries without needing to instantiate the helper explicitly.

        Parameters
        ----------
        pipe : epynet pipe object
            Must expose ``.uid`` and ``.length``.
        species : str
            Chemical element / species name (e.g. ``'Ca'``).
        units : str
            Concentration units (e.g. ``'mg'``, ``'mmol'``).
        seg_length_m : float
            Physical segment length in metres (default 6.0 m).

        Returns
        -------
        list of dict
            See :meth:`PipeSegmentation.segment_pipe` for the full schema.
        """
        return PipeSegmentation(self, seg_length_m).segment_pipe(pipe, species, units)

    def segment_network(
        self,
        network: Any,
        species: str,
        units: str = 'mg',
        seg_length_m: float = 6.0,
    ) -> 'pd.DataFrame':
        """
        Segment all pipes in *network* and return a tidy DataFrame.

        Convenience wrapper around :class:`PipeSegmentation` for one-off
        snapshots of the entire network at the current simulation state.

        Parameters
        ----------
        network : epynet Network
            Used to iterate over ``network.pipes``.
        species : str
            Chemical element / species name.
        units : str
            Concentration units.
        seg_length_m : float
            Physical segment length in metres (default 6.0 m).

        Returns
        -------
        pandas.DataFrame
            Columns: ``pipe``, ``seg_id``, ``x_start_m``, ``x_end_m``,
            ``x_mid_m``, ``length_m``, ``conc``, ``n_parcels``.
        """
        return PipeSegmentation(self, seg_length_m).segment_network(network, species, units)
