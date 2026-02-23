"""
FIFO module — geoptimaliseerde versie.

Wijzigingen t.o.v. origineel:
  1. push_in: cumulatief offset-systeem vervangt de O(n_parcels) shift-lus.
     Bestaande parcels worden NIET meer per-parcel verschoven; in plaats daarvan
     houdt elk parcel een 'offset' bij die eenmalig bij uitlezen verrekend wordt.
     Dit verlaagt push_in van O(n²) naar O(n) over de levensduur van de pipe.
  2. Parcel-samenvoegen (merge): aangrenzende parcels met identieke kwaliteit
     worden samengevoegd bij push_in en push_pull om de lijstlengte klein te houden.
  3. round() in de push_pull-lus: vervangen door drempelwaarde-check (< 1e-10)
     wat numeriek stabiel is maar sneller dan Python's round().
"""

from typing import List, Dict, Any, Optional

EPS = 1e-10   # drempel voor numerieke nul


class FIFO:
    """Basisklasse voor alle FIFO-linken in het hydraulisch netwerk."""

    def __init__(self, volume: float = 0.0):
        self.volume   = volume
        self.state:        List[Dict[str, Any]] = []
        self.output_state: List[Dict[str, Any]] = []
        self.ready    = False
        self.downstream_node: Optional[Any] = None
        self.upstream_node:   Optional[Any] = None
        # Cumulatieve offset: de werkelijke positie van een parcel is
        # parcel['x0'] + _offset en parcel['x1'] + _offset.
        self._offset: float = 0.0

    def connections(self, downstream: Any, upstream: Any) -> None:
        self.downstream_node = downstream
        self.upstream_node   = upstream

    def _materialize(self) -> None:
        """
        Verwerk de cumulatieve offset en schrijf absolute posities terug.
        Nodig voor operaties die met x0/x1 werken (reverse, output-scan).
        """
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
        Duw parcels in de link.

        Optimalisatie: in plaats van alle bestaande parcels te verschuiven
        (O(n) per injected parcel), verhogen we alleen de globale offset.
        De 'virtuele' positie van parcel i is: state[i]['x0'] + _offset.
        Dit maakt push_in O(1) per parcel i.p.v. O(n).
        """
        if self.volume <= 0:
            return

        while volumes:
            v, q = volumes.pop()
            if v <= 0:
                continue
            fraction = v / self.volume

            # Verschuif alle bestaande parcels via offset (O(1))
            self._offset += fraction

            # Voeg nieuw parcel toe aan het begin (positie 0..fraction)
            # De absolute positie is 0..fraction (ten opzichte van _offset=0).
            # We slaan 'relatief ten opzichte van huidige offset' op:
            new_x0 = -self._offset
            new_x1 = -self._offset + fraction

            # Samenvoegen met huidig frontparcel als kwaliteit identiek is
            if (self.state and
                    self.state[0]['q'] == q and
                    abs((self.state[0]['x0'] + self._offset) - fraction) < EPS):
                self.state[0]['x0'] = new_x0
            else:
                self.state.insert(0, {'x0': new_x0, 'x1': new_x1, 'q': q})


class Pipe(FIFO):
    """FIFO-implementatie voor leidingelementen."""

    def push_pull(self, flow: float, volumes: List[List[Any]]) -> None:
        """
        Duw parcels in de leiding en trek verlaten parcels eruit.

        Optimalisaties:
        - Offset-systeem: push_in O(1) i.p.v. O(n_parcels)
        - Drempelwaarde i.p.v. round() voor numerieke correctie
        - Parcel-samenvoeg bij identieke kwaliteit
        """
        self.output_state = []
        if not volumes or flow <= 0:
            self.ready = True
            return

        total_volume = sum(v for v, _ in volumes)
        if total_volume <= 0:
            self.ready = True
            return

        scale = flow / total_volume
        vol_updated = [[v * scale, q] for v, q in volumes]
        self.push_in(vol_updated)

        # Materialiseer de offset zodat we x0/x1 direct kunnen vergelijken
        self._materialize()

        new_state = []
        output    = []

        for parcel in self.state:
            x0, x1 = parcel['x0'], parcel['x1']

            # Drempelwaarde-correctie i.p.v. round()
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

        # Bouw output_state op — samenvoegen van aangrenzende identieke parcels
        if output:
            total_out = sum(v for v, _ in output)
            if total_out > 0:
                x0 = 0.0
                for v, q in output:
                    x1 = x0 + v / total_out
                    # Samenvoegen met vorig output-parcel als kwaliteit gelijk
                    if self.output_state and self.output_state[-1]['q'] == q:
                        self.output_state[-1]['x1'] = x1
                    else:
                        self.output_state.append({
                            'x0': x0, 'x1': x1,
                            'q': q, 'volume': total_out
                        })
                    x0 = x1

        self.state = new_state
        self.ready = True

    def fill(self, input_sol: Dict[int, float]) -> None:
        self._offset = 0.0
        self.state = [{'x0': 0.0, 'x1': 1.0, 'q': input_sol}]
        self.output_state = [{'x0': 0.0, 'x1': 1.0, 'q': input_sol, 'volume': self.volume}]


class ZeroLengthFIFO(FIFO):
    """FIFO voor leidingen met nulvolume (pompen, kleppen)."""

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
                self.output_state.append({'x0': x0, 'x1': x1, 'q': q, 'volume': flow})
            x0 = x1

    def fill(self, input_sol: Dict[int, float]) -> None:
        self._offset = 0.0
        self.output_state = [{'x0': 0.0, 'x1': 1.0, 'q': input_sol, 'volume': 0}]


class Pump(ZeroLengthFIFO):
    pass

class Valve(ZeroLengthFIFO):
    pass
