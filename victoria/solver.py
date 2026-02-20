"""
Solver module for water quality simulation.
This module implements the main calculation loop for tracing water parcels through the hydraulic network.
"""

from typing import List, Any
import logging

logger = logging.getLogger(__name__)


class Solver:
    """
    Main solver for water quality calculations.
    Traces water parcels through the network based on hydraulic simulation results from EPyNet.
    """

    def __init__(self, models: Any, network: Any):
        """
        Initialize solver.
        Args:
            models: Models instance containing all network components
            network: EPyNet network object
        """
        self.models = models
        self.net = network
        self.output: List = []
        self.filled_links: List = []

    def _get_links(self, node: Any, direction: str) -> list:
        """
        Get upstream or downstream links, handling both EPyNet API styles.

        Args:
            node: Node object
            direction: 'upstream' or 'downstream'
        Returns:
            List of links
        """
        links_attr = f'{direction}_links'
        links = getattr(node, links_attr)
        return links() if callable(links) else links

    def _get_node_attr(self, obj: Any, attr: str) -> Any:
        """
        Get node/link attribute, handling both methods and properties.

        Args:
            obj: Object to get attribute from
            attr: Attribute name
        Returns:
            Attribute value
        """
        value = getattr(obj, attr)
        return value() if callable(value) else value

    def _all_upstream_links_ready(self, node: Any) -> bool:
        """Helper to check if all upstream links for a node are ready."""
        upstream_links = self._get_links(node, 'upstream')
        return all(self.models.links[link.uid].ready for link in upstream_links)

    def _gather_inflow(self, upstream_links) -> list:
        """Gather parcels from all upstream links."""
        inflow = []
        for link in upstream_links:
            link_model = self.models.links[link.uid]
            inflow.extend(link_model.output_state)
        return inflow

    def run_trace(self, node: Any, timestep: float, input_sol: Any) -> None:
        """
        Recursively trace water parcels from a node through the network.

        Args:
            node: Starting node
            timestep: Simulation timestep in seconds
            input_sol: Dictionary of input solutions
        """
        # Check if all upstream links are ready
        if not self._all_upstream_links_ready(node):
            return

        # Gather inflow from upstream
        upstream_links = self._get_links(node, 'upstream')
        inflow = self._gather_inflow(upstream_links)

        # Mix parcels at the node
        try:
            self.models.nodes[node.uid].mix(inflow, node, timestep, input_sol)
        except Exception as e:
            logger.error(f"Error mixing at node {node.uid}: {e}")
            raise

        # Initialize or reset flow counter for this node
        self.models.nodes[node.uid].flowcount = 0

        # Process each downstream link
        downstream_links = self._get_links(node, 'downstream')
        for link in downstream_links:
            # Skip links with very low velocity
            if link.velocity < 0.001:
                logger.debug(f"Skipping link {link.uid} due to low velocity")
                continue  # Do NOT increment flowcount here

            node_model = self.models.nodes[node.uid]
            flow_cnt = node_model.flowcount
            flow_in = round(abs(link.flow) / 3600 * timestep, 7)

            try:
                volumes = node_model.outflow[flow_cnt]

                self.models.links[link.uid].push_pull(flow_in, volumes)
                self.models.links[link.uid].ready = True
            except IndexError:
                logger.debug(
                    f"outflow[{flow_cnt}] missing for link {link.uid} at node "
                    f"{node.uid} — skipping (zero-flow parcel path)"
                )
                continue
            except Exception as e:
                logger.error(f"Error in push_pull for link {link.uid}: {e}")
                raise

            node_model.flowcount += 1
            downstream_node = self._get_node_attr(link, 'downstream_node')
            self.run_trace(downstream_node, timestep, input_sol)

    def check_connections(self) -> None:
        """
        Check if flow direction has changed and reverse parcels if needed.
        This should be called after each hydraulic timestep to handle flow reversals.
        """
        reversed_count = 0
        for link in self.net.links:
            link_model = self.models.links[link.uid]
            # Check if flow direction has changed
            if (link.upstream_node == link_model.upstream_node and
                link.downstream_node == link_model.downstream_node):
                continue

            # Flow direction has reversed
            link_model.reverse_parcels(link.downstream_node, link.upstream_node)
            reversed_count += 1

        if reversed_count > 0:
            logger.info(f"Reversed {reversed_count} links due to flow changes")

    def fill_network(self, node: Any, input_sol: Any) -> None:
        """
        Recursively fill the network from a source node.

        Args:
            node: Source node (usually reservoir)
            input_sol: Dictionary of input solutions
        """
        # Check if all upstream links are ready
        if not self._all_upstream_links_ready(node):
            return

        # Gather parcels from upstream (should be empty initially)
        upstream_links = self._get_links(node, 'upstream')
        inflow = self._gather_inflow(upstream_links)

        # Mix at node (generates initial solution for reservoirs)
        timestep = 60  # Use 1 minute for initialization
        try:
            self.models.nodes[node.uid].mix(inflow, node, timestep, input_sol)
        except Exception as e:
            logger.error(f"Error filling node {node.uid}: {e}")
            raise

        # Fill all downstream links
        downstream_links = self._get_links(node, 'downstream')
        node_outflow = self.models.nodes[node.uid].outflow

        for i, link in enumerate(downstream_links):
            try:
                # Select the appropriate solution for the link
                sol = self._select_fill_solution(node_outflow, i, input_sol)
                self.models.links[link.uid].fill(sol)
                self.models.links[link.uid].ready = True
                self.models.links[link.uid].connections(
                    self._get_node_attr(link, 'downstream_node'),
                    self._get_node_attr(link, 'upstream_node')
                )
                self.filled_links.append(link)

                downstream_node = self._get_node_attr(link, 'downstream_node')
                self.fill_network(downstream_node, input_sol)
            except Exception as e:
                logger.error(f"Error filling link {link.uid}: {e}")
                raise

    @staticmethod
    def _select_fill_solution(node_outflow: list, i: int, input_sol: Any) -> Any:
        """
        Determines which solution should be used to fill the link based on node outflow.
        Handles edge cases for zero-flow, multiple links, etc.
        """
        # case: normal outflow per link
        if node_outflow and i < len(node_outflow) and node_outflow[i]:
            return node_outflow[i][0][1]
        # case: single outflow slot, e.g., reservoir
        elif node_outflow and node_outflow[0]:
            return node_outflow[0][0][1]
        # case: zero-flow node
        else:
            logger.debug(
                f"Outflow empty for downstream link index={i}, using default background solution (key=0)"
            )
            return {input_sol[0].number: 1.0}

    def reset_ready_state(self) -> None:
        """Reset the ready state of all links."""
        for link in self.net.links:
            self.models.links[link.uid].ready = False
