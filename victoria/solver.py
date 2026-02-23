"""
Solver module — geoptimaliseerde versie 2.

Wijzigingen t.o.v. v1:
  1. _build_adjacency vult de EPyNet _values-cache van elk link- en node-object
     via directe ENgetlinkvalue / ENgetnodevalue aanroepen. Daarna leveren
     link.flow, link.velocity, node.demand, node.outflow en node.volume
     alleen nog een dict-lookup op — geen ctypes meer in de traversal-lus.
  2. node.outflow (voor reservoir en tank) wordt berekend als som van de
     stroomafwaartse link-flows uit de al-gecachede flow-dict.
  3. Iteratieve BFS en precomputed adjacency (uit v1) blijven intact.
  4. ready-state als set (O(1) clear).

Benodigde EPANET property-codes (uit epynet/epanet2.py):
  EN_FLOW      = 8   (link, read only)
  EN_VELOCITY  = 9   (link, read only)
  EN_DEMAND    = 9   (node, read only)
  EN_TANKVOLUME= 24  (node, read only)
"""

from collections import deque
from typing import Any, Dict, List, Set
import logging

logger = logging.getLogger(__name__)

# EPANET property codes — gespiegeld van epynet/epanet2.py zodat de solver
# geen import-afhankelijkheid van epynet heeft.
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

        # Precomputed adjacency — vernieuwd per stap door _build_adjacency()
        self._up_links:   Dict[str, List[str]] = {}   # node_uid -> [link_uid,...]
        self._down_links: Dict[str, List[str]] = {}   # node_uid -> [link_uid,...]
        self._link_dn:    Dict[str, Any] = {}          # link_uid -> downstream node obj
        self._link_up:    Dict[str, Any] = {}          # link_uid -> upstream node obj

        # Gecachede hydraulische waarden per stap (uid -> waarde)
        self._flow:   Dict[str, float] = {}   # link_uid -> flow [m³/h]
        self._vel:    Dict[str, float] = {}   # link_uid -> velocity [m/s]

        # Ready-set
        self._ready: Set[str] = set()

        # Snelle uid -> object lookups
        self._link_obj: Dict[str, Any] = {l.uid: l for l in network.links}
        self._node_obj: Dict[str, Any] = {n.uid: n for n in network.nodes}

    # ── Adjacency + hydraulische cache ───────────────────────────────────────

    def _build_adjacency(self) -> None:
        """
        Bouw stroomopwaarts/stroomafwaarts adjacency op EN vul de EPyNet
        _values-cache van elk link/node-object met de hydraulische waarden
        van de huidige tijdstap.

        Alle ENgetlinkvalue / ENgetnodevalue aanroepen gebeuren hier —
        precies één keer per object per stap. Daarna leveren link.flow,
        link.velocity, node.demand, node.outflow en node.volume alleen
        nog een Python dict-lookup op (via BaseObject.get_property ->
        _values cache hit).
        """
        ep = self.net.ep

        up:  Dict[str, List[str]] = {n.uid: [] for n in self.net.nodes}
        dn:  Dict[str, List[str]] = {n.uid: [] for n in self.net.nodes}
        lup: Dict[str, Any] = {}
        ldn: Dict[str, Any] = {}

        flow_cache: Dict[str, float] = {}
        vel_cache:  Dict[str, float] = {}

        # ── Links: flow + velocity + adjacency ────────────────────────────────
        for link in self.net.links:
            idx  = link.index                              # gecached na eerste aanroep
            flow = ep.ENgetlinkvalue(idx, _EN_FLOW)       # 1× ctypes
            vel  = ep.ENgetlinkvalue(idx, _EN_VELOCITY)   # 1× ctypes

            # Vul EPyNet _values-cache: daarna geeft link.flow / link.velocity
            # een cache-hit zonder extra ctypes-aanroep.
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

            # Alleen links met noemenswaardig debiet in de adjacency opnemen
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
            idx = node.index   # gecached

            # node.demand (EN_DEMAND=9) — gebruikt door Junction.mix
            demand = ep.ENgetnodevalue(idx, _EN_DEMAND)
            if demand is not None:
                node._values[_EN_DEMAND] = demand

            if node.uid in tank_uids:
                # node.volume (EN_TANKVOLUME=24) — gebruikt door Tank_CSTR.mix
                vol = ep.ENgetnodevalue(idx, _EN_TANKVOLUME)
                if vol is not None:
                    node._values[_EN_TANKVOLUME] = vol

            # node.outflow — som van stroomafwaartse link-flows [m³/h]
            # Wordt gebruikt door Reservoir.mix en Tank.mix.
            # Niet direct een EN-property; berekend uit de al-gecachede flows.
            outflow = sum(abs(flow_cache[l_uid])
                          for l_uid in dn.get(node.uid, []))
            # Sla op als attribuut zodat node.outflow dit direct retourneert.
            # (Overschrijft de EPyNet __getattr__ niet — die controleert
            #  'outflow' niet in properties; dus object.__setattr__ werkt.)
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
                logger.error(f"Fout bij mixen op node {node_uid}: {e}")
                raise

            node_model = self.models.nodes[node_uid]
            node_model.flowcount = 0

            for l_uid in self._down_links.get(node_uid, []):
                # Gebruik gecachede flow — geen ctypes
                flow_in  = round(abs(self._flow[l_uid]) / 3600 * timestep, 7)
                flow_cnt = node_model.flowcount

                try:
                    volumes = node_model.outflow[flow_cnt]
                    self.models.links[l_uid].push_pull(flow_in, volumes)
                    self._ready.add(l_uid)
                    self.models.links[l_uid].ready = True
                except IndexError:
                    logger.debug(
                        f"outflow[{flow_cnt}] ontbreekt voor link {l_uid} — overgeslagen"
                    )
                    continue
                except Exception as e:
                    logger.error(f"Fout in push_pull voor link {l_uid}: {e}")
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
            logger.info(f"{reversed_count} links omgekeerd wegens stroomwijziging")

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
                logger.error(f"Fout bij initialiseren node {node_uid}: {e}")
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
                raise KeyError("Geen geldig solution-object in input_sol voor fallback fill")
            return {candidate.number: 1.0}

    # ── Achterwaartse compatibiliteit ─────────────────────────────────────────

    def _get_links(self, node: Any, direction: str) -> list:
        uids = (self._up_links if direction == 'upstream' else self._down_links).get(node.uid, [])
        return [self._link_obj[u] for u in uids]

    def _get_node_attr(self, obj: Any, attr: str) -> Any:
        v = getattr(obj, attr)
        return v() if callable(v) else v

    def _all_upstream_links_ready(self, node: Any) -> bool:
        return all(uid in self._ready for uid in self._up_links.get(node.uid, []))
