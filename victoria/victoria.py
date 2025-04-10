from .solver import Solver
from .quality import Quality
from .models import Models


class Victoria(object):

    def __init__(self, network, pp):
        self.net = network
        self.models = Models(network)
        self.solver = Solver(self.models, network)
        self.quality = Quality(pp, self.models)
        self.output = []
        self.pp = pp

    def step(self, timestep, input_sol):
        # Solve the volume fractions for the whole network for one timestep
        # Run trace starting at each reservoir node

        for emitter in self.net.reservoirs:
            self.solver.run_trace(emitter, timestep, input_sol)

        for link in self.net.links:
            self.solver.models.links[link.uid].ready = False

    def fill_network(self, input_sol, from_reservoir=True):
        # Fill the network with initial solution
        if from_reservoir is True:
            # Fill the whole network with reservoir solution, while
            # considering the mix ratio. Links not filled with run_trace
            # are filled with a standard solution
            for emitter in self.net.reservoirs:
                try:
                    self.solver.fill_network(emitter, input_sol)
                except KeyError:
                    print('No solution defined for reservoir', emitter)
                    raise
            # Construct set of links unfilled links
            link_list = [link for link in self.net.pipes]
            link_filled = self.solver.filled_links
            unfilled = set(link_list) - set(link_filled)
            # Fill links with standard solution
            try:
                for link in unfilled:
                    q = {}
                    q[input_sol[0].number] = 1
                    self.solver.models.pipes[link.uid].fill(q)
            except KeyError:
                print('No initial solution defined for 0')
                raise
            # Reset ready state
            for link in self.net.links:
                self.solver.models.links[link.uid].ready = False

        else:
            print
            # Fill the whole network with an initial solution
            try:
                for pipe in self.net.pipes:
                    q = {}
                    q[input_sol[0].number] = 1
                    self.solver.models.pipes[pipe.uid].fill(q)
            except KeyError:
                print('No initial solution defined, solution for Key = 0')
                raise

    def check_flow_direction(self):
        # Compares the current flow direction with the previous flow direction,
        # reverses the list if required
        self.solver.check_connections()

    def garbage_collect(self):
        self.registered_solutions = []
        for pipe in self.solver.models.pipes.values():
            for parcel in pipe.state:
                for i in parcel['q']:
                    self.registered_solutions.append(i)

        registered_solutions = set(self.registered_solutions)
        phreeqc_solutions = set(self.pp.get_solution_list())
        to_forget = phreeqc_solutions - registered_solutions
        if len(to_forget) > 0:
            self.pp.remove_solutions(to_forget)

    def get_conc_node(self, node, element, units='mmol'):
        # Calculate the concentration of desired species exiting the node
        # at this exact moment
        return self.quality.get_conc_node(node, element, units)

    def get_conc_node_avg(self, node, element, units='mmol'):
        # Calculate the average concentration of a species exitting
        # the node during the last timestep
        return self.quality.get_conc_node_avg(node, element, units)

    def get_mixture_node(self, node):
        # Return the PHREEQC solution number with its respective
        # volume fraction
        return self.quality.get_mixture_node(node)

    def get_mixture_node_avg(self, node):
        # Return the PHREEQC solution number with its respective
        # volume fraction averaged over the last timestep
        return self.quality.get_mixture_node_avg(node)

    def get_conc_pipe(self, link, element, units='mmol'):
        # Calculate the concentration of the element in each parcel in a pipe
        return self.quality.get_conc_pipe(link, element, units)

    def get_conc_pipe_avg(self, link, element, units='mmol'):
        # Calculate the average concentration of an element over the whole pipe
        return self.quality.get_conc_pipe_avg(link, element, units)

    def get_parcels(self, link):
        # Return the parcels in a pipe
        return self.quality.get_parcels(link)

    def get_properties_node(self, node):
        # Returns the pH, specific condunctivity and temperature exiting
        # the node at this moment
        return self.quality.get_properties_node(node)

    def get_properties_node_avg(self, node):
        # Returns the pH, specific condnctivity and temperature averaged
        # over the last timestep
        return self.quality.get_properties_node_avg(node)
