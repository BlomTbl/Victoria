"""
Models module — version 2.

Changes compared to v1:
  - _create_models: dead-code condition removed (was always True).
  - Tank model selection: default Tank_CSTR, but configurable via
    Models.tank_model_map (uid -> class) at or after construction.
    This allows individual tanks to be set as Tank_FIFO or Tank_LIFO
    without subclassing Models.
  - Documentation extended for tank_model_map.
"""

from __future__ import annotations

from typing import Dict, Any, Optional, Type
from math import pi
import logging

from .fifo import Pipe, Pump, Valve
from .mix import Junction, Reservoir, Tank_CSTR, Tank_FIFO, Tank_LIFO

logger = logging.getLogger(__name__)

# Type alias for tank model classes
TankModelClass = Type[Any]


class Models:
    """
    Container for all node and link models in the network.
    Creates appropriate FIFO/MIX models for each network component.

    Tank model configuration
    ------------------------
    By default all tanks are created as Tank_CSTR. Use ``tank_model_map``
    to specify a different class per tank uid:

    .. code-block:: python

        models = Models(network)   # all tanks -> CSTR

        # Or: pass a map to the constructor
        models = Models(
            network,
            tank_model_map={
                'T1': Tank_FIFO,
                'T2': Tank_LIFO,
            }
        )

    The class is called with the tank's initvolume as its sole positional
    argument (same as Tank_CSTR). Make sure the chosen class accepts a
    volume argument.
    """

    def __init__(self, network: Any,
                 tank_model_map: Optional[Dict[str, TankModelClass]] = None):
        """
        Initialise models from the network.

        Args:
            network:        EPyNet network object.
            tank_model_map: Optional mapping of tank uid to model class.
                            Tanks not in the map default to Tank_CSTR.
        """
        self._tank_model_map: Dict[str, TankModelClass] = tank_model_map or {}

        self.nodes:      Dict[str, Any]       = {}
        self.junctions:  Dict[str, Junction]  = {}
        self.reservoirs: Dict[str, Reservoir] = {}
        self.tanks:      Dict[str, Any]       = {}
        self.links:      Dict[str, Any]       = {}
        self.pipes:      Dict[str, Pipe]      = {}
        self.pumps:      Dict[str, Pump]      = {}
        self.valves:     Dict[str, Valve]     = {}

        self._load_links(network)
        self._load_nodes(network)

        logger.info(
            "Models initialized: %d nodes, %d links",
            len(self.nodes), len(self.links)
        )

    # ── Privé laadmethoden ───────────────────────────────────────────────────

    def _load_nodes(self, network: Any) -> None:
        """Create node models from network junctions, reservoirs, and tanks."""
        self._create_models(network.junctions, Junction,  self.junctions,  self.nodes)
        self._create_models(network.reservoirs, Reservoir, self.reservoirs, self.nodes)

        for tank in network.tanks:
            model_cls  = self._tank_model_map.get(tank.uid, Tank_CSTR)
            tank_model = model_cls(tank.initvolume)
            self.tanks[tank.uid] = tank_model
            self.nodes[tank.uid] = tank_model

        logger.debug(
            "Loaded %d junctions, %d reservoirs, %d tanks",
            len(self.junctions),
            len(self.reservoirs),
            len(self.tanks),
        )

    def _load_links(self, network: Any) -> None:
        """Create link models from network pipes, pumps, and valves."""
        for pipe in network.pipes:
            pipe_volume = self._calculate_pipe_volume(pipe.length, pipe.diameter)
            pipe_model  = Pipe(volume=pipe_volume)
            self.pipes[pipe.uid] = pipe_model
            self.links[pipe.uid] = pipe_model

        self._create_models(network.pumps,  Pump,  self.pumps,  self.links)
        self._create_models(network.valves, Valve, self.valves, self.links)

        logger.debug(
            "Loaded %d pipes, %d pumps, %d valves",
            len(self.pipes),
            len(self.pumps),
            len(self.valves),
        )

    @staticmethod
    def _create_models(items: Any, model_cls: Any,
                       model_dict: Dict, update_dict: Dict) -> None:
        """
        Create models for an iterable of network elements.

        Args:
            items:       Iterable of network elements with a .uid attribute.
            model_cls:   Model class instantiated without arguments.
            model_dict:  Dict for the created models (indexed by uid).
            update_dict: Dict that is also updated (nodes or links).
        """
        for item in items:
            model = model_cls()
            model_dict[item.uid] = model
            update_dict[item.uid] = model

    # ── Hulpmethoden ─────────────────────────────────────────────────────────

    @staticmethod
    def _calculate_pipe_volume(length_m: float, diameter_mm: float) -> float:
        """
        Calculate the volume of a pipe.

        Args:
            length_m:    Pipe length in metres.
            diameter_mm: Pipe diameter in millimetres.

        Returns:
            Volume in cubic metres.
        """
        diameter_m = diameter_mm * 1e-3
        return 0.25 * pi * length_m * diameter_m ** 2

    def get_node_model(self, node_uid: str) -> Any:
        """
        Return the model for a specific node.

        Args:
            node_uid: Unique node identifier.

        Returns:
            Node model object.

        Raises:
            KeyError: If the node is not found.
        """
        try:
            return self.nodes[node_uid]
        except KeyError:
            raise KeyError(f"Node '{node_uid}' not found in models") from None

    def get_link_model(self, link_uid: str) -> Any:
        """
        Return the model for a specific link.

        Args:
            link_uid: Unique link identifier.

        Returns:
            Link model object.

        Raises:
            KeyError: If the link is not found.
        """
        try:
            return self.links[link_uid]
        except KeyError:
            raise KeyError(f"Link '{link_uid}' not found in models") from None

    def set_tank_model(self, tank_uid: str, model_cls: TankModelClass,
                       initvolume: Optional[float] = None) -> None:
        """
        Replace the model of an existing tank after initialisation.

        Useful when the desired tank model is not known until after Models
        has already been created (e.g. based on a configuration file).

        Args:
            tank_uid:   Unique tank identifier.
            model_cls:  New model class (Tank_CSTR, Tank_FIFO, or Tank_LIFO).
            initvolume: Initial volume for the new model. If None, the volume
                        of the current model is used (attribute 'volume' or
                        'maxvolume').

        Raises:
            KeyError: If tank_uid is not in self.tanks.
        """
        if tank_uid not in self.tanks:
            raise KeyError(f"Tank '{tank_uid}' not found in models")

        existing = self.tanks[tank_uid]
        if initvolume is None:
            initvolume = getattr(existing, 'volume',
                         getattr(existing, 'maxvolume', 0.0))

        new_model = model_cls(initvolume)
        self.tanks[tank_uid] = new_model
        self.nodes[tank_uid] = new_model
        logger.info("Tank '%s' model replaced with %s", tank_uid, model_cls.__name__)
