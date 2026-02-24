"""
Solver module — optimized version 2.

Changes from v1:
    1. _build_adjacency populates the EPyNet _values ​​cache of each link and node object
        via direct ENgetlinkvalue / ENgetnodevalue calls. Afterward,
        link.flow, link.velocity, node.demand, node.outflow, and node.volume
        only return a dict lookup—no more ctypes in the traversal loop.
    2. node.outflow (for reservoir and tank) is calculated as the sum of the
        downstream link flows from the already cached flow dict.
    3. Iterative BFS and precomputed adjacency (from v1) remain intact.
    4. Ready state as a set (O(1) clear).

Required EPANET property codes (from epynet/epanet2.py):
    EN_FLOW = 8 (link, read only)
    EN_VELOCITY = 9 (link, read only)
    EN_DEMAND = 9 (node, read only)
    EN_TANKVOLUME = 24 (node, read only)
"""

from collections import deque
from typing import Any, Dict, List, Optional, Set
import logging
import numpy as np

logger = logging.getLogger(__name__)

# EPANET property codes — mirrored from epynet/epanet2.py so the solver
# has no import dependency on epynet.
_EN_FLOW       = 8
_EN_VELOCITY   = 9
_EN_DEMAND     = 9
_EN_TANKVOLUME = 24



# EPANET property codes
_EN_FLOW       = 8
_EN_VELOCITY   = 9
_EN_DEMAND     = 9
_EN_TANKVOLUME = 24


class HydraulicCache:
    """
    Pre-computes and caches all hydraulic time-step results.

    Parameters
    ----------
    network: epynet.Network
        The EPyNet network (after loading, before solving).
    """

    def __init__(self, network: Any) -> None:
        self.net = network
        self._links: List[Any] = list(network.links)
        self._nodes: List[Any] = list(network.nodes)
        self._tank_uids = {t.uid for t in network.tanks}

        n_links = len(self._links)
        n_nodes = len(self._nodes)

        # Will be filled by precompute()
        self._flows:     np.ndarray | None = None   # (n_steps, n_links)
        self._vels:      np.ndarray | None = None   # (n_steps, n_links)
        self._demands:   np.ndarray | None = None   # (n_steps, n_nodes)
        self._volumes:   np.ndarray | None = None   # (n_steps, n_tanks)
        self._tank_idx:  List[int]         = []     # indices in _nodes voor tanks
        self._n_links    = n_links
        self._n_nodes    = n_nodes
        self._precomputed = False

    def precompute(self, hydstep_s: int = 300, n_steps: int = 864) -> None:
        """
        Pre-calculate hydraulic values ​​for all time steps using net.solve().

        Use net.solve(simtime) for each step so that the time steps
        exactly match the quality simulation.
        ENopenH/ENcloseH are called per step — this is the correct EPyNet approach.

        Parameters
        ----------
        hydstep_s : int
        Hydraulic time step in seconds.
            n_steps : int
        Number of time steps to cache.
        """
        links  = self._links
        nodes  = self._nodes
        n_l    = self._n_links
        n_n    = self._n_nodes

        tank_idx = [i for i, n in enumerate(nodes) if n.uid in self._tank_uids]
        self._tank_idx = tank_idx
        n_t = len(tank_idx)

        flows_list:   list = []
        vels_list:    list = []
        demands_list: list = []
        volumes_list: list = []

        ep = self.net.ep

        for step in range(n_steps):
            simtime = step * hydstep_s
            # Use EPyNet's solve() — same path as the normal simulation loop
            self.net.solve(simtime=simtime)

            f_row = np.empty(n_l, dtype=np.float32)
            v_row = np.empty(n_l, dtype=np.float32)
            for i, link in enumerate(links):
                idx = link.index
                f_row[i] = ep.ENgetlinkvalue(idx, _EN_FLOW)
                v_row[i] = ep.ENgetlinkvalue(idx, _EN_VELOCITY)
                # Also fill in _values ​​so that link.flow reads directly from cache
                link._values[_EN_FLOW]     = float(f_row[i])
                link._values[_EN_VELOCITY] = float(v_row[i])
            flows_list.append(f_row)
            vels_list.append(v_row)

            d_row = np.empty(n_n, dtype=np.float32)
            for i, node in enumerate(nodes):
                val = ep.ENgetnodevalue(node.index, _EN_DEMAND)
                d_row[i] = val if val is not None else 0.0
                node._values[_EN_DEMAND] = float(d_row[i])
            demands_list.append(d_row)

            if n_t > 0:
                vol_row = np.empty(n_t, dtype=np.float32)
                for j, ni in enumerate(tank_idx):
                    val = ep.ENgetnodevalue(nodes[ni].index, _EN_TANKVOLUME)
                    vol_row[j] = val if val is not None else 0.0
                volumes_list.append(vol_row)

        # Reset EPyNet solved-state so that net.solve() does not return cached answers
        self.net.solved = False

        self._flows   = np.array(flows_list,   dtype=np.float32)
        self._vels    = np.array(vels_list,    dtype=np.float32)
        self._demands = np.array(demands_list, dtype=np.float32)
        self._volumes = np.array(volumes_list, dtype=np.float32) if volumes_list else None
        self._precomputed = True

        print(f"HydraulicCache: {len(flows_list)} stappen gecached "
              f"({n_l} links × {n_n} nodes)")

    def apply(self, step: int) -> None:
        """
        Load the hydraulic values of time step 'step' into the EPyNet
        _values cache of each link/node object.

        After apply() returns link.flow, link.velocity, node.demand and
        node.volume only Python array lookups — no ctypes.

        Parameters
        ----------
        step : int
            Zero-based step index.
        """
        if not self._precomputed:
            raise RuntimeError("Call precompute() before apply()")

        # Limit the step index: an extra _build_adjacency call outside
        # the sim loop (e.g. for fill_network) otherwise causes IndexError.
        step = min(step, len(self._flows) - 1)

        f_row = self._flows[step]
        v_row = self._vels[step]
        d_row = self._demands[step]

        for i, link in enumerate(self._links):
            link._values[_EN_FLOW]     = float(f_row[i])
            link._values[_EN_VELOCITY] = float(v_row[i])

        for i, node in enumerate(self._nodes):
            node._values[_EN_DEMAND] = float(d_row[i])

        if self._volumes is not None:
            vol_row = self._volumes[step]
            for j, ni in enumerate(self._tank_idx):
                self._nodes[ni]._values[_EN_TANKVOLUME] = float(vol_row[j])

    @property
    def n_steps(self) -> int:
        """Number of time steps cached."""
        return len(self._flows) if self._flows is not None else 0

    def flows_at(self, step: int) -> Dict[str, float]:
        """Give flows at time step `step` as uid→flow dict."""
        row = self._flows[step]
        return {link.uid: float(row[i]) for i, link in enumerate(self._links)}

    def velocities_at(self, step: int) -> Dict[str, float]:
        """Give velocities at time step `step` as uid→velocity dict."""
        row = self._vels[step]
        return {link.uid: float(row[i]) for i, link in enumerate(self._links)}

class Solver:

    def __init__(self, models: Any, network: Any):
        self.models = models
        self.net    = network
        self.output: List = []
        self.filled_links: List = []

        # Precomputed adjacency — refreshed per step by _build_adjacency()
        self._up_links:   Dict[str, List[str]] = {}   # node_uid -> [link_uid,...]
        self._down_links: Dict[str, List[str]] = {}   # node_uid -> [link_uid,...]
        self._link_dn:    Dict[str, Any] = {}          # link_uid -> downstream node obj
        self._link_up:    Dict[str, Any] = {}          # link_uid -> upstream node obj

        # Cached hydraulic values ​​per step (uid -> value)
        self._flow:   Dict[str, float] = {}   # link_uid -> flow [m³/h]
        self._vel:    Dict[str, float] = {}   # link_uid -> velocity [m/s]

        # Ready-set
        self._ready: Set[str] = set()

        # Optional HydraulicCache for pre-computed hydraulics
        self._hcache: Optional[Any] = None
        self._hcache_step: int = 0

        #Fast uid -> object lookups
        self._link_obj: Dict[str, Any] = {l.uid: l for l in network.links}
        self._node_obj: Dict[str, Any] = {n.uid: n for n in network.nodes}

    # ── Adjacency + hydraulic cache ───────────────────────────────────────

    def set_hydraulic_cache(self, hcache: Any) -> None:
        """
        Attach a pre-computed HydraulicCache.
        This is called before the sim loop; the notebook explicitly calls
        _build_adjacency() after hcache.apply().
        """
        self._hcache = hcache
        self._hcache_step = 0

    def _build_adjacency(self) -> None:
        """
        Build upstream/downstream adjacency AND populate the EPyNet
        _values ​​cache of each link/node object containing the hydraulic values
        of the current time step.

        All ENgetlinkvalue / ENgetnodevalue calls happen here —
        exactly once per object per step. Then provide link.flow,
        link.velocity, node.demand, node.outflow and node.volume only
        another Python dict lookup (via BaseObject.get_property ->
        _values ​​cache hit).
        """
        ep = self.net.ep

        # If a HydraulicCache is available: load the pre-computed values
        # in the EPyNet _values ​​cache. The ENgetlinkvalue loop below reads
        # then output _values ​​(cache hit) instead of calling ctypes.
        if self._hcache is not None:
            self._hcache.apply(self._hcache_step)
            self._hcache_step += 1

        up:  Dict[str, List[str]] = {n.uid: [] for n in self.net.nodes}
        dn:  Dict[str, List[str]] = {n.uid: [] for n in self.net.nodes}
        lup: Dict[str, Any] = {}
        ldn: Dict[str, Any] = {}

        flow_cache: Dict[str, float] = {}
        vel_cache:  Dict[str, float] = {}

        # ── Links: flow + velocity + adjacency ────────────────────────────────
        _use_cache = self._hcache is not None

        for link in self.net.links:
            idx = link.index

            if _use_cache:
                # Values ​​already loaded by hcache.apply() — no ctypes
                flow = link._values.get(_EN_FLOW, 0.0)
                vel  = link._values.get(_EN_VELOCITY, 0.0)
            else:
                flow = ep.ENgetlinkvalue(idx, _EN_FLOW)
                vel  = ep.ENgetlinkvalue(idx, _EN_VELOCITY)
                link._values[_EN_FLOW]     = flow
                link._values[_EN_VELOCITY] = vel

            flow_cache[link.uid] = flow
            vel_cache[link.uid]  = vel

            # Stroomrichting bepalen op basis van flow-teken
            if flow >= 0:
                u_node, d_node = link.from_node, link.to_node
            else:
                u_node, d_node = link.to_node, link.from_node

            lup[link.uid] = u_node
            ldn[link.uid] = d_node

            # Determine flow direction based on flow sign
            if abs(vel) >= 0.001:
                up[d_node.uid].append(link.uid)
                dn[u_node.uid].append(link.uid)

        self._up_links   = up
        self._down_links = dn
        self._link_up    = lup
        self._link_dn    = ldn
        self._flow       = flow_cache
        self._vel        = vel_cache

        # ── Nodes: demand + volume (tank) + outflow (reservoir/tank) ──────────
        reservoir_uids = {r.uid for r in self.net.reservoirs}
        tank_uids      = {t.uid for t in self.net.tanks}

        for node in self.net.nodes:
            if not _use_cache:
                idx = node.index
                demand = ep.ENgetnodevalue(idx, _EN_DEMAND)
                if demand is not None:
                    node._values[_EN_DEMAND] = demand
                if node.uid in tank_uids:
                    vol = ep.ENgetnodevalue(idx, _EN_TANKVOLUME)
                    if vol is not None:
                        node._values[_EN_TANKVOLUME] = vol
            # If cache active: demands/volumes already filled by hcache.apply()

            # node.outflow — sum of downstream link flows [m³/h]
            # Used by Reservoir.mix and Tank.mix.
            # Not directly an EN property; calculated from the already-cached flows
            outflow = sum(abs(flow_cache[l_uid])
                          for l_uid in dn.get(node.uid, []))
            # Save as an attribute so that node.outflow returns it directly.
            # (Does not overwrite the EPyNet __getattr__ — which checks
            # 'outflow' not in properties; so object.__setattr__ works.)
            try:
                object.__setattr__(node, '_cached_outflow', outflow)
            except Exception:
                pass

    # ── Ready state ───────────────────────────────────────────────────────────

    def reset_ready_state(self) -> None:
        self._ready.clear()
        for lm in self.models.links.values():
            lm.ready = False

    # ── Iteratieve BFS trace ──────────────────────────────────────────────────

    def run_trace(self, start_node: Any, timestep: float, input_sol: Any) -> None:
        queue:   deque    = deque([start_node.uid])
        visited: Set[str] = set()

        while queue:
            node_uid = queue.popleft()
            if node_uid in visited:
                continue

            up_uids = self._up_links.get(node_uid, [])
            if not all(uid in self._ready for uid in up_uids):
                continue

            visited.add(node_uid)
            node = self._node_obj[node_uid]

            inflow = []
            for l_uid in up_uids:
                inflow.extend(self.models.links[l_uid].output_state)

            try:
                self.models.nodes[node_uid].mix(inflow, node, timestep, input_sol)
            except Exception as e:
                logger.error(f"Error mixing on node {node_uid}: {e}")
                raise

            node_model = self.models.nodes[node_uid]
            node_model.flowcount = 0

            for l_uid in self._down_links.get(node_uid, []):
                # Use cached flow — no ctypes
                flow_in  = round(abs(self._flow[l_uid]) / 3600 * timestep, 7)
                flow_cnt = node_model.flowcount

                try:
                    volumes = node_model.outflow[flow_cnt]
                    self.models.links[l_uid].push_pull(flow_in, volumes)
                    self._ready.add(l_uid)
                    self.models.links[l_uid].ready = True
                except IndexError:
                    logger.debug(
                        f"outflow[{flow_cnt}] missing for link {l_uid} — skipped"
                    )
                    continue
                except Exception as e:
                    logger.error(f"Error in push_pull for link {l_uid}: {e}")
                    raise

                node_model.flowcount += 1
                queue.append(self._link_dn[l_uid].uid)

    # ── Stroomrichtingscontrole ────────────────────────────────────────────────

    def check_connections(self) -> None:
        reversed_count = 0
        for link in self.net.links:
            lm    = self.models.links[link.uid]
            new_u = self._link_up.get(link.uid)
            new_d = self._link_dn.get(link.uid)
            if new_u is None or new_d is None:
                continue
            if lm.upstream_node is new_u and lm.downstream_node is new_d:
                continue
            lm.reverse_parcels(new_d, new_u)
            reversed_count += 1
        if reversed_count:
            logger.info(f"{reversed_count} links reversed due to flow direction change")

    # ── Iteratieve netwerk-fill ───────────────────────────────────────────────

    def fill_network(self, start_node: Any, input_sol: Any) -> None:
        queue:   deque    = deque([start_node.uid])
        visited: Set[str] = set()
        timestep = 60

        while queue:
            node_uid = queue.popleft()
            if node_uid in visited:
                continue

            up_uids = self._up_links.get(node_uid, [])
            if not all(uid in self._ready for uid in up_uids):
                continue

            visited.add(node_uid)
            node = self._node_obj[node_uid]

            inflow = []
            for l_uid in up_uids:
                inflow.extend(self.models.links[l_uid].output_state)

            try:
                self.models.nodes[node_uid].mix(inflow, node, timestep, input_sol)
            except Exception as e:
                logger.error(f"Error initializing node {node_uid}: {e}")
                raise

            node_outflow = self.models.nodes[node_uid].outflow

            for i, l_uid in enumerate(self._down_links.get(node_uid, [])):
                lm  = self.models.links[l_uid]
                sol = self._select_fill_solution(node_outflow, i, input_sol)
                lm.fill(sol)
                self._ready.add(l_uid)
                lm.ready = True
                self.filled_links.append(self._link_obj[l_uid])
                queue.append(self._link_dn[l_uid].uid)

    @staticmethod
    def _select_fill_solution(node_outflow: list, i: int, input_sol: Any) -> Any:
        if node_outflow and i < len(node_outflow) and node_outflow[i]:
            return node_outflow[i][0][1]
        elif node_outflow and node_outflow[0]:
            return node_outflow[0][0][1]
        else:
            candidate = input_sol.get(0, None)
            if candidate is None:
                for v in input_sol.values():
                    if hasattr(v, 'number'):
                        candidate = v
                        break
            if candidate is None:
                raise KeyError("No valid solution object in input_sol for fallback fill")
            return {candidate.number: 1.0}

    # ── Backwards compatibility ─────────────────────────────────────────

    def _get_links(self, node: Any, direction: str) -> list:
        uids = (self._up_links if direction == 'upstream' else self._down_links).get(node.uid, [])
        return [self._link_obj[u] for u in uids]

    def _get_node_attr(self, obj: Any, attr: str) -> Any:
        v = getattr(obj, attr)
        return v() if callable(v) else v

    def _all_upstream_links_ready(self, node: Any) -> bool:
        return all(uid in self._ready for uid in self._up_links.get(node.uid, []))
