"""
Solver module for water quality simulation.

This module implements the main calculation loop for tracing water
parcels through the hydraulic network.
"""
from typing import List, Any, Set
import logging

logger = logging.getLogger(__name__)


class Solver:
    """
    Main solver for water quality calculations.
    
    Traces water parcels through the network based on hydraulic simulation
    results from EPyNet.
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
        
        Some EPyNet versions have upstream_links/downstream_links as methods,
        others as properties. This handles both.
        
        Args:
            node: Node object
            direction: 'upstream' or 'downstream'
            
        Returns:
            List of links
        """
        attr = f'{direction}_links'
        links = getattr(node, attr)
        # If it's a method, call it
        if callable(links):
            return links()
        # Otherwise it's already a list/iterable
        return links
    
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
        if callable(value):
            return value()
        return value

    def run_trace(self, node: Any, timestep: float, input_sol: Any) -> None:
        """
        Recursively trace water parcels from a node through the network.
        
        Args:
            node: Starting node
            timestep: Simulation timestep in seconds
            input_sol: Dictionary of input solutions
        """
        # Check if all upstream links are ready
        upstream_links = self._get_links(node, 'upstream')
        ready = all(
            self.models.links[link.uid].ready 
            for link in upstream_links
        )
        if not ready:
            return

        # Gather parcels from all upstream links
        inflow = []
        for link in upstream_links:
            link_model = self.models.links[link.uid]
            inflow.extend(link_model.output_state)

        # Mix parcels at the node
        try:
            self.models.nodes[node.uid].mix(inflow, node, timestep, input_sol)
        except Exception as e:
            logger.error(f"Error mixing at node {node.uid}: {e}")
            raise

        # Initialize flow counter for this node
        if not hasattr(self.models.nodes[node.uid], 'flowcount'):
            self.models.nodes[node.uid].flowcount = 0
        else:
            self.models.nodes[node.uid].flowcount = 0

        # Process each downstream link
        downstream_links = self._get_links(node, 'downstream')
        for link in downstream_links:
            # Skip links with very low velocity
            if link.velocity < 0.001:
                logger.debug(f"Skipping link {link.uid} due to low velocity")
                # Bug fix 3: do NOT increment flowcount here — the outflow slot
                # for this link was never consumed, so skipping it would shift
                # all subsequent indices by one and cause an IndexError on the
                # next link that does have flow.
                continue

            flow_cnt = self.models.nodes[node.uid].flowcount
            flow_in = round(abs(link.flow) / 3600 * timestep, 7)

            # Push and pull parcels through the link
            try:
                volumes = self.models.nodes[node.uid].outflow[flow_cnt]
                self.models.links[link.uid].push_pull(flow_in, volumes)
                self.models.links[link.uid].ready = True
            except IndexError:
                # outflow has fewer slots than active downstream links —
                # this can happen at a junction whose parcels_out produced
                # fewer entries than expected (e.g. all-zero mixed_parcels).
                # Skip this link gracefully rather than crashing.
                logger.debug(
                    f"outflow[{flow_cnt}] missing for link {link.uid} at node "
                    f"{node.uid} — skipping (zero-flow parcel path)"
                )
                continue
            except Exception as e:
                logger.error(f"Error in push_pull for link {link.uid}: {e}")
                raise

            # Continue trace from downstream node
            self.models.nodes[node.uid].flowcount += 1
            downstream_node = self._get_node_attr(link, 'downstream_node')
            self.run_trace(downstream_node, timestep, input_sol)

    def check_connections(self) -> None:
        """
        Check if flow direction has changed and reverse parcels if needed.
        
        This should be called after each hydraulic timestep to handle
        flow reversals.
        """
        reversed_count = 0
        
        for link in self.net.links:
            link_model = self.models.links[link.uid]
            
            # Check if flow direction has changed
            if (link.upstream_node == link_model.upstream_node and
                link.downstream_node == link_model.downstream_node):
                continue
            else:
                # Flow direction has reversed
                link_model.reverse_parcels(
                    link.downstream_node,
                    link.upstream_node
                )
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
        upstream_links = self._get_links(node, 'upstream')
        ready = all(
            self.models.links[link.uid].ready 
            for link in upstream_links
        )
        if not ready:
            return

        # Gather parcels from upstream (should be empty initially)
        inflow = []
        for link in upstream_links:
            link_model = self.models.links[link.uid]
            inflow.extend(link_model.output_state)

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
                # Bug fix 1: outflow may be empty when a junction has zero total
                # downstream flow (dead-end, closed valve, near-zero velocity).
                # In that case fall back to the default background solution.
                # Bug fix 2: use outflow[i] not outflow[0] — junctions with
                # multiple downstream pipes produce one outflow slot per pipe.
                if node_outflow and i < len(node_outflow) and node_outflow[i]:
                    sol = node_outflow[i][0][1]
                elif node_outflow and node_outflow[0]:
                    # Reservoir always produces a single slot; reuse it for
                    # every downstream link.
                    sol = node_outflow[0][0][1]
                else:
                    # Zero-flow node — fill with default background solution
                    logger.debug(
                        f"Node {node.uid} outflow empty for link {link.uid}, "
                        f"using default background solution (key=0)"
                    )
                    sol = {input_sol[0].number: 1.0}

                # Fill the link
                self.models.links[link.uid].fill(sol)
                self.models.links[link.uid].ready = True

                # Track filled links
                self.filled_links.append(link)

                # Continue filling downstream
                downstream_node = self._get_node_attr(link, 'downstream_node')
                self.fill_network(downstream_node, input_sol)

            except Exception as e:
                logger.error(f"Error filling link {link.uid}: {e}")
                raise

    def reset_ready_state(self) -> None:
        """Reset the ready state of all links."""
        for link in self.net.links:
            self.models.links[link.uid].ready = False
