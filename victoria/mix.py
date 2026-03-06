"""
MIX module — geoptimaliseerde versie 2.

Wijzigingen t.o.v. v1:
  1. Junction.mix: O(n log n) sweep-algoritme (uit v1) behouden.
     node.demand wordt gelezen via de EPyNet _values-cache (gevuld door
     _build_adjacency) — geen extra ctypes-aanroep.
  2. Reservoir.mix: node.outflow gelezen uit _cached_outflow attribuut
     dat door _build_adjacency is gezet, of berekend als som van
     stroomafwaartse link-flows (fallback).
  3. Tank_CSTR.mix: node.volume via _values[EN_TANKVOLUME] cache,
     node.outflow via _cached_outflow.
  4. flows_out berekening: link.flow al gecached in link._values[8]
     dus __getattr__ -> get_property -> _values cache-hit.
  5. _get_links ongewijzigd (EPyNet compatibel).
"""

from typing import List, Dict, Any
from math import exp
import logging

logger = logging.getLogger(__name__)

_ROUND = 6


def _get_links(node: Any, direction: str) -> list:
    attr  = f'{direction}_links'
    links = getattr(node, attr, [])
    return links() if callable(links) else links


def _node_outflow(node: Any) -> float:
    """
    Haal de stroomafwaartse totaalflow op [m³/h].
    Probeert eerst het gecachede attribuut (_cached_outflow) gezet door
    _build_adjacency, valt terug op som van downstream link-flows.
    """
    cached = getattr(node, '_cached_outflow', None)
    if cached is not None:
        return cached
    # Fallback: berekenen uit downstream links (langzamer maar correct)
    return sum(abs(link.flow) for link in _get_links(node, 'downstream'))


def _node_volume(node: Any) -> float:
    """Tank-volume [m³] via gecachede _values of rechtstreeks."""
    # EN_TANKVOLUME = 24
    cached = node._values.get(24, None)
    if cached is not None:
        return cached
    return node.volume   # EPyNet fallback


class MIX:

    def __init__(self):
        self.sorted_parcels: List[Dict[str, Any]] = []
        self.outflow:        List[List[List[Any]]] = []
        self.mixed_parcels:  List[Dict[str, Any]]  = []

    @staticmethod
    def merge_load(existing: Dict, add: Dict, volume: float) -> Dict:
        result = existing.copy()
        for key, v in add.items():
            result[key] = result.get(key, 0) + v * volume
        return result

    def parcels_out(self, flows_out: List[float]) -> None:
        self.outflow = []
        total_flow = sum(flows_out)
        if total_flow <= 1e-7:
            return
        for flow in flows_out:
            ratio = flow / total_flow
            self.outflow.append([
                [((p['x1'] - p['x0']) * ratio * p['volume']), p['q']]
                for p in self.mixed_parcels
            ])


class Junction(MIX):
    """
    Junctionknooppunt — O(n log n) sweep over gesorteerde grenspunten.
    node.demand wordt geleverd door de EPyNet _values-cache (gevuld door
    _build_adjacency via ENgetnodevalue) — geen extra ctypes.
    """

    def mix(self, inflow: List[Dict[str, Any]], node: Any, timestep: float, input_sol: Any) -> None:
        self.mixed_parcels = []
        if not inflow:
            return

        # node.demand: EPyNet __getattr__ -> get_property(9) -> _values[9] cache-hit
        demand = round(node.demand / 3600 * timestep, 7)

        parcels = sorted(inflow, key=lambda p: p['x1'])
        boundaries = sorted({0.0} | {p['x0'] for p in parcels} | {p['x1'] for p in parcels})

        for i in range(len(boundaries) - 1):
            x_lo = boundaries[i]
            x_hi = boundaries[i + 1]
            if x_hi <= x_lo:
                continue

            mixture     = {}
            cell_volume = 0.0
            total_vol   = 0.0

            for p in parcels:
                if p['x1'] <= x_lo or p['x0'] >= x_hi:
                    continue
                overlap = (min(x_hi, p['x1']) - max(x_lo, p['x0'])) * p['volume']
                if overlap <= 0:
                    continue
                for key, val in p['q'].items():
                    mixture[key] = mixture.get(key, 0) + val * overlap
                cell_volume += overlap
                total_vol   += p['volume']

            if cell_volume <= 0:
                continue

            inv_cv = 1.0 / cell_volume
            mixture = {k: round(v * inv_cv, _ROUND) for k, v in mixture.items()}

            effective_volume = max(0.0, total_vol - demand)
            self.mixed_parcels.append({
                'x0': x_lo, 'x1': x_hi,
                'q': mixture, 'volume': effective_volume
            })

        # link.flow is gecached in link._values[8] -> cache-hit, geen ctypes
        flows_out = [abs(link.flow) for link in _get_links(node, 'downstream')]
        self.parcels_out(flows_out)


class Reservoir(MIX):
    """
    Reservoir — node.outflow via _cached_outflow (gezet door _build_adjacency).
    """

    def mix(self, inflow: List[Dict[str, Any]], node: Any, timestep: float, input_sol: Dict) -> None:
        self.mixed_parcels = []
        q = {input_sol[node.uid].number: 1.0}

        # _cached_outflow gezet door _build_adjacency — geen ctypes
        outflow = _node_outflow(node)
        shift_volume = timestep * outflow / 3600

        self.mixed_parcels.append({'x0': 0.0, 'x1': 1.0, 'q': q, 'volume': shift_volume})

        # flows_out via link.flow cache-hit
        flows_out = [abs(link.flow) for link in _get_links(node, 'downstream')]
        if flows_out:
            self.parcels_out(flows_out)
        else:
            self.outflow = [[[shift_volume, q]]]


class Tank_CSTR(MIX):
    """CSTR tank — node.volume en node.outflow via cache."""

    def __init__(self, initvolume: float):
        super().__init__()
        self.volume  = initvolume
        self.mixture: Dict = {}

    def mix(self, inflow: List[Dict[str, Any]], node: Any, timestep: float, input_sol: Any) -> None:
        self.mixed_parcels = []

        # node.volume via EN_TANKVOLUME=24 cache-hit
        volume_tank  = _node_volume(node)
        mixture      = {}
        total_volume = 0.0

        for p in inflow:
            rv = (p['x1'] - p['x0']) * p['volume']
            mixture = self.merge_load(mixture, p['q'], rv)
            total_volume += rv

        if total_volume > 0:
            inv = 1.0 / total_volume
            mixture = {k: round(v * inv, _ROUND) for k, v in mixture.items()}

        frac       = 1.0 if volume_tank <= 0 else 1 - exp(-total_volume / volume_tank)
        # node.outflow via _cached_outflow — geen ctypes
        volume_out = _node_outflow(node) / 3600 * timestep

        new_solution = self.merge_load({}, mixture, frac)
        new_solution = self.merge_load(new_solution, self.mixture, 1 - frac)
        solution_out = self.merge_load({}, self.mixture, 0.5)
        solution_out = self.merge_load(solution_out, new_solution, 0.5)

        self.mixed_parcels.append({'x0': 0.0, 'x1': 1.0, 'q': solution_out, 'volume': volume_out})
        self.mixture = new_solution

        flows_out = [abs(link.flow) for link in _get_links(node, 'downstream')]
        self.parcels_out(flows_out)


class Tank_LIFO(MIX):
    """LIFO tank — ongewijzigd t.o.v. v1 (link.flow via cache-hit)."""

    def __init__(self, maxvolume: float):
        super().__init__()
        self.maxvolume = maxvolume
        self.state: List[Dict[str, Any]] = []

    def _shift_state(self, shift: float) -> None:
        for s in self.state:
            s['x0'] += shift
            s['x1'] += shift

    def mix(self, inflow: List[Dict[str, Any]], node: Any, timestep: float, input_sol: Any) -> None:
        self.mixed_parcels = []
        downstream_links = _get_links(node, 'downstream')

        if not downstream_links:
            for p in inflow:
                volume = (p['x1'] - p['x0']) * p['volume']
                shift  = volume / self.maxvolume if self.maxvolume > 0 else 0
                self._shift_state(shift)
                if self.state and p['q'] == self.state[0]['q']:
                    self.state[0]['x0'] = 0
                else:
                    self.state = [{'x0': 0.0, 'x1': shift, 'q': p['q']}] + self.state
            return

        total_outflow = sum(link.flow for link in downstream_links)
        if total_outflow > 0:
            flows_out = [abs(link.flow) for link in downstream_links]
            vol_out   = sum(flows_out) / 3600 * timestep
            shift     = vol_out / self.maxvolume if self.maxvolume > 0 else 0
            self.state = [{'x0': s['x0'] - shift, 'x1': s['x1'] - shift, 'q': s['q']}
                          for s in self.state]
            xcure     = 1.0
            new_state = []

            for p in self.state:
                x0, x1 = p['x0'], p['x1']
                if x1 > 0:
                    vol = abs(x0) * self.maxvolume if x0 < 0 else 0
                    if x0 < 0:
                        excess = vol / vol_out if vol_out > 0 else 0
                        x0_out = xcure - excess
                        self.mixed_parcels.append(
                            {'x0': x0_out, 'x1': xcure, 'q': p['q'], 'volume': vol_out})
                        xcure = x0_out
                    if x1 > 0:
                        p['x0'] = 0
                        new_state.append(p)
                else:
                    new_state.append(p)

            self.state = new_state
            self.parcels_out(flows_out)


class Tank_FIFO(MIX):
    """FIFO tank — ongewijzigd t.o.v. v1 (link.flow via cache-hit)."""

    def __init__(self, volume: float):
        super().__init__()
        self.volume      = volume
        self.volume_prev = volume
        self.state: List[Dict[str, Any]] = []

    def _shift_and_scale_state(self, shift: float, factor: float) -> None:
        self.state = [
            {'x0': s['x0'] * factor + shift,
             'x1': s['x1'] * factor + shift,
             'q':  s['q']}
            for s in self.state
        ]

    def mix(self, inflow: List[Dict[str, Any]], node: Any, timestep: float, input_sol: Any) -> None:
        factor = self.volume_prev / self.volume if self.volume > 0 else 1.0
        for p in inflow:
            volume = (p['x1'] - p['x0']) * p['volume']
            shift  = volume / self.volume if self.volume > 0 else 0
            self._shift_and_scale_state(shift, factor)
            if self.state and p['q'] == self.state[0]['q']:
                self.state[0]['x0'] = 0
            else:
                self.state = [{'x0': 0.0, 'x1': shift, 'q': p['q']}] + self.state

        self.volume_prev = self.volume

        downstream_links = _get_links(node, 'downstream')
        flows_out = [abs(link.flow) for link in downstream_links]
        vol_out   = sum(flows_out) / 3600 * timestep
        x0_out    = 0.0
        new_state = []
        output    = []

        for p in self.state:
            x0, x1 = p['x0'], p['x1']
            if x1 > 1:
                out_vol = (x1 - max(1, x0)) * self.volume
                x1_out  = x0_out + out_vol / vol_out if vol_out > 0 else x0_out
                output.append({'x0': x0_out, 'x1': x1_out, 'q': p['q'], 'volume': vol_out})
                x0_out = x1_out
            if x0 < 1:
                p['x1'] = 1
                new_state.append(p)
            else:
                new_state.append(p)

        self.mixed_parcels = output
        self.state         = new_state
        self.parcels_out(flows_out)
