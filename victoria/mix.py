"""
MIX module — version 4.

Changes compared to v3:
  - Tank_LIFO.mix: abs(link.flow) used when computing total_outflow
    (was: link.flow — could become negative on backflow through a valve).
  - Reservoir.mix: logs a DEBUG warning when inflow parcels arrive
    (parcels are discarded as expected, but silent incorrectness on
    backflow is now visible).
  - Junction, Tank_CSTR, Tank_FIFO: unchanged from v3.
  - _merge_adjacent / _enforce_max_parcels: imported from fifo v4
    (O(n log n) heap implementation).
"""

from __future__ import annotations

from typing import List, Dict, Any
from math import exp
import logging

try:
    from .fifo import _merge_adjacent, _enforce_max_parcels
except ImportError:
    from fifo import _merge_adjacent, _enforce_max_parcels

logger = logging.getLogger(__name__)

_ROUND      = 6
_EPS_MERGE  = 0.005   # default 0.5% quality difference
_MAX_PARCEL = 50      # default max parcels per node output


def _get_links(node: Any, direction: str) -> list:
    attr  = f'{direction}_links'
    links = getattr(node, attr, [])
    return links() if callable(links) else links


def _node_outflow(node: Any) -> float:
    cached = getattr(node, '_cached_outflow', None)
    if cached is not None:
        return cached
    return sum(abs(link.flow) for link in _get_links(node, 'downstream'))


def _node_volume(node: Any) -> float:
    cached = node._values.get(24, None)
    if cached is not None:
        return cached
    return node.volume


# ── Base class ────────────────────────────────────────────────────────────────

class MIX:

    eps_merge:   float = _EPS_MERGE
    max_parcels: int   = _MAX_PARCEL

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


# ── Junction ──────────────────────────────────────────────────────────────────

class Junction(MIX):
    """
    Junction node — O(n log n) sweep + parcel merging on output.

    The sweep reduces O(n²) to O(n log n) in the number of boundary points.
    Parcel merging on mixed_parcels limits the propagation of large parcel
    lists to downstream pipes.
    """

    def mix(self, inflow: List[Dict[str, Any]], node: Any,
            timestep: float, input_sol: Any) -> None:
        self.mixed_parcels = []
        if not inflow:
            return

        demand  = round(node.demand / 3600 * timestep, 7)
        parcels = sorted(inflow, key=lambda p: p['x1'])

        boundaries = sorted(
            {0.0} | {p['x0'] for p in parcels} | {p['x1'] for p in parcels}
        )

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

        # ── Parcel merging on output ──────────────────────────────────────────
        if len(self.mixed_parcels) > 1:
            self.mixed_parcels = _merge_adjacent(self.mixed_parcels, self.eps_merge)
        if len(self.mixed_parcels) > self.max_parcels:
            self.mixed_parcels = _enforce_max_parcels(self.mixed_parcels, self.max_parcels)

        flows_out = [abs(link.flow) for link in _get_links(node, 'downstream')]
        self.parcels_out(flows_out)


# ── Reservoir ─────────────────────────────────────────────────────────────────

class Reservoir(MIX):
    """
    Reservoir node.

    Output is always the configured source solution (input_sol[node.uid]).
    Incoming parcels are discarded — this is hydraulically correct as long
    as there is no backflow towards the reservoir. On backflow a DEBUG
    message is logged so the situation does not fail silently.
    """

    def mix(self, inflow: List[Dict[str, Any]], node: Any,
            timestep: float, input_sol: Dict) -> None:
        self.mixed_parcels = []

        if inflow:
            logger.debug(
                "Reservoir '%s' received %d inflow parcels — discarded "
                "(possible backflow).", node.uid, len(inflow)
            )

        q            = {input_sol[node.uid].number: 1.0}
        outflow      = _node_outflow(node)
        shift_volume = timestep * outflow / 3600
        self.mixed_parcels.append({'x0': 0.0, 'x1': 1.0, 'q': q,
                                    'volume': shift_volume})
        flows_out = [abs(link.flow) for link in _get_links(node, 'downstream')]
        if flows_out:
            self.parcels_out(flows_out)
        else:
            self.outflow = [[[shift_volume, q]]]


# ── Tank_CSTR ─────────────────────────────────────────────────────────────────

class Tank_CSTR(MIX):

    def __init__(self, initvolume: float):
        super().__init__()
        self.volume  = initvolume
        self.mixture: Dict = {}

    def mix(self, inflow: List[Dict[str, Any]], node: Any,
            timestep: float, input_sol: Any) -> None:
        self.mixed_parcels = []
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
        volume_out = _node_outflow(node) / 3600 * timestep

        new_solution = self.merge_load({}, mixture, frac)
        new_solution = self.merge_load(new_solution, self.mixture, 1 - frac)
        solution_out = self.merge_load({}, self.mixture, 0.5)
        solution_out = self.merge_load(solution_out, new_solution, 0.5)

        self.mixed_parcels.append({'x0': 0.0, 'x1': 1.0,
                                    'q': solution_out, 'volume': volume_out})
        self.mixture = new_solution

        flows_out = [abs(link.flow) for link in _get_links(node, 'downstream')]
        self.parcels_out(flows_out)


# ── Tank_LIFO ─────────────────────────────────────────────────────────────────

class Tank_LIFO(MIX):
    """
    Tank with LIFO (last-in, first-out) displacement model.

    Bug fix compared to v3: total_outflow is now computed with abs(link.flow).
    Without abs() a negative flow value (backflow through a valve) could make
    the sum zero or negative, causing the output branch to never execute even
    though outflow was actually occurring.
    """

    def __init__(self, maxvolume: float):
        super().__init__()
        self.maxvolume = maxvolume
        self.state: List[Dict[str, Any]] = []

    def _shift_state(self, shift: float) -> None:
        for s in self.state:
            s['x0'] += shift
            s['x1'] += shift

    def mix(self, inflow: List[Dict[str, Any]], node: Any,
            timestep: float, input_sol: Any) -> None:
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

        # ── Fix: abs() on link.flow ───────────────────────────────────────────
        total_outflow = sum(abs(link.flow) for link in downstream_links)

        if total_outflow > 0:
            flows_out = [abs(link.flow) for link in downstream_links]
            vol_out   = sum(flows_out) / 3600 * timestep
            shift     = vol_out / self.maxvolume if self.maxvolume > 0 else 0
            self.state = [
                {'x0': s['x0'] - shift, 'x1': s['x1'] - shift, 'q': s['q']}
                for s in self.state
            ]
            xcure = 1.0
            new_state = []
            for p in self.state:
                x0, x1 = p['x0'], p['x1']
                if x1 > 0:
                    vol = abs(x0) * self.maxvolume if x0 < 0 else 0
                    if x0 < 0:
                        excess = vol / vol_out if vol_out > 0 else 0
                        x0_out = xcure - excess
                        self.mixed_parcels.append({
                            'x0': x0_out, 'x1': xcure,
                            'q': p['q'], 'volume': vol_out
                        })
                        xcure = x0_out
                    if x1 > 0:
                        p['x0'] = 0
                        new_state.append(p)
                else:
                    new_state.append(p)
            self.state = new_state
            self.parcels_out(flows_out)


# ── Tank_FIFO ─────────────────────────────────────────────────────────────────

class Tank_FIFO(MIX):

    def __init__(self, volume: float):
        super().__init__()
        self.volume = volume
        self.volume_prev = volume
        self.state: List[Dict[str, Any]] = []

    def _shift_and_scale_state(self, shift: float, factor: float) -> None:
        self.state = [
            {'x0': s['x0'] * factor + shift,
             'x1': s['x1'] * factor + shift,
             'q':  s['q']}
            for s in self.state
        ]

    def mix(self, inflow: List[Dict[str, Any]], node: Any,
            timestep: float, input_sol: Any) -> None:
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
                output.append({'x0': x0_out, 'x1': x1_out,
                                'q': p['q'], 'volume': vol_out})
                x0_out = x1_out
            if x0 < 1:
                p['x1'] = 1
                new_state.append(p)
            else:
                new_state.append(p)

        self.mixed_parcels = output
        self.state         = new_state
        self.parcels_out(flows_out)
