"""
Solver module — optimized version 2.

Changes compared to v1:
  1. _build_adjacency fills the EPyNet _values ​​cache of each link and node object
     via direct ENgetlinkvalue / ENgetnodevalue calls. Then deliver
     link.flow, link.velocity, node.demand, node.outflow and node.volume
     just a dict lookup — no more ctypes in the traversal loop.
  2. node.outflow (for reservoir and tank) is calculated as the sum of the
     downstream link flows from the already cached flow dict.
  3. Iterative BFS and precomputed adjacency (from v1) remain intact.
  4. ready-state as set (O(1) clear).

Required EPANET property codes (from epynet/epanet2.py):
  EN_FLOW = 8 (link, read only)
  EN_VELOCITY = 9 (link, read only)
  EN_DEMAND = 9 (node, read only)
  EN_TANKVOLUME= 24 (node, read only)
"""

from collections import deque
from typing import Any, Dict, List, Optional, Set
import logging

logger = logging.getLogger(__name__)

# EPANET property codes — mirrored from epynet/epanet2.py so that the solver
# has no import dependency on epynet.
_EN_FLOW       = 8
_EN_VELOCITY   = 9
_EN_DEMAND     = 9
_EN_TANKVOLUME = 24


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

        # Snelle uid -> object lookups
        self._link_obj: Dict[str, Any] = {l.uid: l for l in network.links}
        self._node_obj: Dict[str, Any] = {n.uid: n for n in network.nodes}

    # ── Adjacency + hydraulische cache ───────────────────────────────────────

    def set_hydraulic_cache(self, hcache: Any) -> None:
        """
        Attach a pre-computed HydraulicCache.
        Called before the sim loop; the notebook calls
        _build_adjacency() explicitly after hcache.apply().
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

            # Determine flow direction based on flow sign
            if flow >= 0:
                u_node, d_node = link.from_node, link.to_node
            else:
                u_node, d_node = link.to_node, link.from_node

            lup[link.uid] = u_node
            ldn[link.uid] = d_node

            # Include only links with significant throughput in the adjacency
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
            # If cache is active: demands/volumes already filled by hcache.apply()

            # node.outflow — sum of downstream link flows [m³/h]
            # Used by Reservoir.mix and Tank.mix.
            # Not directly an EN property; calculated from already cached flows.
            outflow = sum(abs(flow_cache[l_uid])
                          for l_uid in dn.get(node.uid, []))
            # Save this as an attribute so node.outflow returns it directly.
            # (Doesn't overwrite the EPyNet __getattr__ — it checks
            # 'outflow' in properties; so object.__setattr__ works.)
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

    # ── Flow direction control ────────────────────────────────────────────────

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

    # ── Iterative network fill ───────────────────────────────────────────────

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
                raise KeyError("No valid solution-object in input_sol for fallback fill")
            return {candidate.number: 1.0}

    # ── Backward compatibility ─────────────────────────────────────────

    def _get_links(self, node: Any, direction: str) -> list:
        uids = (self._up_links if direction == 'upstream' else self._down_links).get(node.uid, [])
        return [self._link_obj[u] for u in uids]

    def _get_node_attr(self, obj: Any, attr: str) -> Any:
        v = getattr(obj, attr)
        return v() if callable(v) else v

    def _all_upstream_links_ready(self, node: Any) -> bool:
        return all(uid in self._ready for uid in self._up_links.get(node.uid, []))
