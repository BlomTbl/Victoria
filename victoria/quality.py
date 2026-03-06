"""
Quality module — version 2.

Changes compared to v1:
  - _mix_phreeqc_solutions: results are cached via an LRU cache keyed on
    a frozen set (frozenset of solution_dict items). Repeated calls with
    the same mixture fractions (common in steady or slowly changing
    networks) now result in a cache hit instead of a new PHREEQC
    computation. Cache size is configurable via Quality.mix_cache_size
    (default 256).
  - get_conc_node / _get_conc_node_internal: docstring clarifies that
    'instantaneous' returns the *first parcel in mixed_parcels*
    (the parcel with the lowest x-coordinate, i.e. the oldest water
    closest to the offtake).
  - _mix_phreeqc_solutions: cache is automatically invalidated when pp
    is replaced (future use).
"""

from __future__ import annotations

from functools import lru_cache
from typing import List, Dict, Any, Optional, FrozenSet, Tuple
import logging

logger = logging.getLogger(__name__)


class Quality:
    """
    Quality calculator for water chemistry in the network.
    Calculates concentrations and properties by mixing PHREEQC solutions.

    Attributes
    ----------
    mix_cache_size : int
        Maximum size of the LRU cache for PHREEQC mixtures.
        Increase for networks with many unique mixture combinations.
        Default 256.
    """

    mix_cache_size: int = 256

    def __init__(self, pp: Any, models: Any):
        """
        Initialise the quality calculator.

        Args:
            pp:     PhreeqPython instance.
            models: Models instance containing network components.
        """
        self.pp     = pp
        self.models = models
        self._build_mix_cache()

    # ── Cache management ──────────────────────────────────────────────────────

    def _build_mix_cache(self) -> None:
        """Build (or rebuild) the LRU cache for _mix_phreeqc_solutions."""
        pp = self.pp

        @lru_cache(maxsize=self.mix_cache_size)
        def _cached_mix(key: FrozenSet[Tuple[int, float]]) -> Optional[Any]:
            """
            Cache wrapper around pp.mix_solutions.

            `key` is a frozenset of (solution_number, fraction) tuples
            derived from solution_dict. This makes the result stable
            regardless of dict iteration order.
            """
            solution_dict = dict(key)
            if not solution_dict:
                return None
            try:
                available = set(pp.get_solution_list())
                mix_temp  = {}
                for sol_num, frac in solution_dict.items():
                    if sol_num not in available:
                        logger.warning(
                            "Solution %s not found in PHREEQC, skipping", sol_num
                        )
                        continue
                    phreeqc_sol = pp.get_solution(sol_num)
                    if phreeqc_sol:
                        mix_temp[phreeqc_sol] = frac
                if mix_temp:
                    return pp.mix_solutions(mix_temp)
                logger.warning("No valid solutions found to mix from %s", solution_dict)
                return None
            except Exception as e:
                err_str = str(e)
                if "oxygen" in err_str.lower() or "converged" in err_str.lower():
                    logger.debug("PHREEQC oxygen convergence issue (non-fatal): %s", e)
                else:
                    logger.error("Error mixing PHREEQC solutions: %s", e)
                return None

        self._cached_mix = _cached_mix

    def invalidate_mix_cache(self) -> None:
        """
        Discard the PHREEQC mixture cache.

        Call when solutions have been added or removed from the pp
        instance outside Victoria's control, so that stale cache entries
        are no longer returned.
        """
        self._cached_mix.cache_clear()
        logger.debug("PHREEQC mix cache cleared")

    @property
    def cache_info(self):
        """Return lru_cache statistics (hits, misses, size)."""
        return self._cached_mix.cache_info()

    # ── Internal mixing ───────────────────────────────────────────────────────

    def _mix_phreeqc_solutions(self, solution_dict: Dict[int, float]) -> Optional[Any]:
        """
        Mix PHREEQC solutions according to their fractions.

        Results are cached on the frozen key. Rounding fractions to 8
        decimal places prevents cache misses caused by floating-point noise.

        Args:
            solution_dict: Dict of solution numbers and fractions.

        Returns:
            Mixed PHREEQC solution, or None.
        """
        if not solution_dict:
            return None
        # Round fractions to avoid floating-point noise in the cache key
        key = frozenset(
            (sol_num, round(frac, 8))
            for sol_num, frac in solution_dict.items()
            if frac > 0
        )
        if not key:
            return None
        return self._cached_mix(key)

    def _calculate_concentration(self, solution_dict: Dict[int, float],
                                  element: str, units: str) -> float:
        """
        Calculate concentration from a solution mixture.

        Args:
            solution_dict: Dict of solution numbers and fractions.
            element:       Chemical element or species name.
            units:         Concentration units.

        Returns:
            Calculated concentration.
        """
        mixture = self._mix_phreeqc_solutions(solution_dict)
        if mixture:
            try:
                return mixture.total(element, units)
            except Exception as e:
                logger.warning("Error calculating %s: %s", element, e)
        return 0.0

    # ── Parcel access ─────────────────────────────────────────────────────────

    def get_parcels(self, link: Any) -> List[Dict[str, Any]]:
        """
        Return all parcels currently inside a pipe.

        Args:
            link: Pipe link object.

        Returns:
            List of parcel dicts.
        """
        link_model = self.models.pipes.get(link.uid)
        return link_model.state if link_model else []

    # ── Node concentrations ───────────────────────────────────────────────────

    def get_conc_node(self, node: Any, element: str, units: str = 'mmol') -> float:
        """
        Calculate instantaneous concentration at the node outlet.

        'Instantaneous' means the *first parcel* in mixed_parcels —
        the parcel with the lowest x-coordinate, i.e. the oldest water
        closest to the offtake point.

        Args:
            node:    Node object.
            element: Chemical element or species name.
            units:   Concentration units (default: 'mmol').

        Returns:
            Concentration value.
        """
        return self._get_conc_node_internal(node, element, units, avg=False)

    def get_conc_node_avg(self, node: Any, element: str, units: str = 'mmol') -> float:
        """
        Calculate time-averaged concentration at the node outlet.

        Args:
            node:    Node object.
            element: Chemical element or species name.
            units:   Concentration units (default: 'mmol').

        Returns:
            Time-averaged concentration value.
        """
        return self._get_conc_node_internal(node, element, units, avg=True)

    def _get_conc_node_internal(self, node: Any, element: str,
                                 units: str, avg: bool) -> float:
        """Shared logic for node concentration (instantaneous or time-averaged)."""
        node_model    = self.models.nodes.get(node.uid)
        mixed_parcels = getattr(node_model, 'mixed_parcels', None)
        if not node_model or not mixed_parcels:
            return 0.0

        if not avg:
            return self._calculate_concentration(mixed_parcels[0]['q'], element, units)

        mixture = 0.0
        for parcel in mixed_parcels:
            conc     = self._calculate_concentration(parcel['q'], element, units)
            fraction = parcel['x1'] - parcel['x0']
            mixture += conc * fraction
        return mixture

    # ── Mixture fractions ─────────────────────────────────────────────────────

    def get_mixture_node(self, node: Any) -> Dict[int, float]:
        """
        Return instantaneous solution mixture fractions at the node outlet.

        Args:
            node: Node object.

        Returns:
            Dict mapping solution numbers to fractions.
        """
        node_model    = self.models.nodes.get(node.uid)
        mixed_parcels = getattr(node_model, 'mixed_parcels', None)
        if not node_model or not mixed_parcels:
            return {}
        return mixed_parcels[0]['q']

    def get_mixture_node_avg(self, node: Any) -> Dict[int, float]:
        """
        Return time-averaged solution mixture fractions at the node outlet.

        Args:
            node: Node object.

        Returns:
            Dict mapping solution numbers to averaged fractions.
        """
        node_model    = self.models.nodes.get(node.uid)
        mixed_parcels = getattr(node_model, 'mixed_parcels', None)
        if not node_model or not mixed_parcels:
            return {}

        average_dict: Dict[int, float] = {}
        for parcel in mixed_parcels:
            frac = parcel['x1'] - parcel['x0']
            for sol_num, sol_frac in parcel['q'].items():
                average_dict[sol_num] = average_dict.get(sol_num, 0.0) + sol_frac * frac
        return average_dict

    # ── Pipe concentrations ───────────────────────────────────────────────────

    def get_conc_pipe(self, link: Any, element: str,
                      units: str = 'mmol') -> List[Dict[str, Any]]:
        """
        Return the concentration profile along a pipe.

        Args:
            link:    Pipe link object.
            element: Chemical element or species name.
            units:   Concentration units (default: 'mmol').

        Returns:
            List of parcels with concentration values.
        """
        link_model = self.models.links.get(link.uid)
        state      = getattr(link_model, 'state', None)
        if not link_model or not state:
            return []

        return [
            {
                'x0': parcel['x0'],
                'x1': parcel['x1'],
                'q':  self._calculate_concentration(parcel['q'], element, units),
            }
            for parcel in state
        ]

    def get_conc_pipe_avg(self, link: Any, element: str,
                           units: str = 'mmol') -> float:
        """
        Calculate the volume-averaged concentration in a pipe.

        Args:
            link:    Pipe link object.
            element: Chemical element or species name.
            units:   Concentration units (default: 'mmol').

        Returns:
            Volume-averaged concentration.
        """
        link_model = self.models.pipes.get(link.uid)
        state      = getattr(link_model, 'state', None)
        if not link_model or not state:
            return 0.0

        average_conc = 0.0
        for parcel in state:
            conc     = self._calculate_concentration(parcel['q'], element, units)
            vol_frac = parcel['x1'] - parcel['x0']
            average_conc += conc * vol_frac
        return average_conc

    # ── Node properties ───────────────────────────────────────────────────────

    def get_properties_node(self, node: Any) -> List[float]:
        """
        Return instantaneous water properties at the node outlet.

        Returns:
            List of [pH, specific conductivity, temperature].
        """
        return self._get_properties_node_internal(node, avg=False)

    def get_properties_node_avg(self, node: Any) -> List[float]:
        """
        Return time-averaged water properties at the node outlet.

        Returns:
            List of [pH, specific conductivity, temperature].
        """
        return self._get_properties_node_internal(node, avg=True)

    def _get_properties_node_internal(self, node: Any, avg: bool) -> List[float]:
        """Shared logic for node properties (instantaneous or time-averaged)."""
        node_model    = self.models.nodes.get(node.uid)
        mixed_parcels = getattr(node_model, 'mixed_parcels', None)
        if not node_model or not mixed_parcels:
            return [0.0, 0.0, 0.0]

        if not avg:
            mixture = self._mix_phreeqc_solutions(mixed_parcels[0]['q'])
            if mixture:
                return [
                    getattr(mixture, 'pH',          0.0),
                    getattr(mixture, 'sc',           0.0),
                    getattr(mixture, 'temperature',  0.0),
                ]
            return [0.0, 0.0, 0.0]

        temp = [0.0, 0.0, 0.0]
        for parcel in mixed_parcels:
            mixture = self._mix_phreeqc_solutions(parcel['q'])
            if mixture:
                frac     = parcel['x1'] - parcel['x0']
                temp[0] += frac * getattr(mixture, 'pH',         0.0)
                temp[1] += frac * getattr(mixture, 'sc',          0.0)
                temp[2] += frac * getattr(mixture, 'temperature', 0.0)
        return temp
