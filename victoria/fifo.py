"""
FIFO (First In First Out) module for hydraulic network modeling.
This module implements various link types (pipes, pumps, valves) using the FIFO principle
for water parcel tracking.
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field


@dataclass
class Parcel:
    """Represents a water parcel with position and quality."""
    x0: float  # Start position (0-1)
    x1: float  # End position (0-1)
    q: Dict[int, float]  # Quality/solution mixture

    def to_dict(self) -> Dict[str, Any]:
        """Convert parcel to dictionary format."""
        return {'x0': self.x0, 'x1': self.x1, 'q': self.q}


class FIFO:
    """Base class for all FIFO link objects in the hydraulic network."""

    def __init__(self, volume: float = 0.0):
        """
        Initialize FIFO link.

        Args:
            volume: Physical volume of the link in m³
        """
        self.volume = volume
        self.state: List[Dict[str, Any]] = []
        self.output_state: List[Dict[str, Any]] = []
        self.ready = False
        self.downstream_node: Optional[Any] = None
        self.upstream_node: Optional[Any] = None

    def connections(self, downstream: Any, upstream: Any) -> None:
        """
        Set the downstream and upstream node connections.

        Args:
            downstream: Downstream node object
            upstream: Upstream node object
        """
        self.downstream_node = downstream
        self.upstream_node = upstream

    def reverse_parcels(self, downstream: Any, upstream: Any) -> None:
        """
        Reverse parcel positions when flow direction changes.

        Args:
            downstream: New downstream node
            upstream: New upstream node
        """
        def _reverse(parcel: Dict[str, Any]) -> Dict[str, Any]:
            return {
                'x0': abs(1 - parcel['x1']),
                'x1': abs(1 - parcel['x0']),
                'q': parcel['q']
            }

        self.state = sorted(
            (_reverse(parcel) for parcel in self.state),
            key=lambda p: p['x1']
        )
        self.downstream_node = downstream
        self.upstream_node = upstream

    def push_in(self, volumes: List[List[Any]]) -> None:
        """
        Push parcels into the link (recursive implementation).

        Args:
            volumes: List of [volume, quality] pairs to push
        """
        # Use iteration instead of recursion for clarity and stack safety
        while volumes:
            v, q = volumes.pop()
            if self.volume <= 0:
                continue
            fraction = v / self.volume

            # Shift existing parcels
            for s in self.state:
                s['x0'] += fraction
                s['x1'] += fraction

            # Merge with existing parcel if same quality, else create new
            if self.state and q == self.state[0]['q']:
                self.state[0]['x0'] = 0
            else:
                self.state.insert(0, {'x0': 0, 'x1': fraction, 'q': q})


class Pipe(FIFO):
    """FIFO implementation for pipe links."""

    def push_pull(self, flow: float, volumes: List[List[Any]]) -> None:
        """
        Push parcels into pipe and pull parcels out.

        Args:
            flow: Flow volume for this timestep
            volumes: List of [volume, quality] pairs to push
        """
        self.output_state = []
        if not volumes or flow <= 0:
            self.ready = True
            return

        total_volume = sum(v[0] for v in volumes)
        if total_volume <= 0:
            self.ready = True
            return

        # Scale volumes proportionally to flow
        vol_updated = [[v / total_volume * flow, q] for v, q in volumes]
        self.push_in(vol_updated)

        new_state = []
        output = []

        for parcel in self.state:
            # Round to prevent numerical errors
            parcel['x0'] = round(parcel['x0'], 10)
            parcel['x1'] = round(parcel['x1'], 10)
            x0, x1 = parcel['x0'], parcel['x1']

            # Calculate output (parcel volume leaving pipe)
            if x1 > 1:
                vol = (x1 - max(1, x0)) * self.volume
                output.append([vol, parcel['q']])
                if x0 < 1:
                    parcel['x1'] = 1
                    new_state.append(parcel)
            else:
                new_state.append(parcel)

        # Compose output state
        if output:
            total_output_volume = sum(v[0] for v in output)
            x0 = 0
            for v, q in output:
                if total_output_volume > 0:
                    x1 = x0 + v / total_output_volume
                    self.output_state.append({
                        'x0': x0,
                        'x1': x1,
                        'q': q,
                        'volume': total_output_volume
                    })
                    x0 = x1

        self.state = new_state
        self.ready = True

    def fill(self, input_sol: Dict[int, float]) -> None:
        """
        Fill the entire pipe with a single solution.

        Args:
            input_sol: Solution quality dictionary
        """
        self.state = [{
            'x0': 0,
            'x1': 1,
            'q': input_sol
        }]
        self.output_state = [{
            'x0': 0,
            'x1': 1,
            'q': input_sol,
            'volume': self.volume
        }]


class ZeroLengthFIFO(FIFO):
    """FIFO for zero-length links (Pumps and Valves)."""

    def push_pull(self, flow: float, volumes: List[List[Any]]) -> None:
        """
        Process flow through zero-length FIFO (instantaneous passage).

        Args:
            flow: Flow volume for this timestep
            volumes: List of [volume, quality] pairs
        """
        self.output_state = []
        if not volumes or flow <= 0:
            return

        total_volume = sum(v[0] for v in volumes)
        if total_volume <= 0:
            return

        x0 = 0
        for v, q in volumes:
            x1 = x0 + v / total_volume
            self.output_state.append({
                'x0': x0,
                'x1': x1,
                'q': q,
                'volume': flow
            })
            x0 = x1

    def fill(self, input_sol: Dict[int, float]) -> None:
        """
        Initialize the zero-length FIFO with a solution.

        Args:
            input_sol: Solution quality dictionary
        """
        self.output_state = [{
            'x0': 0,
            'x1': 1,
            'q': input_sol,
            'volume': 0  # No storage for zero-length links
        }]


class Pump(ZeroLengthFIFO):
    """FIFO implementation for pump links (zero-length)."""
    pass

class Valve(ZeroLengthFIFO):
    """FIFO implementation for valve links (zero-length)."""
    pass
