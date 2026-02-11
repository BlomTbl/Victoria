"""
MIX module for mixing water parcels at nodes.

This module implements various mixing strategies for different node types
in a hydraulic network (junctions, reservoirs, tanks).
"""
from typing import List, Dict, Any, Optional
from math import exp
import logging

logger = logging.getLogger(__name__)


def _get_links(node: Any, direction: str) -> list:
    """
    Get upstream or downstream links, handling both EPyNet API styles.
    
    Some EPyNet versions have upstream_links/downstream_links as methods,
    others as properties. This handles both.
    
    Args:
        node: Node object
        direction: 'upstream' or 'downstream'
        
    Returns:
        List of links
    """
    attr = f'{direction}_links'
    links = getattr(node, attr, [])
    return links() if callable(links) else links


class MIX:
    """Base class for mixing parcels at nodes."""
    
    def __init__(self):
        self.sorted_parcels: List[Dict[str, Any]] = []
        self.outflow: List[List[List[Any]]] = []
        self.mixed_parcels: List[Dict[str, Any]] = []

    @staticmethod
    def merge_load(dict1: Dict, dict2: Dict, volume: float) -> Dict:
        """
        Merge two solution dictionaries with volume weighting.
        
        Args:
            dict1: First solution dictionary
            dict2: Second solution dictionary to add
            volume: Volume fraction of dict2
            
        Returns:
            Merged solution dictionary
        """
        dict3 = dict1.copy()

        for key, value in dict2.items():
            if key in dict3:
                dict3[key] = dict3[key] + value * volume
            else:
                dict3[key] = value * volume
                
        return dict3

    def parcels_out(self, flows_out: List[float]) -> None:
        """
        Distribute mixed parcels to outgoing links based on flow rates.
        
        Args:
            flows_out: List of outflow rates
        """
        self.outflow = []
        total_flow = sum(flows_out)
        
        if total_flow <= 1E-7:
            return

        for flow in flows_out:
            temp = []
            for parcel in self.mixed_parcels:
                parcel_volume = (
                    (parcel['x1'] - parcel['x0']) * 
                    flow / total_flow * 
                    parcel['volume']
                )
                parcel_volume = round(parcel_volume, 6)
                temp.append([parcel_volume, parcel['q']])
            self.outflow.append(temp)


class Junction(MIX):
    """Junction node with ideal mixing."""
    
    def mix(self, inflow: List[Dict[str, Any]], node: Any, 
            timestep: float, input_sol: Any) -> None:
        """
        Mix parcels at junction with demand consideration.
        
        Args:
            inflow: List of incoming parcels
            node: Junction node object
            timestep: Simulation timestep in seconds
            input_sol: Input solutions (not used for junctions)
        """
        self.mixed_parcels = []
        
        if not inflow:
            return
            
        demand = round(node.demand / 3600 * timestep, 7)

        # Sort parcels by end position
        self.sorted_parcels = sorted(inflow, key=lambda a: a['x1'])
        
        xcure = 0.0
        
        for parcel1 in self.sorted_parcels:
            if parcel1['x1'] <= xcure:
                continue

            mixture = {}
            total_volume = 0.0
            cell_volume = 0.0
            
            # Find all overlapping parcels
            for parcel2 in self.sorted_parcels:
                if parcel2['x1'] <= xcure or parcel2['x0'] >= parcel1['x1']:
                    continue

                total_volume += parcel2['volume']

                # Calculate overlapping volume
                overlap_fraction = min(parcel1['x1'], parcel2['x1']) - max(xcure, parcel2['x0'])
                rv = overlap_fraction * parcel2['volume']
                
                # Mix solutions
                mixture = self.merge_load(mixture, parcel2['q'], rv)
                cell_volume += rv
            
            # Normalize mixture
            if cell_volume > 0:
                for charge in mixture:
                    mixture[charge] = round(mixture[charge] / cell_volume, 6)
                
                # Subtract demand from total volume
                total_volume = max(0, total_volume - demand)

                self.mixed_parcels.append({
                    'x0': xcure,
                    'x1': parcel1['x1'],
                    'q': mixture,
                    'volume': total_volume
                })

            xcure = parcel1['x1']

        # Use compatibility function for getting links
        flows_out = [abs(link.flow) for link in _get_links(node, 'downstream')]
        self.parcels_out(flows_out)


class Reservoir(MIX):
    """Reservoir node (source of water)."""
    
    def mix(self, inflow: List[Dict[str, Any]], node: Any, 
            timestep: float, input_sol: Dict) -> None:
        """
        Generate outflow from reservoir.
        
        Args:
            inflow: Incoming parcels (ignored for reservoirs)
            node: Reservoir node object
            timestep: Simulation timestep in seconds
            input_sol: Dictionary of input solutions
        """
        self.mixed_parcels = []

        # Create solution mixture for reservoir
        q = {input_sol[node.uid].number: 1.0}
        shift_volume = timestep * node.outflow / 3600

        self.outflow = [[[shift_volume, q]]]

        self.mixed_parcels.append({
            'x0': 0.0,
            'x1': 1.0,
            'q': q,
            'volume': shift_volume
        })


class Tank_CSTR(MIX):
    """
    Continuous Stirred Tank Reactor (CSTR) - ideal mixing.
    
    Assumes instantaneous and complete mixing in the tank.
    """
    
    def __init__(self, initvolume: float):
        """
        Initialize CSTR tank.
        
        Args:
            initvolume: Initial tank volume in m³
        """
        super().__init__()
        self.volume = initvolume
        self.mixture: Dict = {}

    def mix(self, inflow: List[Dict[str, Any]], node: Any, 
            timestep: float, input_sol: Any) -> None:
        """
        Mix inflow with tank contents using CSTR model.
        
        Args:
            inflow: List of incoming parcels
            node: Tank node object
            timestep: Simulation timestep in seconds
            input_sol: Input solutions (not used)
        """
        self.mixed_parcels = []
        
        volume_tank = node.volume
        mixture = {}
        total_volume = 0.0

        # Mix all incoming parcels
        for parcel in inflow:
            rv = (parcel['x1'] - parcel['x0']) * parcel['volume']
            mixture = self.merge_load(mixture, parcel['q'], rv)
            total_volume += rv

        # Normalize inflow mixture
        if total_volume > 0:
            for charge in mixture:
                mixture[charge] = round(mixture[charge] / total_volume, 6)

            # Calculate mixing fraction (exponential decay model)
            if volume_tank > 0:
                frac = 1 - exp(-total_volume / volume_tank)
            else:
                frac = 1.0

            volume_out = node.outflow / 3600 * timestep

            # Mix inflow with existing tank contents
            new_solution = {}
            new_solution = self.merge_load(new_solution, mixture, frac)
            new_solution = self.merge_load(new_solution, self.mixture, 1 - frac)

            # Use average of old and new for outflow
            solution_out = {}
            solution_out = self.merge_load(solution_out, self.mixture, 0.5)
            solution_out = self.merge_load(solution_out, new_solution, 0.5)

            self.mixed_parcels.append({
                'x0': 0.0,
                'x1': 1.0,
                'q': solution_out,
                'volume': volume_out
            })

            self.mixture = new_solution
        else:
            # No inflow, use existing mixture
            volume_out = node.outflow / 3600 * timestep
            if self.mixture:
                self.mixed_parcels.append({
                    'x0': 0.0,
                    'x1': 1.0,
                    'q': self.mixture,
                    'volume': volume_out
                })

        # Use compatibility function for getting links
        flows_out = [abs(link.flow) for link in _get_links(node, 'downstream')]
        self.parcels_out(flows_out)


class Tank_LIFO(MIX):
    """
    Last In First Out (LIFO) tank model.
    
    Parcels are stratified with newest on top.
    """
    
    def __init__(self, maxvolume: float):
        """
        Initialize LIFO tank.
        
        Args:
            maxvolume: Maximum tank volume in m³
        """
        super().__init__()
        self.maxvolume = maxvolume
        self.state: List[Dict[str, Any]] = []

    def mix(self, inflow: List[Dict[str, Any]], node: Any, 
            timestep: float, input_sol: Any) -> None:
        """
        Process flow through LIFO tank.
        
        Args:
            inflow: List of incoming parcels
            node: Tank node object
            timestep: Simulation timestep in seconds
            input_sol: Input solutions (not used)
        """
        self.mixed_parcels = []
        
        # Use compatibility function for getting links
        downstream_links = _get_links(node, 'downstream')

        if not downstream_links:
            # Tank is filling
            for parcel in inflow:
                volume = (parcel['x1'] - parcel['x0']) * parcel['volume']
                shift = volume / self.maxvolume

                # Shift existing parcels down
                self.state = [
                    {
                        'x0': s['x0'] + shift,
                        'x1': s['x1'] + shift,
                        'q': s['q']
                    }
                    for s in self.state
                ]

                # Add new parcel at top
                new_state = []
                if self.state and parcel['q'] == self.state[0]['q']:
                    self.state[0]['x0'] = 0
                else:
                    new_state.append({
                        'x0': 0.0,
                        'x1': shift,
                        'q': parcel['q']
                    })
                self.state = new_state + self.state

        elif sum(link.flow for link in downstream_links) > 0:
            # Tank is emptying
            flows_out = [abs(link.flow) for link in downstream_links]
            vol_out = sum(flows_out) / 3600 * timestep
            shift = vol_out / self.maxvolume

            # Shift parcels up
            self.state = [
                {
                    'x0': s['x0'] - shift,
                    'x1': s['x1'] - shift,
                    'q': s['q']
                }
                for s in self.state
            ]

            xcure = 1.0
            new_state = []
            
            for parcel in self.state:
                x0 = parcel['x0']
                x1 = parcel['x1']
                
                # Check if parcel exits tank (x < 0)
                if x1 > 0:
                    vol = abs(x0) * self.maxvolume if x0 < 0 else 0
                    
                    if x0 < 0:
                        excess = vol / vol_out if vol_out > 0 else 0
                        x0_out = xcure - excess
                        
                        self.mixed_parcels.append({
                            'x0': x0_out,
                            'x1': xcure,
                            'q': parcel['q'],
                            'volume': vol_out
                        })
                        xcure = x0_out
                        
                        if x1 > 0:
                            parcel['x0'] = 0
                            new_state.append(parcel)
                    else:
                        new_state.append(parcel)
                        
            self.state = new_state
            self.parcels_out(flows_out)


class Tank_FIFO(MIX):
    """
    First In First Out (FIFO) tank model.
    
    Parcels maintain entry order through the tank.
    """
    
    def __init__(self, volume: float):
        """
        Initialize FIFO tank.
        
        Args:
            volume: Tank volume in m³
        """
        super().__init__()
        self.volume = volume
        self.volume_prev = volume
        self.state: List[Dict[str, Any]] = []

    def mix(self, inflow: List[Dict[str, Any]], node: Any, 
            timestep: float, input_sol: Any) -> None:
        """
        Process flow through FIFO tank.
        
        Args:
            inflow: List of incoming parcels
            node: Tank node object
            timestep: Simulation timestep in seconds
            input_sol: Input solutions (not used)
        """
        # Handle volume changes
        factor = self.volume_prev / self.volume if self.volume > 0 else 1.0

        for parcel in inflow:
            volume = (parcel['x1'] - parcel['x0']) * parcel['volume']
            shift = volume / self.volume if self.volume > 0 else 0

            # Adjust existing parcels for volume change and new input
            self.state = [
                {
                    'x0': s['x0'] * factor + shift,
                    'x1': s['x1'] * factor + shift,
                    'q': s['q']
                }
                for s in self.state
            ]

            # Add new parcel
            new_state = []
            if self.state and parcel['q'] == self.state[0]['q']:
                self.state[0]['x0'] = 0
            else:
                new_state.append({
                    'x0': 0.0,
                    'x1': shift,
                    'q': parcel['q']
                })
            self.state = new_state + self.state
            self.volume_prev = self.volume

        # Process outflow
        new_state = []
        output = []
        
        # Use compatibility function for getting links
        downstream_links = _get_links(node, 'downstream')
        flows_out = [abs(link.flow) for link in downstream_links]
        vol_out = sum(flows_out) / 3600 * timestep
        
        x0_out = 0.0
        
        for parcel in self.state:
            x0 = parcel['x0']
            x1 = parcel['x1']
            
            # Calculate volume exiting (x > 1)
            if x1 > 1:
                vol = (x1 - max(1, x0)) * self.volume
                
                x1_out = x0_out + vol / vol_out if vol_out > 0 else x0_out
                output.append({
                    'x0': x0_out,
                    'x1': x1_out,
                    'q': parcel['q'],
                    'volume': vol_out
                })
                x0_out = x1_out
                
                if x0 < 1:
                    parcel['x1'] = 1
                    new_state.append(parcel)
            else:
                new_state.append(parcel)

        self.mixed_parcels = output
        self.state = new_state
        self.parcels_out(flows_out)
