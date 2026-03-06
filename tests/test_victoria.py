"""
Test suite for the victoria water quality simulation package.

Run with:
    pytest tests/test_victoria.py -v
    pytest tests/test_victoria.py -v --cov=victoria --cov-report=term-missing

Modules covered:
    - victoria.fifo      : FIFO, Pipe, ZeroLengthFIFO, Pump, Valve
    - victoria.mix       : MIX, Junction, Reservoir, Tank_CSTR, Tank_FIFO, Tank_LIFO
    - victoria.models    : Models
    - victoria.quality   : Quality
    - victoria.segmentation : PipeSegmentation
    - victoria.solver    : Solver (_select_fill_solution, check_connections, reset_ready_state)
    - victoria           : package-level imports and __version__
"""

import math
import pytest
from unittest.mock import MagicMock, patch, PropertyMock


# ---------------------------------------------------------------------------
# Helpers — lightweight mocks that stand in for EPyNet objects
# ---------------------------------------------------------------------------

def _make_link(uid, flow=1.0, velocity=0.5, upstream_node=None, downstream_node=None):
    """Return a mock link object."""
    link = MagicMock()
    link.uid = uid
    link.flow = flow
    link.velocity = velocity
    link.upstream_node = upstream_node or MagicMock(uid=f'{uid}_up')
    link.downstream_node = downstream_node or MagicMock(uid=f'{uid}_dn')
    return link


def _make_node(uid, demand=0.0, outflow=0.0, upstream_links=None, downstream_links=None):
    """Return a mock node (junction/reservoir) object."""
    node = MagicMock()
    node.uid = uid
    node.demand = demand
    node.outflow = outflow
    node.upstream_links = upstream_links or []
    node.downstream_links = downstream_links or []
    return node


def _make_pipe_object(uid, length=100.0, diameter=200.0):
    """Return a mock epynet pipe object."""
    pipe = MagicMock()
    pipe.uid = uid
    pipe.length = length
    pipe.diameter = diameter
    return pipe


# ---------------------------------------------------------------------------
# victoria package — import and version
# ---------------------------------------------------------------------------

class TestPackageImport:
    def test_version(self):
        import victoria
        assert victoria.__version__ == '1.1.0'

    def test_all_public_classes_importable(self):
        from victoria import (
            Victoria, Models, Solver, Quality, PipeSegmentation,
            FIFO, Pipe, Pump, Valve,
            MIX, Junction, Reservoir, Tank_CSTR, Tank_FIFO, Tank_LIFO,
        )
        for cls in (Victoria, Models, Solver, Quality, PipeSegmentation,
                    FIFO, Pipe, Pump, Valve, MIX, Junction, Reservoir,
                    Tank_CSTR, Tank_FIFO, Tank_LIFO):
            assert cls is not None

    def test_all_exports_in_dunder_all(self):
        import victoria
        for name in victoria.__all__:
            assert hasattr(victoria, name), f"'{name}' listed in __all__ but not importable"


# ---------------------------------------------------------------------------
# fifo.py — Parcel dataclass
# ---------------------------------------------------------------------------

class TestParcel:
    def test_to_dict(self):
        from victoria.fifo import Parcel
        p = Parcel(x0=0.0, x1=0.5, q={1: 1.0})
        d = p.to_dict()
        assert d == {'x0': 0.0, 'x1': 0.5, 'q': {1: 1.0}}


# ---------------------------------------------------------------------------
# fifo.py — FIFO base class
# ---------------------------------------------------------------------------

class TestFIFO:
    def test_initial_state(self):
        from victoria.fifo import FIFO
        f = FIFO(volume=10.0)
        assert f.volume == 10.0
        assert f.state == []
        assert f.output_state == []
        assert f.ready is False
        assert f.downstream_node is None
        assert f.upstream_node is None

    def test_connections(self):
        from victoria.fifo import FIFO
        f = FIFO()
        up = MagicMock()
        dn = MagicMock()
        f.connections(dn, up)
        assert f.downstream_node is dn
        assert f.upstream_node is up

    def test_reverse_parcels_flips_positions(self):
        from victoria.fifo import FIFO
        f = FIFO(volume=1.0)
        f.state = [
            {'x0': 0.0, 'x1': 0.4, 'q': {1: 1.0}},
            {'x0': 0.4, 'x1': 1.0, 'q': {2: 1.0}},
        ]
        new_dn = MagicMock()
        new_up = MagicMock()
        f.reverse_parcels(new_dn, new_up)
        # Positions should be mirrored around 0.5
        xs = [(p['x0'], p['x1']) for p in f.state]
        assert all(0.0 <= x0 <= 1.0 and 0.0 <= x1 <= 1.0 for x0, x1 in xs)
        assert f.downstream_node is new_dn
        assert f.upstream_node is new_up

    def test_reverse_parcels_sorted_by_x1(self):
        from victoria.fifo import FIFO
        f = FIFO(volume=1.0)
        f.state = [
            {'x0': 0.0, 'x1': 0.3, 'q': {1: 1.0}},
            {'x0': 0.3, 'x1': 0.7, 'q': {2: 1.0}},
            {'x0': 0.7, 'x1': 1.0, 'q': {3: 1.0}},
        ]
        f.reverse_parcels(MagicMock(), MagicMock())
        x1s = [p['x1'] for p in f.state]
        assert x1s == sorted(x1s)

    def test_push_in_zero_volume(self):
        from victoria.fifo import FIFO
        f = FIFO(volume=0.0)
        f.push_in([[5.0, {1: 1.0}]])
        assert f.state == []  # volume=0 means nothing stored

    def test_push_in_creates_parcel(self):
        from victoria.fifo import FIFO
        f = FIFO(volume=10.0)
        f.push_in([[2.0, {1: 1.0}]])
        assert len(f.state) == 1
        assert f.state[0]['x0'] == 0.0
        assert pytest.approx(f.state[0]['x1']) == 0.2

    def test_push_in_merges_identical_quality(self):
        from victoria.fifo import FIFO
        f = FIFO(volume=10.0)
        q = {1: 1.0}
        f.push_in([[2.0, q]])
        f.push_in([[3.0, q]])
        # Second push should merge with existing front parcel
        assert len(f.state) == 1

    def test_push_in_creates_new_parcel_for_different_quality(self):
        from victoria.fifo import FIFO
        f = FIFO(volume=10.0)
        f.push_in([[2.0, {1: 1.0}]])
        f.push_in([[3.0, {2: 1.0}]])
        assert len(f.state) == 2


# ---------------------------------------------------------------------------
# fifo.py — Pipe
# ---------------------------------------------------------------------------

class TestPipe:
    def _filled_pipe(self, volume=10.0, sol=None):
        from victoria.fifo import Pipe
        p = Pipe(volume=volume)
        p.fill(sol or {1: 1.0})
        return p

    def test_fill_sets_full_state(self):
        from victoria.fifo import Pipe
        p = Pipe(volume=5.0)
        p.fill({1: 1.0})
        assert p.state == [{'x0': 0, 'x1': 1, 'q': {1: 1.0}}]
        assert p.output_state[0]['volume'] == 5.0

    def test_push_pull_no_flow_returns_ready(self):
        p = self._filled_pipe()
        p.push_pull(0.0, [[1.0, {2: 1.0}]])
        assert p.ready is True
        assert p.output_state == []

    def test_push_pull_empty_volumes_returns_ready(self):
        p = self._filled_pipe()
        p.push_pull(1.0, [])
        assert p.ready is True

    def test_push_pull_produces_output(self):
        """Pushing more than the pipe volume should flush parcels out."""
        p = self._filled_pipe(volume=1.0)  # 1 m³ pipe already full with sol 1
        # Push 1 m³ of sol 2 — sol 1 should exit
        p.push_pull(1.0, [[1.0, {2: 1.0}]])
        assert p.ready is True
        assert len(p.output_state) > 0
        # The output should carry sol 1 (what was already in the pipe)
        assert p.output_state[0]['q'] == {1: 1.0}

    def test_push_pull_updates_internal_state(self):
        p = self._filled_pipe(volume=10.0)
        p.push_pull(2.0, [[2.0, {2: 1.0}]])
        # New parcel of sol 2 should be at the inlet
        assert p.state[0]['q'] == {2: 1.0}
        assert p.state[0]['x0'] == 0.0


# ---------------------------------------------------------------------------
# fifo.py — ZeroLengthFIFO / Pump / Valve
# ---------------------------------------------------------------------------

class TestZeroLengthFIFO:
    def test_fill(self):
        from victoria.fifo import Pump
        p = Pump()
        p.fill({1: 1.0})
        assert len(p.output_state) == 1
        assert p.output_state[0]['volume'] == 0

    def test_push_pull_passes_through(self):
        from victoria.fifo import Valve
        v = Valve()
        v.push_pull(5.0, [[3.0, {1: 1.0}], [2.0, {2: 1.0}]])
        assert len(v.output_state) == 2
        assert pytest.approx(sum(p['x1'] - p['x0'] for p in v.output_state)) == 1.0

    def test_push_pull_zero_flow_clears_output(self):
        from victoria.fifo import Pump
        p = Pump()
        p.push_pull(0.0, [[1.0, {1: 1.0}]])
        assert p.output_state == []

    def test_pump_and_valve_are_separate_classes(self):
        from victoria.fifo import Pump, Valve
        assert Pump is not Valve


# ---------------------------------------------------------------------------
# mix.py — MIX.merge_load
# ---------------------------------------------------------------------------

class TestMixMergeLoad:
    def test_merge_empty_dicts(self):
        from victoria.mix import MIX
        result = MIX.merge_load({}, {1: 1.0}, 0.5)
        assert result == {1: 0.5}

    def test_merge_accumulates(self):
        from victoria.mix import MIX
        existing = {1: 0.4}
        result = MIX.merge_load(existing, {1: 1.0}, 0.6)
        assert pytest.approx(result[1]) == 1.0

    def test_merge_does_not_mutate_existing(self):
        from victoria.mix import MIX
        existing = {1: 0.5}
        MIX.merge_load(existing, {2: 1.0}, 1.0)
        assert existing == {1: 0.5}  # unchanged


# ---------------------------------------------------------------------------
# mix.py — MIX.parcels_out
# ---------------------------------------------------------------------------

class TestMixParcelsOut:
    def test_parcels_out_zero_total_flow(self):
        from victoria.mix import MIX
        m = MIX()
        m.mixed_parcels = [{'x0': 0, 'x1': 1, 'q': {1: 1.0}, 'volume': 10.0}]
        m.parcels_out([0.0])
        assert m.outflow == []

    def test_parcels_out_distributes_proportionally(self):
        from victoria.mix import MIX
        m = MIX()
        m.mixed_parcels = [{'x0': 0, 'x1': 1, 'q': {1: 1.0}, 'volume': 10.0}]
        m.parcels_out([3.0, 7.0])
        assert len(m.outflow) == 2
        # Volume fractions should sum to total flow / link count
        vol0 = m.outflow[0][0][0]
        vol1 = m.outflow[1][0][0]
        assert pytest.approx(vol0 / vol1, rel=1e-5) == 3.0 / 7.0


# ---------------------------------------------------------------------------
# mix.py — Reservoir
# ---------------------------------------------------------------------------

class TestReservoir:
    def _make_reservoir_node(self, uid='R1', outflow=3.6):
        node = MagicMock()
        node.uid = uid
        node.outflow = outflow        # m³/h
        node.downstream_links = []
        return node

    def test_mix_produces_mixed_parcel(self):
        from victoria.mix import Reservoir
        r = Reservoir()
        node = self._make_reservoir_node()
        sol = MagicMock()
        sol.number = 1
        input_sol = {node.uid: sol}
        r.mix([], node, 3600, input_sol)
        assert len(r.mixed_parcels) == 1
        assert r.mixed_parcels[0]['q'] == {1: 1.0}

    def test_mix_outflow_fallback_for_no_downstream(self):
        from victoria.mix import Reservoir
        r = Reservoir()
        node = self._make_reservoir_node()
        node.downstream_links = []
        sol = MagicMock()
        sol.number = 1
        r.mix([], node, 3600, {node.uid: sol})
        # Should produce at least one outflow slot
        assert len(r.outflow) >= 1


# ---------------------------------------------------------------------------
# mix.py — Junction
# ---------------------------------------------------------------------------

class TestJunction:
    def _simple_inflow(self, q, volume=10.0):
        return [{'x0': 0.0, 'x1': 1.0, 'q': q, 'volume': volume}]

    def test_mix_empty_inflow(self):
        from victoria.mix import Junction
        j = Junction()
        node = MagicMock()
        node.demand = 0.0
        node.downstream_links = []
        j.mix([], node, 3600, {})
        assert j.mixed_parcels == []

    def test_mix_single_parcel(self):
        from victoria.mix import Junction
        j = Junction()
        node = MagicMock()
        node.demand = 0.0
        node.downstream_links = []
        j.mix(self._simple_inflow({1: 1.0}), node, 3600, {})
        assert len(j.mixed_parcels) == 1
        assert j.mixed_parcels[0]['q'] == {1: 1.0}


# ---------------------------------------------------------------------------
# mix.py — Tank_CSTR
# ---------------------------------------------------------------------------

class TestTankCSTR:
    def test_initial_mixture_empty(self):
        from victoria.mix import Tank_CSTR
        t = Tank_CSTR(initvolume=100.0)
        assert t.mixture == {}

    def test_mix_updates_mixture(self):
        from victoria.mix import Tank_CSTR
        t = Tank_CSTR(initvolume=50.0)
        node = MagicMock()
        node.volume = 50.0
        node.outflow = 0.0
        node.downstream_links = []
        inflow = [{'x0': 0.0, 'x1': 1.0, 'q': {1: 1.0}, 'volume': 10.0}]
        t.mix(inflow, node, 3600, {})
        # mixture should now contain solution 1
        assert 1 in t.mixture

    def test_mix_zero_volume_tank(self):
        from victoria.mix import Tank_CSTR
        t = Tank_CSTR(initvolume=0.0)
        node = MagicMock()
        node.volume = 0.0
        node.outflow = 0.0
        node.downstream_links = []
        inflow = [{'x0': 0.0, 'x1': 1.0, 'q': {1: 1.0}, 'volume': 5.0}]
        # Should not raise
        t.mix(inflow, node, 3600, {})


# ---------------------------------------------------------------------------
# mix.py — _get_links and _round_dict_values helpers
# ---------------------------------------------------------------------------

class TestMixHelpers:
    def test_get_links_property(self):
        from victoria.mix import _get_links
        node = MagicMock()
        node.upstream_links = ['link1', 'link2']
        assert _get_links(node, 'upstream') == ['link1', 'link2']

    def test_get_links_callable(self):
        from victoria.mix import _get_links
        node = MagicMock()
        node.upstream_links = MagicMock(return_value=['link1'])
        assert _get_links(node, 'upstream') == ['link1']

    def test_round_dict_values(self):
        from victoria.mix import _round_dict_values
        result = _round_dict_values({1: 0.123456789, 2: 0.987654321}, 4)
        assert result == {1: 0.1235, 2: 0.9877}


# ---------------------------------------------------------------------------
# models.py — Models
# ---------------------------------------------------------------------------

class TestModels:
    def _make_network(self, n_junctions=2, n_reservoirs=1, n_pipes=2,
                      n_pumps=0, n_valves=0, n_tanks=0):
        """Build a minimal mock EPyNet network."""
        network = MagicMock()

        junctions = []
        for i in range(n_junctions):
            j = MagicMock()
            j.uid = f'J{i+1}'
            junctions.append(j)

        reservoirs = []
        for i in range(n_reservoirs):
            r = MagicMock()
            r.uid = f'R{i+1}'
            reservoirs.append(r)

        tanks = []
        for i in range(n_tanks):
            t = MagicMock()
            t.uid = f'T{i+1}'
            t.initvolume = 100.0
            tanks.append(t)

        pipes = []
        for i in range(n_pipes):
            p = MagicMock()
            p.uid = f'P{i+1}'
            p.length = 100.0
            p.diameter = 150.0
            pipes.append(p)

        pumps = []
        for i in range(n_pumps):
            p = MagicMock()
            p.uid = f'PU{i+1}'
            pumps.append(p)

        valves = []
        for i in range(n_valves):
            v = MagicMock()
            v.uid = f'V{i+1}'
            valves.append(v)

        network.junctions = junctions
        network.reservoirs = reservoirs
        network.tanks = tanks
        network.pipes = pipes
        network.pumps = pumps
        network.valves = valves
        return network

    def test_creates_junction_models(self):
        from victoria.models import Models
        net = self._make_network(n_junctions=3)
        m = Models(net)
        assert len(m.junctions) == 3
        assert all(uid in m.nodes for uid in m.junctions)

    def test_creates_reservoir_models(self):
        from victoria.models import Models
        net = self._make_network(n_reservoirs=2)
        m = Models(net)
        assert len(m.reservoirs) == 2

    def test_creates_pipe_models(self):
        from victoria.models import Models
        net = self._make_network(n_pipes=4)
        m = Models(net)
        assert len(m.pipes) == 4
        assert all(uid in m.links for uid in m.pipes)

    def test_creates_tank_models(self):
        from victoria.models import Models
        net = self._make_network(n_tanks=2)
        m = Models(net)
        assert len(m.tanks) == 2

    def test_pipe_volume_calculation(self):
        from victoria.models import Models
        # V = pi/4 * L * D^2  (D in metres)
        vol = Models._calculate_pipe_volume(length_m=100.0, diameter_mm=200.0)
        expected = math.pi / 4 * 100.0 * (0.2 ** 2)
        assert pytest.approx(vol, rel=1e-6) == expected

    def test_get_node_model_found(self):
        from victoria.models import Models
        net = self._make_network(n_junctions=1)
        m = Models(net)
        uid = 'J1'
        model = m.get_node_model(uid)
        assert model is m.nodes[uid]

    def test_get_node_model_not_found(self):
        from victoria.models import Models
        net = self._make_network()
        m = Models(net)
        with pytest.raises(KeyError):
            m.get_node_model('NONEXISTENT')

    def test_get_link_model_found(self):
        from victoria.models import Models
        net = self._make_network(n_pipes=1)
        m = Models(net)
        uid = 'P1'
        model = m.get_link_model(uid)
        assert model is m.links[uid]

    def test_get_link_model_not_found(self):
        from victoria.models import Models
        net = self._make_network()
        m = Models(net)
        with pytest.raises(KeyError):
            m.get_link_model('NONEXISTENT')


# ---------------------------------------------------------------------------
# solver.py — _select_fill_solution (static, no mocks needed)
# ---------------------------------------------------------------------------

class TestSolverSelectFillSolution:
    def test_normal_outflow(self):
        from victoria.solver import Solver
        outflow = [[[10.0, {1: 1.0}]], [[5.0, {2: 1.0}]]]
        sol = Solver._select_fill_solution(outflow, 0, {})
        assert sol == {1: 1.0}

    def test_fallback_to_first_slot(self):
        from victoria.solver import Solver
        outflow = [[[10.0, {1: 1.0}]]]
        # index 1 does not exist → fall back to outflow[0]
        sol = Solver._select_fill_solution(outflow, 1, {})
        assert sol == {1: 1.0}

    def test_empty_outflow_uses_input_sol(self):
        from victoria.solver import Solver
        bg = MagicMock()
        bg.number = 99
        input_sol = {0: bg}
        sol = Solver._select_fill_solution([], 0, input_sol)
        assert sol == {99: 1.0}


# ---------------------------------------------------------------------------
# solver.py — reset_ready_state
# ---------------------------------------------------------------------------

class TestSolverResetReadyState:
    def test_reset_sets_all_links_not_ready(self):
        from victoria.solver import Solver
        from victoria.fifo import Pipe

        network = MagicMock()
        pipe1 = _make_link('P1')
        pipe2 = _make_link('P2')
        network.links = [pipe1, pipe2]

        models = MagicMock()
        p1_model = Pipe(volume=1.0)
        p2_model = Pipe(volume=1.0)
        p1_model.ready = True
        p2_model.ready = True
        models.links = {'P1': p1_model, 'P2': p2_model}

        solver = Solver(models, network)
        solver.reset_ready_state()

        assert p1_model.ready is False
        assert p2_model.ready is False


# ---------------------------------------------------------------------------
# solver.py — check_connections (flow reversal detection)
# ---------------------------------------------------------------------------

class TestSolverCheckConnections:
    def test_no_reversal_when_direction_unchanged(self):
        from victoria.solver import Solver
        from victoria.fifo import Pipe

        up = MagicMock(uid='J1')
        dn = MagicMock(uid='J2')
        link = _make_link('P1', upstream_node=up, downstream_node=dn)

        network = MagicMock()
        network.links = [link]

        p = Pipe(volume=1.0)
        p.upstream_node = up
        p.downstream_node = dn
        p.state = [{'x0': 0.0, 'x1': 1.0, 'q': {1: 1.0}}]

        models = MagicMock()
        models.links = {'P1': p}

        solver = Solver(models, network)
        solver.check_connections()

        # State should be unchanged (no reversal)
        assert p.state[0]['x0'] == 0.0
        assert p.state[0]['x1'] == 1.0

    def test_reversal_triggered_when_direction_changes(self):
        from victoria.solver import Solver
        from victoria.fifo import Pipe

        up = MagicMock(uid='J1')
        dn = MagicMock(uid='J2')
        link = _make_link('P1', upstream_node=dn, downstream_node=up)  # reversed

        network = MagicMock()
        network.links = [link]

        p = Pipe(volume=1.0)
        p.upstream_node = up   # was: J1→J2, now link says J2→J1
        p.downstream_node = dn
        p.state = [{'x0': 0.0, 'x1': 0.6, 'q': {1: 1.0}}]

        models = MagicMock()
        models.links = {'P1': p}

        solver = Solver(models, network)
        solver.check_connections()

        # After reversal, x1 of original parcel (0.6) should become 1-0.0=1.0 x0 and 1-0.6=0.4 x1
        assert p.state[0]['x0'] == pytest.approx(0.4)
        assert p.state[0]['x1'] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# quality.py — Quality (with mocked PHREEQC and Models)
# ---------------------------------------------------------------------------

class TestQuality:
    def _make_quality(self, sol_conc=5.0):
        """Return a Quality instance with fully mocked dependencies."""
        from victoria.quality import Quality

        # Mock PHREEQC
        pp = MagicMock()
        pp.get_solution_list.return_value = [1, 2]
        phreeqc_sol = MagicMock()
        phreeqc_sol.pH = 7.0
        phreeqc_sol.sc = 500.0
        phreeqc_sol.temperature = 15.0
        pp.get_solution.return_value = phreeqc_sol
        mixed = MagicMock()
        mixed.total.return_value = sol_conc
        mixed.pH = 7.0
        mixed.sc = 500.0
        mixed.temperature = 15.0
        pp.mix_solutions.return_value = mixed

        # Mock Models
        models = MagicMock()

        return Quality(pp, models), pp, models

    def _node_with_parcels(self, models, q, volume=10.0):
        """Set up models.nodes[uid] to return a node with mixed_parcels."""
        node_uid = 'J1'
        node = MagicMock()
        node.uid = node_uid
        node_model = MagicMock()
        node_model.mixed_parcels = [
            {'x0': 0.0, 'x1': 1.0, 'q': q, 'volume': volume}
        ]
        models.nodes.get.return_value = node_model
        return node

    def test_get_conc_node_no_model(self):
        quality, pp, models = self._make_quality()
        models.nodes.get.return_value = None
        node = MagicMock(uid='MISSING')
        assert quality.get_conc_node(node, 'Ca', 'mg') == 0.0

    def test_get_conc_node_returns_value(self):
        quality, pp, models = self._make_quality(sol_conc=3.5)
        node = self._node_with_parcels(models, {1: 1.0})
        result = quality.get_conc_node(node, 'Ca', 'mg')
        assert result == pytest.approx(3.5)

    def test_get_conc_node_avg_returns_value(self):
        quality, pp, models = self._make_quality(sol_conc=2.0)
        node = self._node_with_parcels(models, {1: 1.0})
        result = quality.get_conc_node_avg(node, 'Ca', 'mg')
        # Single parcel spanning 0→1, weighted average equals raw value
        assert result == pytest.approx(2.0)

    def test_get_mixture_node_returns_dict(self):
        quality, pp, models = self._make_quality()
        q = {1: 0.6, 2: 0.4}
        node = self._node_with_parcels(models, q)
        result = quality.get_mixture_node(node)
        assert result == q

    def test_get_mixture_node_no_model(self):
        quality, pp, models = self._make_quality()
        models.nodes.get.return_value = None
        node = MagicMock(uid='MISSING')
        assert quality.get_mixture_node(node) == {}

    def test_get_conc_pipe_empty_state(self):
        quality, pp, models = self._make_quality()
        link_model = MagicMock()
        link_model.state = []
        models.links.get.return_value = link_model
        link = MagicMock(uid='P1')
        assert quality.get_conc_pipe(link, 'Ca', 'mg') == []

    def test_get_conc_pipe_returns_profile(self):
        quality, pp, models = self._make_quality(sol_conc=4.0)
        link_model = MagicMock()
        link_model.state = [
            {'x0': 0.0, 'x1': 0.5, 'q': {1: 1.0}},
            {'x0': 0.5, 'x1': 1.0, 'q': {2: 1.0}},
        ]
        models.links.get.return_value = link_model
        link = MagicMock(uid='P1')
        result = quality.get_conc_pipe(link, 'Ca', 'mg')
        assert len(result) == 2
        assert result[0]['x0'] == 0.0
        assert result[0]['x1'] == 0.5
        assert result[0]['q'] == pytest.approx(4.0)

    def test_get_conc_pipe_avg(self):
        quality, pp, models = self._make_quality(sol_conc=2.0)
        pipe_model = MagicMock()
        pipe_model.state = [
            {'x0': 0.0, 'x1': 0.5, 'q': {1: 1.0}},
            {'x0': 0.5, 'x1': 1.0, 'q': {2: 1.0}},
        ]
        models.pipes.get.return_value = pipe_model
        link = MagicMock(uid='P1')
        result = quality.get_conc_pipe_avg(link, 'Ca', 'mg')
        # 0.5 * 2.0 + 0.5 * 2.0 = 2.0
        assert result == pytest.approx(2.0)

    def test_get_properties_node(self):
        quality, pp, models = self._make_quality()
        node = self._node_with_parcels(models, {1: 1.0})
        ph, sc, temp = quality.get_properties_node(node)
        assert ph == pytest.approx(7.0)
        assert sc == pytest.approx(500.0)
        assert temp == pytest.approx(15.0)

    def test_mix_phreeqc_solutions_oxygen_convergence_logs_debug(self, caplog):
        """Oxygen convergence errors should be DEBUG, not ERROR."""
        import logging
        from victoria.quality import Quality

        pp = MagicMock()
        pp.get_solution_list.return_value = [1]
        pp.get_solution.return_value = MagicMock()
        pp.mix_solutions.side_effect = Exception("Oxygen Mass of oxygen has not converged.")

        quality = Quality(pp, MagicMock())

        with caplog.at_level(logging.DEBUG, logger='victoria.quality'):
            result = quality._mix_phreeqc_solutions({1: 1.0})

        assert result is None
        # Should NOT have logged at ERROR level
        error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(error_records) == 0

    def test_mix_phreeqc_solutions_other_error_logs_error(self, caplog):
        """Non-oxygen errors should still log at ERROR level."""
        import logging
        from victoria.quality import Quality

        pp = MagicMock()
        pp.get_solution_list.return_value = [1]
        pp.get_solution.return_value = MagicMock()
        pp.mix_solutions.side_effect = Exception("Unexpected chemistry failure")

        quality = Quality(pp, MagicMock())

        with caplog.at_level(logging.ERROR, logger='victoria.quality'):
            result = quality._mix_phreeqc_solutions({1: 1.0})

        assert result is None
        error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(error_records) == 1

    def test_mix_phreeqc_solutions_empty_dict(self):
        from victoria.quality import Quality
        quality = Quality(MagicMock(), MagicMock())
        assert quality._mix_phreeqc_solutions({}) is None

    def test_mix_phreeqc_solutions_missing_solution(self):
        from victoria.quality import Quality
        pp = MagicMock()
        pp.get_solution_list.return_value = []   # sol 1 is not registered
        quality = Quality(pp, MagicMock())
        result = quality._mix_phreeqc_solutions({1: 1.0})
        assert result is None


# ---------------------------------------------------------------------------
# segmentation.py — PipeSegmentation
# ---------------------------------------------------------------------------

class TestPipeSegmentation:
    def _make_model_with_parcels(self, parcels):
        """Return a mock Victoria model whose get_conc_pipe returns parcels."""
        model = MagicMock()
        model.get_conc_pipe.return_value = parcels
        return model

    def _make_pipe(self, uid='P1', length=30.0):
        return _make_pipe_object(uid, length=length)

    # Construction ----------------------------------------------------------

    def test_invalid_seg_length_raises(self):
        from victoria.segmentation import PipeSegmentation
        with pytest.raises(ValueError):
            PipeSegmentation(MagicMock(), seg_length_m=0.0)

    def test_repr(self):
        from victoria.segmentation import PipeSegmentation
        seg = PipeSegmentation(MagicMock(), seg_length_m=5.0)
        assert '5.0' in repr(seg)

    # segment_pipe ----------------------------------------------------------

    def test_segment_pipe_empty_parcels(self):
        from victoria.segmentation import PipeSegmentation
        model = self._make_model_with_parcels([])
        seg = PipeSegmentation(model, seg_length_m=10.0)
        result = seg.segment_pipe(self._make_pipe(length=30.0), 'Ca', 'mg')
        assert result == []

    def test_segment_pipe_zero_length_pipe(self):
        from victoria.segmentation import PipeSegmentation
        model = self._make_model_with_parcels([{'x0': 0.0, 'x1': 1.0, 'q': 5.0}])
        seg = PipeSegmentation(model, seg_length_m=10.0)
        result = seg.segment_pipe(self._make_pipe(length=0.0), 'Ca', 'mg')
        assert result == []

    def test_segment_pipe_correct_count(self):
        from victoria.segmentation import PipeSegmentation
        parcels = [{'x0': 0.0, 'x1': 1.0, 'q': 3.0}]
        model = self._make_model_with_parcels(parcels)
        seg = PipeSegmentation(model, seg_length_m=10.0)
        pipe = self._make_pipe(length=30.0)   # exactly 3 segments
        result = seg.segment_pipe(pipe, 'Ca', 'mg')
        assert len(result) == 3

    def test_segment_pipe_partial_last_segment(self):
        from victoria.segmentation import PipeSegmentation
        parcels = [{'x0': 0.0, 'x1': 1.0, 'q': 2.0}]
        model = self._make_model_with_parcels(parcels)
        seg = PipeSegmentation(model, seg_length_m=10.0)
        pipe = self._make_pipe(length=25.0)   # 2 full + 1 partial (5 m)
        result = seg.segment_pipe(pipe, 'Ca', 'mg')
        assert len(result) == 3
        assert result[-1]['length_m'] == pytest.approx(5.0)

    def test_segment_pipe_conc_uniform_parcel(self):
        """Single uniform parcel: every segment should have the same concentration."""
        from victoria.segmentation import PipeSegmentation
        conc_value = 4.2
        parcels = [{'x0': 0.0, 'x1': 1.0, 'q': conc_value}]
        model = self._make_model_with_parcels(parcels)
        seg = PipeSegmentation(model, seg_length_m=10.0)
        pipe = self._make_pipe(length=30.0)
        result = seg.segment_pipe(pipe, 'Ca', 'mg')
        for s in result:
            assert s['conc'] == pytest.approx(conc_value)

    def test_segment_pipe_conc_two_parcels(self):
        """Two adjacent parcels with different concentrations."""
        from victoria.segmentation import PipeSegmentation
        # Pipe 20 m, seg 10 m: seg1 = first half (conc 1.0), seg2 = second half (conc 3.0)
        parcels = [
            {'x0': 0.0, 'x1': 0.5, 'q': 1.0},
            {'x0': 0.5, 'x1': 1.0, 'q': 3.0},
        ]
        model = self._make_model_with_parcels(parcels)
        seg = PipeSegmentation(model, seg_length_m=10.0)
        pipe = self._make_pipe(length=20.0)
        result = seg.segment_pipe(pipe, 'Ca', 'mg')
        assert len(result) == 2
        assert result[0]['conc'] == pytest.approx(1.0)
        assert result[1]['conc'] == pytest.approx(3.0)

    def test_segment_pipe_seg_id_is_one_based(self):
        from victoria.segmentation import PipeSegmentation
        parcels = [{'x0': 0.0, 'x1': 1.0, 'q': 1.0}]
        model = self._make_model_with_parcels(parcels)
        seg = PipeSegmentation(model, seg_length_m=5.0)
        pipe = self._make_pipe(length=15.0)
        result = seg.segment_pipe(pipe, 'Ca', 'mg')
        assert [s['seg_id'] for s in result] == [1, 2, 3]

    def test_segment_pipe_x_positions(self):
        from victoria.segmentation import PipeSegmentation
        parcels = [{'x0': 0.0, 'x1': 1.0, 'q': 1.0}]
        model = self._make_model_with_parcels(parcels)
        seg = PipeSegmentation(model, seg_length_m=10.0)
        pipe = self._make_pipe(length=20.0)
        result = seg.segment_pipe(pipe, 'Ca', 'mg')
        assert result[0]['x_start_m'] == pytest.approx(0.0)
        assert result[0]['x_end_m'] == pytest.approx(10.0)
        assert result[0]['x_mid_m'] == pytest.approx(5.0)
        assert result[1]['x_start_m'] == pytest.approx(10.0)
        assert result[1]['x_end_m'] == pytest.approx(20.0)

    def test_segment_pipe_n_parcels_count(self):
        from victoria.segmentation import PipeSegmentation
        parcels = [
            {'x0': 0.0, 'x1': 0.4, 'q': 1.0},
            {'x0': 0.4, 'x1': 1.0, 'q': 2.0},
        ]
        model = self._make_model_with_parcels(parcels)
        seg = PipeSegmentation(model, seg_length_m=10.0)
        pipe = self._make_pipe(length=20.0)
        result = seg.segment_pipe(pipe, 'Ca', 'mg')
        # Seg 1 (0–10 m = 0–0.5 norm): overlaps both parcels (parcel 1: 0–0.4, parcel 2: 0.4–1.0)
        assert result[0]['n_parcels'] == 2
        # Seg 2 (10–20 m = 0.5–1.0 norm): only parcel 2
        assert result[1]['n_parcels'] == 1

    # segment_network -------------------------------------------------------

    def test_segment_network_returns_dataframe(self):
        import pandas as pd
        from victoria.segmentation import PipeSegmentation

        parcels = [{'x0': 0.0, 'x1': 1.0, 'q': 2.0}]
        model = self._make_model_with_parcels(parcels)
        seg = PipeSegmentation(model, seg_length_m=10.0)

        network = MagicMock()
        pipes = [self._make_pipe('P1', 20.0), self._make_pipe('P2', 30.0)]
        network.pipes = pipes

        df = seg.segment_network(network, 'Ca', 'mg')
        assert isinstance(df, pd.DataFrame)
        assert set(df.columns) >= {'pipe', 'seg_id', 'conc', 'x_start_m', 'x_end_m'}
        assert len(df) == 2 + 3  # 2 segs for P1, 3 segs for P2

    def test_segment_network_empty_when_no_parcels(self):
        import pandas as pd
        from victoria.segmentation import PipeSegmentation

        model = self._make_model_with_parcels([])
        seg = PipeSegmentation(model, seg_length_m=10.0)

        network = MagicMock()
        network.pipes = [self._make_pipe('P1', 20.0)]

        df = seg.segment_network(network, 'Ca', 'mg')
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0

    # record_step / to_dataframe / reset ------------------------------------

    def test_record_step_populates_buffer(self):
        from victoria.segmentation import PipeSegmentation

        parcels = [{'x0': 0.0, 'x1': 1.0, 'q': 1.5}]
        model = self._make_model_with_parcels(parcels)
        seg = PipeSegmentation(model, seg_length_m=10.0)

        network = MagicMock()
        network.pipes = [self._make_pipe('P1', 20.0)]

        seg.record_step(network, 'Ca', 'mg', time_s=300, step=1)
        df = seg.to_dataframe()
        assert len(df) == 2  # 2 segments
        assert 'time_s' in df.columns
        assert 'time_min' in df.columns
        assert 'step' in df.columns
        assert df['step'].iloc[0] == 1
        assert df['time_min'].iloc[0] == pytest.approx(5.0)

    def test_record_step_without_time_metadata(self):
        from victoria.segmentation import PipeSegmentation

        parcels = [{'x0': 0.0, 'x1': 1.0, 'q': 1.0}]
        model = self._make_model_with_parcels(parcels)
        seg = PipeSegmentation(model, seg_length_m=20.0)

        network = MagicMock()
        network.pipes = [self._make_pipe('P1', 20.0)]

        seg.record_step(network, 'Ca', 'mg')   # no time_s or step
        df = seg.to_dataframe()
        assert 'time_s' not in df.columns
        assert 'step' not in df.columns

    def test_to_dataframe_empty_buffer(self):
        import pandas as pd
        from victoria.segmentation import PipeSegmentation

        seg = PipeSegmentation(MagicMock(), seg_length_m=5.0)
        df = seg.to_dataframe()
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0

    def test_reset_clears_buffer(self):
        from victoria.segmentation import PipeSegmentation

        parcels = [{'x0': 0.0, 'x1': 1.0, 'q': 1.0}]
        model = self._make_model_with_parcels(parcels)
        seg = PipeSegmentation(model, seg_length_m=10.0)

        network = MagicMock()
        network.pipes = [self._make_pipe('P1', 10.0)]

        seg.record_step(network, 'Ca', 'mg', time_s=60, step=1)
        assert len(seg._time_records) > 0

        seg.reset()
        assert seg._time_records == []
        assert len(seg.to_dataframe()) == 0

    def test_multiple_steps_accumulate(self):
        from victoria.segmentation import PipeSegmentation

        parcels = [{'x0': 0.0, 'x1': 1.0, 'q': 1.0}]
        model = self._make_model_with_parcels(parcels)
        seg = PipeSegmentation(model, seg_length_m=10.0)

        network = MagicMock()
        network.pipes = [self._make_pipe('P1', 10.0)]  # 1 segment

        for step in range(5):
            seg.record_step(network, 'Ca', 'mg', time_s=step * 300, step=step)

        df = seg.to_dataframe()
        assert len(df) == 5   # 1 segment × 5 steps

    # pipe_metadata ---------------------------------------------------------

    def test_pipe_metadata_columns(self):
        from victoria.segmentation import PipeSegmentation

        seg = PipeSegmentation(MagicMock(), seg_length_m=10.0)
        network = MagicMock()
        network.pipes = [self._make_pipe('P1', 25.0)]

        df = seg.pipe_metadata(network)
        assert set(df.columns) == {'pipe', 'pipe_length_m', 'seg_length_m', 'n_segs', 'last_seg_m'}

    def test_pipe_metadata_values(self):
        from victoria.segmentation import PipeSegmentation

        seg = PipeSegmentation(MagicMock(), seg_length_m=10.0)
        network = MagicMock()
        network.pipes = [self._make_pipe('P1', 25.0)]

        df = seg.pipe_metadata(network)
        row = df.iloc[0]
        assert row['pipe'] == 'P1'
        assert row['pipe_length_m'] == pytest.approx(25.0)
        assert row['n_segs'] == 3           # ceil(25/10)
        assert row['last_seg_m'] == pytest.approx(5.0)

    def test_pipe_metadata_skips_zero_length(self):
        from victoria.segmentation import PipeSegmentation

        seg = PipeSegmentation(MagicMock(), seg_length_m=10.0)
        network = MagicMock()
        zero_pipe = _make_pipe_object('P0', length=0.0)
        valid_pipe = _make_pipe_object('P1', length=20.0)
        network.pipes = [zero_pipe, valid_pipe]

        df = seg.pipe_metadata(network)
        assert len(df) == 1
        assert df.iloc[0]['pipe'] == 'P1'

    # Victoria convenience wrappers ----------------------------------------

    def test_victoria_segmentation_factory(self):
        from victoria.segmentation import PipeSegmentation

        vic = MagicMock()
        # Simulate Victoria.segmentation() behaviour
        result = PipeSegmentation(vic, seg_length_m=8.0)
        assert result.seg_length_m == 8.0
        assert result.model is vic

    def test_victoria_segment_pipe_wrapper(self):
        """victoria.segment_pipe() should delegate to PipeSegmentation."""
        from victoria.segmentation import PipeSegmentation

        parcels = [{'x0': 0.0, 'x1': 1.0, 'q': 7.0}]
        vic = MagicMock()
        vic.get_conc_pipe.return_value = parcels

        seg = PipeSegmentation(vic, seg_length_m=10.0)
        pipe = self._make_pipe('P1', 10.0)
        result = seg.segment_pipe(pipe, 'Ca', 'mg')

        assert len(result) == 1
        assert result[0]['conc'] == pytest.approx(7.0)
