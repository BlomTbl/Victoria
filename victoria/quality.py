"""
Quality module for calculating water quality at nodes and in pipes.
This module handles mixing of PHREEQC solutions and retrieval of concentration and property values.
"""

from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class Quality:
    """
    Quality calculator for water chemistry in the network.
    Calculates concentrations and properties by mixing PHREEQC solutions.
    """

    def __init__(self, pp: Any, models: Any):
        """
        Initialize quality calculator.
        Args:
            pp: PhreeqPython instance
            models: Models instance containing network components
        """
        self.pp = pp
        self.models = models

    def get_parcels(self, link: Any) -> List[Dict[str, Any]]:
        """
        Get all parcels currently in a pipe.
        Args:
            link: Pipe link object
        Returns:
            List of parcel dictionaries
        """
        link_model = self.models.pipes.get(link.uid)
        return link_model.state if link_model else []

    def get_conc_node(self, node: Any, element: str, units: str = 'mmol') -> float:
        """
        Calculate instantaneous concentration at node exit.
        Args:
            node: Node object
            element: Chemical element/species name
            units: Concentration units (default: 'mmol')
        Returns:
            Concentration value
        """
        return self._get_conc_node_internal(node, element, units, avg=False)

    def get_conc_node_avg(self, node: Any, element: str, units: str = 'mmol') -> float:
        """
        Calculate time-averaged concentration at node exit.
        Args:
            node: Node object
            element: Chemical element/species name
            units: Concentration units (default: 'mmol')
        Returns:
            Time-averaged concentration value
        """
        return self._get_conc_node_internal(node, element, units, avg=True)

    def _get_conc_node_internal(self, node: Any, element: str, units: str, avg: bool) -> float:
        """
        Shared logic for getting node concentration (instantaneous or averaged).
        """
        node_model = self.models.nodes.get(node.uid)
        mixed_parcels = getattr(node_model, 'mixed_parcels', None)
        if not node_model or not mixed_parcels:
            return 0.0

        if not avg:
            parcel = mixed_parcels[0]
            return self._calculate_concentration(parcel['q'], element, units)
        
        mixture = 0.0
        for parcel in mixed_parcels:
            conc = self._calculate_concentration(parcel['q'], element, units)
            fraction = parcel['x1'] - parcel['x0']
            mixture += conc * fraction
        return mixture

    def get_mixture_node(self, node: Any) -> Dict[int, float]:
        """
        Get solution mixture fractions at node exit (instantaneous).
        Args:
            node: Node object
        Returns:
            Dictionary mapping solution numbers to fractions
        """
        node_model = self.models.nodes.get(node.uid)
        mixed_parcels = getattr(node_model, 'mixed_parcels', None)
        if not node_model or not mixed_parcels:
            return {}
        return mixed_parcels[0]['q']

    def get_mixture_node_avg(self, node: Any) -> Dict[int, float]:
        """
        Get time-averaged solution mixture fractions at node exit.
        Args:
            node: Node object
        Returns:
            Dictionary mapping solution numbers to averaged fractions
        """
        node_model = self.models.nodes.get(node.uid)
        mixed_parcels = getattr(node_model, 'mixed_parcels', None)
        if not node_model or not mixed_parcels:
            return {}

        average_dict = {}
        for parcel in mixed_parcels:
            frac = parcel['x1'] - parcel['x0']
            for sol_num, sol_frac in parcel['q'].items():
                average_dict[sol_num] = average_dict.get(sol_num, 0.0) + sol_frac * frac
        return average_dict

    def get_conc_pipe(self, link: Any, element: str, units: str = 'mmol') -> List[Dict[str, Any]]:
        """
        Get concentration profile along a pipe.
        Args:
            link: Pipe link object
            element: Chemical element/species name
            units: Concentration units (default: 'mmol')
        Returns:
            List of parcels with concentration values
        """
        link_model = self.models.links.get(link.uid)
        state = getattr(link_model, 'state', None)
        if not link_model or not state:
            return []

        return [
            {
                'x0': parcel['x0'],
                'x1': parcel['x1'],
                'q': self._calculate_concentration(parcel['q'], element, units)
            }
            for parcel in state
        ]

    def get_conc_pipe_avg(self, link: Any, element: str, units: str = 'mmol') -> float:
        """
        Calculate volume-averaged concentration in a pipe.
        Args:
            link: Pipe link object
            element: Chemical element/species name
            units: Concentration units (default: 'mmol')
        Returns:
            Volume-averaged concentration
        """
        link_model = self.models.pipes.get(link.uid)
        state = getattr(link_model, 'state', None)
        if not link_model or not state:
            return 0.0

        average_conc = 0.0
        for parcel in state:
            conc = self._calculate_concentration(parcel['q'], element, units)
            vol_frac = parcel['x1'] - parcel['x0']
            average_conc += conc * vol_frac
        return average_conc

    def get_properties_node(self, node: Any) -> List[float]:
        """
        Get water properties at node exit (instantaneous).
        Args:
            node: Node object
        Returns:
            List of [pH, specific conductivity, temperature]
        """
        return self._get_properties_node_internal(node, avg=False)

    def get_properties_node_avg(self, node: Any) -> List[float]:
        """
        Get time-averaged water properties at node exit.
        Args:
            node: Node object
        Returns:
            List of [pH, specific conductivity, temperature]
        """
        return self._get_properties_node_internal(node, avg=True)

    def _get_properties_node_internal(self, node: Any, avg: bool) -> List[float]:
        """
        Shared logic for retrieving node properties (instantaneous or averaged).
        """
        node_model = self.models.nodes.get(node.uid)
        mixed_parcels = getattr(node_model, 'mixed_parcels', None)
        if not node_model or not mixed_parcels:
            return [0.0, 0.0, 0.0]

        if not avg:
            parcel = mixed_parcels[0]
            mixture = self._mix_phreeqc_solutions(parcel['q'])
            if mixture:
                return [getattr(mixture, 'pH', 0.0), getattr(mixture, 'sc', 0.0), getattr(mixture, 'temperature', 0.0)]
            return [0.0, 0.0, 0.0]

        temp = [0.0, 0.0, 0.0]
        for parcel in mixed_parcels:
            mixture = self._mix_phreeqc_solutions(parcel['q'])
            if mixture:
                frac = parcel['x1'] - parcel['x0']
                temp[0] += frac * getattr(mixture, 'pH', 0.0)
                temp[1] += frac * getattr(mixture, 'sc', 0.0)
                temp[2] += frac * getattr(mixture, 'temperature', 0.0)
        return temp

    def _calculate_concentration(self, solution_dict: Dict[int, float], element: str, units: str) -> float:
        """
        Calculate concentration from solution mixture.
        Args:
            solution_dict: Dictionary of solution numbers and fractions
            element: Chemical element/species name
            units: Concentration units
        Returns:
            Calculated concentration
        """
        mixture = self._mix_phreeqc_solutions(solution_dict)
        if mixture:
            try:
                return mixture.total(element, units)
            except Exception as e:
                logger.warning(f"Error calculating {element}: {e}")
        return 0.0

    def _mix_phreeqc_solutions(self, solution_dict: Dict[int, float]) -> Optional[Any]:
        """
        Mix PHREEQC solutions according to fractions.
        Args:
            solution_dict: Dictionary of solution numbers and fractions
        Returns:
            Mixed PHREEQC solution or None
        """
        if not solution_dict:
            return None
        try:
            available_solutions = set(self.pp.get_solution_list())
            mix_temp = {}
            for sol_num, frac in solution_dict.items():
                if sol_num not in available_solutions:
                    logger.warning(f"Solution {sol_num} not found in PHREEQC, skipping")
                    continue
                phreeqc_sol = self.pp.get_solution(sol_num)
                if phreeqc_sol:
                    mix_temp[phreeqc_sol] = frac
            if mix_temp:
                return self.pp.mix_solutions(mix_temp)
            else:
                logger.warning(f"No valid solutions found to mix from {solution_dict}")
                return None
        except Exception as e:
            # PHREEQC oxygen mass convergence warnings are non-fatal and occur
            # frequently when mixing solutions with near-zero dissolved oxygen.
            # Log at DEBUG level to avoid flooding output; simulation results
            # are unaffected as this only applies to post-processing queries.
            err_str = str(e)
            if "oxygen" in err_str.lower() or "converged" in err_str.lower():
                logger.debug(f"PHREEQC oxygen convergence issue (non-fatal, returning None): {e}")
            else:
                logger.error(f"Error mixing PHREEQC solutions: {e}")
            return None
