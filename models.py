"""
Models module for creating network component models.

This module creates the FIFO and MIX models for all links and nodes
in the hydraulic network.
"""
from typing import Dict, Any
from math import pi
import logging

from .fifo import Pipe, Pump, Valve
from .mix import Junction, Reservoir, Tank_CSTR, Tank_FIFO, Tank_LIFO

logger = logging.getLogger(__name__)


class Models:
    """
    Container for all node and link models in the network.
    
    Creates appropriate FIFO/MIX models for each network component.
    """
    
    def __init__(self, network: Any):
        """
        Initialize models from network.
        
        Args:
            network: EPyNet network object
        """
        self.nodes: Dict[str, Any] = {}
        self.junctions: Dict[str, Junction] = {}
        self.reservoirs: Dict[str, Reservoir] = {}
        self.tanks: Dict[str, Any] = {}

        self.links: Dict[str, Any] = {}
        self.pipes: Dict[str, Pipe] = {}
        self.pumps: Dict[str, Pump] = {}
        self.valves: Dict[str, Valve] = {}

        self.load_links(network)
        self.load_nodes(network)
        
        logger.info(
            f"Models initialized: {len(self.nodes)} nodes, {len(self.links)} links"
        )

    def load_nodes(self, network: Any) -> None:
        """
        Create node models from network junctions, reservoirs, and tanks.
        
        Args:
            network: EPyNet network object
        """
        # Create junction models
        for junction in network.junctions:
            node = Junction()
            self.junctions[junction.uid] = node
            self.nodes[junction.uid] = node

        # Create reservoir models
        for reservoir in network.reservoirs:
            node = Reservoir()
            self.reservoirs[reservoir.uid] = node
            self.nodes[reservoir.uid] = node

        # Create tank models
        for tank in network.tanks:
            # Default to CSTR model - can be changed based on requirements
            node = Tank_CSTR(tank.initvolume)
            
            # Alternative tank models:
            # node = Tank_FIFO(tank.maxvolume)
            # node = Tank_LIFO(tank.maxvolume)
            
            self.tanks[tank.uid] = node
            self.nodes[tank.uid] = node
            
        logger.debug(
            f"Loaded {len(self.junctions)} junctions, "
            f"{len(self.reservoirs)} reservoirs, "
            f"{len(self.tanks)} tanks"
        )

    def load_links(self, network: Any) -> None:
        """
        Create link models from network pipes, pumps, and valves.
        
        Args:
            network: EPyNet network object
        """
        # Create pipe models
        for pipe in network.pipes:
            # Calculate pipe volume: V = π/4 * L * D²
            # Length in m, diameter in mm -> convert to m
            pipe_volume = (
                0.25 * pi * pipe.length * (pipe.diameter * 1e-3) ** 2
            )
            link = Pipe(volume=pipe_volume)
            self.pipes[pipe.uid] = link
            self.links[pipe.uid] = link

        # Create pump models
        for pump in network.pumps:
            link = Pump()
            self.pumps[pump.uid] = link
            self.links[pump.uid] = link  # Fixed bug: was using 'pipe.uid'

        # Create valve models
        for valve in network.valves:
            link = Valve()
            self.valves[valve.uid] = link
            self.links[valve.uid] = link  # Fixed bug: was using 'valve.uid'
            
        logger.debug(
            f"Loaded {len(self.pipes)} pipes, "
            f"{len(self.pumps)} pumps, "
            f"{len(self.valves)} valves"
        )

    def get_node_model(self, node_uid: str) -> Any:
        """
        Get model for a specific node.
        
        Args:
            node_uid: Node unique identifier
            
        Returns:
            Node model object
            
        Raises:
            KeyError: If node not found
        """
        if node_uid not in self.nodes:
            raise KeyError(f"Node '{node_uid}' not found in models")
        return self.nodes[node_uid]

    def get_link_model(self, link_uid: str) -> Any:
        """
        Get model for a specific link.
        
        Args:
            link_uid: Link unique identifier
            
        Returns:
            Link model object
            
        Raises:
            KeyError: If link not found
        """
        if link_uid not in self.links:
            raise KeyError(f"Link '{link_uid}' not found in models")
        return self.links[link_uid]
