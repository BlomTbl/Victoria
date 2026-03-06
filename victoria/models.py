"""
Models module for creating network component models.
This module creates the FIFO and MIX models for all links and nodes in the hydraulic network.
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

        self._load_links(network)
        self._load_nodes(network)

        logger.info(
            "Models initialized: %d nodes, %d links",
            len(self.nodes), len(self.links)
        )

    def _load_nodes(self, network: Any) -> None:
        """
        Create node models from network junctions, reservoirs, and tanks.

        Args:
            network: EPyNet network object
        """
        self._create_models(network.junctions, Junction, self.junctions, self.nodes)
        self._create_models(network.reservoirs, Reservoir, self.reservoirs, self.nodes)

        for tank in network.tanks:
            # Default to CSTR model - can be changed if needed
            tank_model = Tank_CSTR(tank.initvolume)
            self.tanks[tank.uid] = tank_model
            self.nodes[tank.uid] = tank_model
        logger.debug(
            "Loaded %d junctions, %d reservoirs, %d tanks",
            len(self.junctions),
            len(self.reservoirs),
            len(self.tanks)
        )

    def _load_links(self, network: Any) -> None:
        """
        Create link models from network pipes, pumps, and valves.

        Args:
            network: EPyNet network object
        """
        for pipe in network.pipes:
            pipe_volume = self._calculate_pipe_volume(pipe.length, pipe.diameter)
            pipe_model = Pipe(volume=pipe_volume)
            self.pipes[pipe.uid] = pipe_model
            self.links[pipe.uid] = pipe_model

        self._create_models(network.pumps, Pump, self.pumps, self.links)
        self._create_models(network.valves, Valve, self.valves, self.links)

        logger.debug(
            "Loaded %d pipes, %d pumps, %d valves",
            len(self.pipes),
            len(self.pumps),
            len(self.valves)
        )

    def _create_models(self, items, model_cls, model_dict, update_dict):
        """
        Create models for iterable of network items.

        Args:
            items: Iterable of network components with .uid attribute
            model_cls: Model class to instantiate
            model_dict: Dictionary to store created models (indexed by uid)
            update_dict: Dictionary to also update (usually self.nodes or self.links)
        """
        for item in items:
            model = model_cls() if not callable(getattr(model_cls, '__call__', None)) else model_cls()
            model_dict[item.uid] = model
            update_dict[item.uid] = model

    @staticmethod
    def _calculate_pipe_volume(length_m: float, diameter_mm: float) -> float:
        """
        Calculate the volume of a pipe.

        Args:
            length_m: Length of the pipe in meters
            diameter_mm: Diameter of the pipe in millimeters

        Returns:
            Volume in cubic meters
        """
        diameter_m = diameter_mm * 1e-3
        return 0.25 * pi * length_m * diameter_m ** 2

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
        try:
            return self.nodes[node_uid]
        except KeyError:
            raise KeyError(f"Node '{node_uid}' not found in models") from None

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
        try:
            return self.links[link_uid]
        except KeyError:
            raise KeyError(f"Link '{link_uid}' not found in models") from None
