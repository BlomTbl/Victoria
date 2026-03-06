"""
Victoria — Water Quality Simulator for hydraulic networks.
Main module providing the high-level API for water quality simulation
using PHREEQC chemistry with EPyNet hydraulic networks.

Changes compared to v1:
  - step(): calls _ensure_adjacency() if _build_adjacency has not yet
    been executed for the current hydraulic step. This means the user
    does not strictly need to call check_flow_direction() before step().
  - fill_network(): uses solver.filled_links directly as a set (was
    conversion from list to set).
  - fill_network(): passes fill_timestep to solver.fill_network() so
    the hardcoded 60 s no longer silently gives wrong results.
  - garbage_collect(): calls quality.invalidate_mix_cache() so that
    removed PHREEQC solutions no longer surface as cache hits.
  - Internal methods for check_flow_direction documented.
"""

from __future__ import annotations

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

    Combines hydraulic network simulation (EPyNet) with water chemistry
    simulation (PHREEQC) to track water quality through distribution
    networks.

    Usage pattern
    -------------
    1. Load and solve the network hydraulically via EPyNet.
    2. Create a Victoria instance.
    3. Call fill_network() once.
    4. Optionally call check_flow_direction() each time step (recommended
       for networks with variable pump schedules), then call step().
    5. Use the get_* methods to query water quality.
    """

    def __init__(self, network: Any, pp: Any):
        """
        Initialise the Victoria simulator.

        Args:
            network: EPyNet network object (hydraulically solved).
            pp:      PhreeqPython instance for chemistry calculations.
        """
        self.net     = network
        self.pp      = pp
        self.models  = Models(network)
        self.solver  = Solver(self.models, network)
        self.quality = Quality(pp, self.models)
        self.output:  List = []

        # Track whether adjacency has been built for the current
        # hydraulic state — prevents stale BFS in step().
        self._adjacency_built: bool = False

        logger.info("Victoria simulator initialized")

    # ── Simulation step ───────────────────────────────────────────────────────

    def step(self, timestep: float, input_sol: Dict) -> None:
        """
        Simulate one time step of water quality evolution.
        Must be called after the hydraulic simulation for that time step.

        If check_flow_direction() has not been called for the current
        hydraulic state, adjacency is built internally as a safety net.
        It is still recommended to call check_flow_direction() explicitly
        whenever flow directions may change.

        Args:
            timestep:  Time step duration in seconds (must be positive).
            input_sol: Dict mapping node uid to PHREEQC solution.
        """
        if timestep <= 0:
            raise ValueError(f"Timestep must be positive, got {timestep}")

        self._ensure_adjacency()
        logger.debug("Running quality step for timestep=%ss", timestep)

        for reservoir in self.net.reservoirs:
            self._run_safe_trace(reservoir, timestep, input_sol)

        self.solver.reset_ready_state()
        self._adjacency_built = False   # Mark as stale for the next step

    def _ensure_adjacency(self) -> None:
        """Build adjacency if it has not yet been built for the current hydraulic step."""
        if not self._adjacency_built:
            logger.debug(
                "step() called without prior check_flow_direction(); "
                "building adjacency now."
            )
            if hasattr(self.solver, '_build_adjacency'):
                self.solver._build_adjacency()
            self._adjacency_built = True

    def _run_safe_trace(self, emitter: Any, timestep: float, input_sol: Dict) -> None:
        try:
            self.solver.run_trace(emitter, timestep, input_sol)
        except Exception as e:
            logger.error("Error tracing from reservoir %s: %s", emitter.uid, e)
            raise

    # ── Network initialisation ────────────────────────────────────────────────

    def fill_network(self, input_sol: Dict, from_reservoir: bool = True,
                     fill_timestep: float = 3600.0) -> None:
        """
        Initialise the network with starting water quality.
        Call once before the simulation loop.

        Args:
            input_sol:      Dict mapping node uid to PHREEQC solution.
            from_reservoir: If True, fill from reservoirs; otherwise use
                            the default solution for all pipes.
            fill_timestep:  Time step (seconds) for fill volume calculations.
                            Default 3600 s. Adjust if the hydraulic time step
                            differs significantly.
        """
        logger.info("Filling network with initial solutions")

        if hasattr(self.solver, '_build_adjacency'):
            self.solver._build_adjacency()
            self._adjacency_built = True

        def _get_default_solution(sol_dict: Dict) -> Dict[int, float]:
            candidate = sol_dict.get(0, None)
            if candidate is None:
                for v in sol_dict.values():
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
                    self.solver.fill_network(emitter, input_sol,
                                             fill_timestep=fill_timestep)
                except KeyError:
                    logger.error("No solution defined for reservoir %s", emitter.uid)
                    raise

            # Fill any remaining pipes with the default solution
            link_uids     = {link.uid for link in self.net.links}
            filled_uids   = self.solver.filled_links          # al een set
            unfilled_uids = link_uids - filled_uids

            if unfilled_uids:
                logger.info(
                    "Filling %d unfilled links with default solution",
                    len(unfilled_uids),
                )
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

    # ── Flow direction check ──────────────────────────────────────────────────

    def check_flow_direction(self) -> None:
        """
        Check for flow reversals and update parcel positions.
        Call after each hydraulic time step where flow reversals are possible.

        Also builds the adjacency caches (upstream/downstream per node) so
        that run_trace and check_connections avoid repeated ctypes calls.
        """
        if hasattr(self.solver, '_build_adjacency'):
            self.solver._build_adjacency()
        self.solver.check_connections()
        self._adjacency_built = True

    # ── Memory cleanup ────────────────────────────────────────────────────────

    def garbage_collect(self, input_sol: Optional[Dict] = None,
                        preserve: Optional[Set[int]] = None) -> None:
        """
        Remove unused PHREEQC solutions from memory.
        Call periodically to prevent memory buildup from unused solution objects.

        Also clears the PHREEQC mixture cache in Quality so that removed
        solutions no longer surface as cache hits.

        Args:
            input_sol: Dict of input solutions to preserve (optional).
            preserve:  Extra set of PHREEQC solution numbers to always keep
                       (e.g. persistent end-members).
        """
        registered_solutions: Set[int] = set()

        def _collect_from_parcels(parcel_list: list) -> None:
            for parcel in parcel_list:
                registered_solutions.update(parcel.get('q', {}).keys())

        # Pipes
        for pipe in self.solver.models.pipes.values():
            if hasattr(pipe, 'state'):
                _collect_from_parcels(pipe.state)
            if hasattr(pipe, 'output_state'):
                _collect_from_parcels(pipe.output_state)

        # All links (pumps, valves)
        for link in self.solver.models.links.values():
            if hasattr(link, 'output_state'):
                _collect_from_parcels(link.output_state)

        # Tanks
        for tank in self.solver.models.tanks.values():
            if hasattr(tank, 'state'):
                _collect_from_parcels(tank.state)
            if getattr(tank, 'mixture', None) and isinstance(tank.mixture, dict):
                registered_solutions.update(tank.mixture.keys())

        # Node output
        for node in self.solver.models.nodes.values():
            if hasattr(node, 'mixed_parcels'):
                _collect_from_parcels(node.mixed_parcels)
            for slot in getattr(node, 'outflow', []):
                for v, q in slot:
                    registered_solutions.update(q.keys())

        # Preserve all solution objects from input_sol
        if input_sol:
            for sol in input_sol.values():
                if hasattr(sol, 'number'):
                    registered_solutions.add(sol.number)

        # Preserve explicitly specified numbers
        if preserve:
            registered_solutions.update(preserve)

        phreeqc_solutions = set(self.pp.get_solution_list())
        to_forget         = phreeqc_solutions - registered_solutions
        if to_forget:
            logger.info("Removing %d unused PHREEQC solutions", len(to_forget))
            self.pp.remove_solutions(to_forget)
            # Clear the PHREEQC mixture cache — stale entries are now invalid
            self.quality.invalidate_mix_cache()

    # ── Quality queries ───────────────────────────────────────────────────────

    def get_conc_node(self, node: Any, element: str, units: str = 'mmol') -> float:
        """Return instantaneous concentration at the node outlet."""
        return self.quality.get_conc_node(node, element, units)

    def get_conc_node_avg(self, node: Any, element: str, units: str = 'mmol') -> float:
        """Return time-averaged concentration at the node outlet."""
        return self.quality.get_conc_node_avg(node, element, units)

    def get_mixture_node(self, node: Any) -> Dict[int, float]:
        """Return instantaneous solution mixture at the node outlet."""
        return self.quality.get_mixture_node(node)

    def get_mixture_node_avg(self, node: Any) -> Dict[int, float]:
        """Return time-averaged solution mixture at the node outlet."""
        return self.quality.get_mixture_node_avg(node)

    def get_conc_pipe(self, link: Any, element: str, units: str = 'mmol') -> List[Dict]:
        """Return concentration profile along a pipe."""
        return self.quality.get_conc_pipe(link, element, units)

    def get_conc_pipe_avg(self, link: Any, element: str, units: str = 'mmol') -> float:
        """Return volume-averaged concentration in a pipe."""
        return self.quality.get_conc_pipe_avg(link, element, units)

    def get_parcels(self, link: Any) -> List[Dict]:
        """Return all parcels in a pipe."""
        return self.quality.get_parcels(link)

    def get_properties_node(self, node: Any) -> List[float]:
        """Return instantaneous water properties at the node outlet."""
        return self.quality.get_properties_node(node)

    def get_properties_node_avg(self, node: Any) -> List[float]:
        """Return time-averaged water properties at the node outlet."""
        return self.quality.get_properties_node_avg(node)

    # ── Pipe segmentation ────────────────────────────────────────────────────

    def segmentation(self, seg_length_m: float = 6.0) -> PipeSegmentation:
        """
        Create a PipeSegmentation helper bound to this Victoria instance.

        Parameters
        ----------
        seg_length_m : float
            Physical segment length in metres (default 6.0 m).

        Returns
        -------
        PipeSegmentation
            A new, empty segmentation recorder bound to *self*.
        """
        return PipeSegmentation(self, seg_length_m=seg_length_m)

    def segment_pipe(self, pipe: Any, species: str, units: str = 'mg',
                     seg_length_m: float = 6.0) -> List[Dict]:
        """
        Compute concentration for every fixed-length segment of one pipe.

        Convenience wrapper around PipeSegmentation for one-off queries.
        """
        return PipeSegmentation(self, seg_length_m).segment_pipe(pipe, species, units)

    def segment_network(self, network: Any, species: str, units: str = 'mg',
                        seg_length_m: float = 6.0) -> 'pd.DataFrame':
        """
        Segment all pipes in *network* and return a tidy DataFrame.

        Convenience wrapper around PipeSegmentation for one-off snapshots.
        """
        return PipeSegmentation(self, seg_length_m).segment_network(network, species, units)
