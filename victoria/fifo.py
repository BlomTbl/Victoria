"""
FIFO module — version 4.

Changes compared to v3:
  - push_in: offset calculation corrected. x0/x1 are now consistently
    determined after self._offset has been incremented, ensuring the new
    parcel always precedes the existing state (x0 < x1 guaranteed).
  - _enforce_max_parcels: O(n log n) heap implementation instead of O(n²)
    linear scan. At max_parcels=50 the difference is small, but for larger
    limits the saving is significant.
  - Remaining logic (parcel merging, push_pull, fill) unchanged from v3.
"""

from __future__ import annotations

import heapq
from typing import List, Dict, Any, Optional

EPS = 1e-10


# ── Helper functions ──────────────────────────────────────────────────────────

def _merge_adjacent(state: List[Dict[str, Any]],
                    eps_merge: float) -> List[Dict[str, Any]]:
    """
    Merge adjacent parcels whose quality values all lie within eps_merge
    of each other.

    Works for both pipe.state (no 'volume' key) and mixed_parcels (with
    'volume' key): the weight is p['volume'] if present, otherwise the
    width fraction (x1 - x0).
    """
    if len(state) <= 1:
        return state

    merged = [dict(state[0])]
    merged[-1]['q'] = dict(state[0]['q'])

    for p in state[1:]:
        prev     = merged[-1]
        prev_q   = prev['q']
        cur_q    = p['q']
        all_keys = set(prev_q) | set(cur_q)

        if all(abs(prev_q.get(k, 0.0) - cur_q.get(k, 0.0)) <= eps_merge
               for k in all_keys):
            w_prev = prev.get('volume', prev['x1'] - prev['x0'])
            w_cur  = p.get('volume',    p['x1']    - p['x0'])
            w_tot  = w_prev + w_cur
            if w_tot > 0:
                prev['q'] = {
                    k: (prev_q.get(k, 0.0) * w_prev +
                        cur_q.get(k, 0.0)  * w_cur) / w_tot
                    for k in all_keys
                }
            prev['x1'] = p['x1']
            if 'volume' in prev and 'volume' in p:
                prev['volume'] = w_tot
        else:
            new_p = dict(p)
            new_p['q'] = dict(p['q'])
            merged.append(new_p)

    return merged


def _parcel_diff(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    """Maximum quality difference between two adjacent parcels."""
    all_keys = set(a['q']) | set(b['q'])
    if not all_keys:
        return 0.0
    return max(abs(a['q'].get(k, 0.0) - b['q'].get(k, 0.0)) for k in all_keys)


def _enforce_max_parcels(state: List[Dict[str, Any]],
                          max_parcels: int) -> List[Dict[str, Any]]:
    """
    If the parcel list is longer than max_parcels, repeatedly merge the
    two adjacent parcels with the smallest quality difference until the
    limit is reached.

    Implementation: O(n log n) via a min-heap on diff values.
    Stale heap entries are removed lazily (tombstone pattern).

    This guarantees an upper bound on computation time at the cost of a
    small loss of accuracy in zones with sharp quality boundaries.
    """
    if len(state) <= max_parcels:
        return state

    # Working list as a doubly-linked list via index arrays for O(1) removal.
    n    = len(state)
    prev = list(range(-1, n - 1))   # prev[i] = previous live index
    nxt  = list(range(1, n + 1))    # nxt[i]  = next live index (n = sentinel)

    parcels = [dict(p) for p in state]
    for p in parcels:
        p['q'] = dict(p['q'])

    # Heap: (diff, i, j) where i and j are adjacent indices
    heap: list = []
    for i in range(n - 1):
        j = nxt[i]
        if j < n:
            diff = _parcel_diff(parcels[i], parcels[j])
            heapq.heappush(heap, (diff, i, j))

    alive = set(range(n))
    count = n

    while count > max_parcels and heap:
        diff, i, j = heapq.heappop(heap)

        # Tombstone check: both indices must still be live and contiguous
        if i not in alive or j not in alive or nxt[i] != j:
            continue

        # Merge i and j -> keep result in i, remove j
        p = parcels[i]
        q = parcels[j]
        w_p = p.get('volume', p['x1'] - p['x0'])
        w_q = q.get('volume', q['x1'] - q['x0'])
        w_t = w_p + w_q
        all_keys = set(p['q']) | set(q['q'])
        merged_q = (
            {k: (p['q'].get(k, 0.0) * w_p + q['q'].get(k, 0.0) * w_q) / w_t
             for k in all_keys}
            if w_t > 0 else dict(p['q'])
        )
        parcels[i] = {
            'x0': p['x0'],
            'x1': q['x1'],
            'q':  merged_q,
            **({'volume': w_t} if 'volume' in p and 'volume' in q else {}),
        }

        # Remove j from the linked list
        nxt_j = nxt[j]
        nxt[i] = nxt_j
        if nxt_j < n:
            prev[nxt_j] = i
        alive.discard(j)
        count -= 1

        # Push new pair (i, nxt[i]) onto the heap
        if nxt[i] < n:
            new_diff = _parcel_diff(parcels[i], parcels[nxt[i]])
            heapq.heappush(heap, (new_diff, i, nxt[i]))

    # Reconstruct the list in order
    result = []
    idx = 0
    while idx < n:
        if idx in alive:
            result.append(parcels[idx])
        idx = nxt[idx] if idx < n else n
        if idx >= n:
            break

    return result


# ── Base class ────────────────────────────────────────────────────────────────

class FIFO:

    def __init__(self, volume: float = 0.0):
        self.volume   = volume
        self.state:        List[Dict[str, Any]] = []
        self.output_state: List[Dict[str, Any]] = []
        self.ready    = False
        self.downstream_node: Optional[Any] = None
        self.upstream_node:   Optional[Any] = None
        self._offset: float = 0.0

    def connections(self, downstream: Any, upstream: Any) -> None:
        self.downstream_node = downstream
        self.upstream_node   = upstream

    def _materialize(self) -> None:
        """Apply the accumulated offset to absolute x0/x1 coordinates."""
        if self._offset == 0.0:
            return
        for s in self.state:
            s['x0'] += self._offset
            s['x1'] += self._offset
        self._offset = 0.0

    def reverse_parcels(self, downstream: Any, upstream: Any) -> None:
        self._materialize()
        self.state = sorted(
            [{'x0': abs(1 - p['x1']), 'x1': abs(1 - p['x0']), 'q': p['q']}
             for p in self.state],
            key=lambda p: p['x1']
        )
        self.downstream_node = downstream
        self.upstream_node   = upstream

    def push_in(self, volumes: List[List[Any]]) -> None:
        """
        Add volumes to the pipe inlet via cumulative offset (O(1)).

        Fix compared to v3: self._offset is incremented *first*, so that
        new_x0 and new_x1 are computed consistently afterwards:
            new_x0 = -(self._offset)             (front of the new parcel)
            new_x1 = -(self._offset) + fraction  (back of the new parcel)
        This guarantees x0 < x1 and correct ordering relative to existing parcels.
        """
        if self.volume <= 0:
            return
        while volumes:
            v, q = volumes.pop()
            if v <= 0:
                continue
            fraction       = v / self.volume
            self._offset  += fraction          # increment first
            new_x0         = -self._offset
            new_x1         = -self._offset + fraction

            # Merge with the existing first parcel if quality matches
            # and the new parcel's x1 is adjacent to the first parcel's x0.
            if (self.state and
                    self.state[0]['q'] == q and
                    abs((self.state[0]['x0'] + self._offset) - fraction) < EPS):
                self.state[0]['x0'] = new_x0
            else:
                self.state.insert(0, {'x0': new_x0, 'x1': new_x1, 'q': q})


# ── Pipe ──────────────────────────────────────────────────────────────────────

class Pipe(FIFO):
    """FIFO pipe with parcel merging."""

    # Class-level defaults — can be overridden per instance
    eps_merge:   float = 0.005   # max quality difference for merging (0.5%)
    max_parcels: int   = 50      # hard upper bound on parcel list length

    def push_pull(self, flow: float, volumes: List[List[Any]]) -> None:
        self.output_state = []
        if not volumes or flow <= 0:
            self.ready = True
            return

        total_volume = sum(v for v, _ in volumes)
        if total_volume <= 0:
            self.ready = True
            return

        scale       = flow / total_volume
        vol_updated = [[v * scale, q] for v, q in volumes]
        self.push_in(vol_updated)

        self._materialize()

        new_state = []
        output    = []

        for parcel in self.state:
            x0, x1 = parcel['x0'], parcel['x1']
            if abs(x0) < EPS: x0 = 0.0
            if abs(x1) < EPS: x1 = 0.0
            if abs(x0 - 1) < EPS: x0 = 1.0
            if abs(x1 - 1) < EPS: x1 = 1.0
            parcel['x0'], parcel['x1'] = x0, x1

            if x1 > 1:
                vol = (x1 - max(1.0, x0)) * self.volume
                if vol > 0:
                    output.append([vol, parcel['q']])
                if x0 < 1:
                    parcel['x1'] = 1.0
                    new_state.append(parcel)
            else:
                new_state.append(parcel)

        # ── Parcel merging on the remaining state ─────────────────────────────
        if len(new_state) > 1:
            new_state = _merge_adjacent(new_state, self.eps_merge)
        if len(new_state) > self.max_parcels:
            new_state = _enforce_max_parcels(new_state, self.max_parcels)

        self.state = new_state

        # Build output_state
        if output:
            total_out = sum(v for v, _ in output)
            if total_out > 0:
                x0 = 0.0
                for v, q in output:
                    x1 = x0 + v / total_out
                    if self.output_state and self.output_state[-1]['q'] == q:
                        self.output_state[-1]['x1'] = x1
                    else:
                        self.output_state.append({
                            'x0': x0, 'x1': x1,
                            'q': q, 'volume': total_out
                        })
                    x0 = x1

        self.ready = True

    def fill(self, input_sol: Dict[int, float]) -> None:
        self._offset = 0.0
        self.state        = [{'x0': 0.0, 'x1': 1.0, 'q': input_sol}]
        self.output_state = [{'x0': 0.0, 'x1': 1.0, 'q': input_sol,
                               'volume': self.volume}]


# ── Zero-length variants ──────────────────────────────────────────────────────

class ZeroLengthFIFO(FIFO):

    def push_pull(self, flow: float, volumes: List[List[Any]]) -> None:
        self.output_state = []
        if not volumes or flow <= 0:
            return
        total_volume = sum(v for v, _ in volumes)
        if total_volume <= 0:
            return
        x0 = 0.0
        for v, q in volumes:
            x1 = x0 + v / total_volume
            if self.output_state and self.output_state[-1]['q'] == q:
                self.output_state[-1]['x1'] = x1
            else:
                self.output_state.append({'x0': x0, 'x1': x1,
                                          'q': q, 'volume': flow})
            x0 = x1

    def fill(self, input_sol: Dict[int, float]) -> None:
        self._offset      = 0.0
        self.output_state = [{'x0': 0.0, 'x1': 1.0, 'q': input_sol, 'volume': 0}]


class Pump(ZeroLengthFIFO):
    pass


class Valve(ZeroLengthFIFO):
    pass
