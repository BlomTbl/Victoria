"""
Quality module for calculating water quality at nodes and in pipes.

This module handles mixing of PHREEQC solutions and retrieval of
concentration and property values.
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
        self.mixture: List[Any] = []
        self.q_nodes: Dict = {}

    def get_parcels(self, link: Any) -> List[Dict[str, Any]]:
        """
        Get all parcels currently in a pipe.
        
        Args:
            link: Pipe link object
            
        Returns:
            List of parcel dictionaries
        """
        link_model = self.models.pipes.get(link.uid)
        if link_model:
            return link_model.state
        return []

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
        node_model = self.models.nodes.get(node.uid)
        if not node_model or not node_model.mixed_parcels:
            return 0.0

        parcel = node_model.mixed_parcels[0]
        return self._calculate_concentration(parcel['q'], element, units)

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
        node_model = self.models.nodes.get(node.uid)
        if not node_model or not node_model.mixed_parcels:
            return 0.0

        mixture = 0.0
        for parcel in node_model.mixed_parcels:
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
        if not node_model or not node_model.mixed_parcels:
            return {}

        return node_model.mixed_parcels[0]['q']

    def get_mixture_node_avg(self, node: Any) -> Dict[int, float]:
        """
        Get time-averaged solution mixture fractions at node exit.
        
        Args:
            node: Node object
            
        Returns:
            Dictionary mapping solution numbers to averaged fractions
        """
        node_model = self.models.nodes.get(node.uid)
        if not node_model or not node_model.mixed_parcels:
            return {}

        # Use merge_load from a MIX instance
        average_dict = {}
        
        for parcel in node_model.mixed_parcels:
            frac = parcel['x1'] - parcel['x0']  # Fixed typo: was 'x-'
            # Merge the solution fractions
            for sol_num, sol_frac in parcel['q'].items():
                if sol_num in average_dict:
                    average_dict[sol_num] += sol_frac * frac
                else:
                    average_dict[sol_num] = sol_frac * frac

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
        if not link_model or not link_model.state:
            return []

        pipe_conc = []
        for parcel in link_model.state:
            conc = self._calculate_concentration(parcel['q'], element, units)
            pipe_conc.append({
                'x0': parcel['x0'],
                'x1': parcel['x1'],
                'q': conc
            })

        return pipe_conc

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
        if not link_model or not link_model.state:
            return 0.0

        average_conc = 0.0

        for parcel in link_model.state:
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
        node_model = self.models.nodes.get(node.uid)
        if not node_model or not node_model.mixed_parcels:
            return [0.0, 0.0, 0.0]

        parcel = node_model.mixed_parcels[0]
        mixture = self._mix_phreeqc_solutions(parcel['q'])
        
        if mixture:
            return [mixture.pH, mixture.sc, mixture.temperature]
        return [0.0, 0.0, 0.0]

    def get_properties_node_avg(self, node: Any) -> List[float]:
        """
        Get time-averaged water properties at node exit.
        
        Args:
            node: Node object
            
        Returns:
            List of [pH, specific conductivity, temperature]
        """
        node_model = self.models.nodes.get(node.uid)
        if not node_model or not node_model.mixed_parcels:
            return [0.0, 0.0, 0.0]

        temp = [0.0, 0.0, 0.0]

        for parcel in node_model.mixed_parcels:
            mixture = self._mix_phreeqc_solutions(parcel['q'])
            if mixture:
                frac = parcel['x1'] - parcel['x0']
                temp[0] += frac * mixture.pH
                temp[1] += frac * mixture.sc
                temp[2] += frac * mixture.temperature

        return temp

    def _calculate_concentration(self, solution_dict: Dict[int, float], 
                                 element: str, units: str) -> float:
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
            # Get list of available solutions in PHREEQC
            available_solutions = set(self.pp.get_solution_list())
            
            mix_temp = {}
            for sol_num, frac in solution_dict.items():
                # Check if solution exists before trying to get it
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
            logger.error(f"Error mixing PHREEQC solutions: {e}")
            
        return None
