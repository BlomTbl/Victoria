from models import Models


class Solver(object):
    # Solves the main calculation loop for water quality.
    # requires a solved epynet network as input

    def __init__(self, network, sol_dict, pp):
        self.output = []
        self.sol_dict = sol_dict
        # Construct model
        self.models = Models(network, self.sol_dict)

    def step(self, network, timestep, sol_dict):
        # Solve the volume fractions for the whole network for one timestep
        # Loop over all nodes reservoir nodes
        for emitter in network.nodes[network.nodes.inflow == 0]:
            nodetype = 'emitter'
            self.run_trace(emitter, nodetype, timestep, sol_dict)

        for link in network.links:
            self.models.pipes[link.uid[0]].ready = False

    def run_trace(self, startnode, node_type, timestep, sol_dict):
        # Check whether all upstream pipes are ready
        ready = all(list(self.models.pipes[link.uid[0]].ready for link in startnode.upstream_links))
        if not ready:
            return

        # Check type of node
        if node_type == 'emitter':
            shift_volume = timestep * startnode.outflow/60
            self.models.nodes[startnode.uid].emitter(startnode, shift_volume, sol_dict)

        if node_type == 'junction':
            # Collect all parcels flowing into the node
            inflow = []
            for link in startnode.upstream_links:
                inflow += self.models.pipes[link.uid].output_state
            # Mix the parcels at the node
            demand = startnode.demand/60 * timestep
            self.models.nodes[startnode.uid].mix(inflow, demand)
            # Assign downstream outflow matrix
            outflow = [abs(link.flow) for link in startnode.downstream_links]
            # Calculate the parcel size flowing to the downstream pipes
            self.models.nodes[startnode.uid].parcels_out(outflow)
        flowcount = 0

        for link in startnode.downstream_links:
            # Push the parcels in the pipe and pull them
            self.models.pipes[link.uid].push_pull(self.models.nodes[startnode.uid].outflow[flowcount])
            # Merge neighbouring parcels with identical PHREEQC solution matrix
            self.models.pipes[link.uid].merge_parcels()
            # Update ready state of the pipe
            self.models.pipes[link.uid].ready = True
            # Run trace from downstream node

            flowcount += 1
            self.run_trace(link.downstream_node, 'junction', timestep, sol_dict)
