🇳🇱 [Nederlands](README_NL.md) &nbsp;|&nbsp; 🇬🇧 [English](README.md)
# Victoria

**Waterchemiekwaliteitssimulator voor hydraulische distributienetwerken**

[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/)
[![EPyNet](https://img.shields.io/badge/epynet-2025-orange)](https://github.com/pyepanet/epynet)
[![PhreeqPython](https://img.shields.io/badge/phreeqpython-required-red)](https://github.com/Vitens/phreeqpython)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Version](https://img.shields.io/badge/version-1.1.0-informational)](CHANGELOG.md)

Victoria simuleert waterchemische kwaliteit in hydraulische distributienetwerken door PHREEQC-geochemie te koppelen aan EPyNet-hydraulica. Water wordt bijgehouden als **discrete parcels** in leidingen (FIFO) en volledig gemengd op knooppunten en tanks — zonder de numerieke diffusie van Euleriaanse methoden.

🇬🇧 [English version](README.md)

---

## Inhoudsopgave

- [Kenmerken](#kenmerken)
- [Installatie](#installatie)
- [Snelstart](#snelstart)
- [Architectuur](#architectuur)
- [API-referentie](#api-referentie)
  - [Victoria](#victoria-klasse)
  - [Models](#models)
  - [Solver & HydraulicCache](#solver--hydrauliccache)
  - [Quality](#quality)
  - [FIFO & Pipe](#fifo--pipe)
  - [MIX & knooppuntmodellen](#mix--knooppuntmodellen)
  - [PipeSegmentation](#pipesegmentation)
- [Geavanceerd gebruik](#geavanceerd-gebruik)
- [Parcel merging](#parcel-merging)
- [Veelgestelde vragen](#veelgestelde-vragen)
- [Woordenlijst](#woordenlijst)
- [Versiehistorie](#versiehistorie)

---

## Kenmerken

- **FIFO-leidingmodel** met parcel merging — beperkt lijstgroei bij lange leidingen of lage stroomsnelheden
- **Volledige PHREEQC-geochemie** op knooppunten via PhreeqPython (`pp.mix_solutions`)
- **Vijf knooppunt-/tankmodellen**: Junction, Reservoir, Tank\_CSTR, Tank\_FIFO, Tank\_LIFO
- **Flow reversal detectie** — parcels worden automatisch gespiegeld bij omgekeerde stroming
- **Iteratieve BFS-traversal** vanuit reservoirs — correct voor netwerken met lussen
- **Precomputed adjacency** per hydraulische stap — elimineert herhaalde ctypes-aanroepen
- **HydraulicCache** — pre-berekent alle hydraulische tijdstappen in één keer voor maximale snelheid
- **PipeSegmentation** — vaste-lengte segmenten voor ruimtelijke analyses en time-series opname
- **Garbage collection** — verwijdert ongebruikte PHREEQC-solutions bij lange simulaties
- **O(n log n) sweep** in junctionmenging — reduceert complexiteit ten opzichte van de naïeve O(n²) aanpak

---

## Installatie

```bash
pip install epynet phreeqpython pandas numpy
```

> **Vereisten:** Python ≥ 3.9, EPyNet (2025-release), PhreeqPython, pandas, numpy

---

## Snelstart

### Basissimulatielus

```python
import epynet
import phreeqpython
from victoria import Victoria

network = epynet.Network('netwerk.inp')
pp = phreeqpython.PhreeqPython()

sol_hoog = pp.add_solution({'units': 'mmol/kgw', 'Ca': 10})
sol_laag = pp.add_solution({})
input_sol = {
    'R1':  sol_hoog,   # reservoir R1 → calciumrijk water
    '_bg': sol_laag,   # achtergrondoplossing
}

network.solve(simtime=0)
vic = Victoria(network, pp)
vic.fill_network(input_sol, from_reservoir=True)

hydstep = 3600  # 1 uur [s]
for step in range(24):
    network.solve(simtime=step * hydstep)
    vic.check_flow_direction()
    vic.step(timestep=hydstep, input_sol=input_sol)

knoop = network.nodes['J5']
print(vic.get_conc_node(knoop, 'Ca', 'mg/L'))
print(vic.get_properties_node(knoop))  # [pH, SC, temperatuur]
```

### Met segmentatie en time-series

```python
seg = vic.segmentation(seg_length_m=10.0)
seg.calibrate(sol_hoog, sc_high=600.0, sc_low=0.0, species='Ca', units='mg')

for step in range(24):
    network.solve(simtime=step * hydstep)
    vic.check_flow_direction()
    vic.step(timestep=hydstep, input_sol=input_sol)
    seg.record_step(network, species='Ca', units='mg',
                    time_s=(step + 1) * hydstep, step=step + 1)

df = seg.to_dataframe()
# Kolommen: pipe, step, time_s, time_min, seg_id, x_start_m, x_end_m,
#           x_mid_m, length_m, conc, sc, n_parcels
```

### Met HydraulicCache (snelste variant)

```python
from victoria.solver import HydraulicCache

hcache = HydraulicCache(network)
hcache.precompute(hydstep_s=3600, n_steps=24)
vic.solver.set_hydraulic_cache(hcache)

for step in range(24):
    vic.check_flow_direction()  # laadt stap uit cache; geen network.solve() nodig
    vic.step(timestep=hydstep, input_sol=input_sol)
```

---

## Architectuur

### Transportmodel

Victoria gebruikt een **Lagrangiaans parcelmodel** (FIFO). Per tijdstap:

```
1. push_in()      — nieuw water van upstream knoop de leiding in
2. push_pull()    — verschuif parcels; x > 1 → output_state (verlaat leiding)
3. mix()          — knooppunt ontvangt output_state van upstream leidingen
                    en berekent chemisch mengsel (PHREEQC of analytisch)
4. parcels_out()  — verdeel mengsel over downstream leidingen naar ratio debiet
```

### Parcel merging

Na elke `push_pull()` worden aangrenzende parcels samengevoegd als alle fracties binnen `eps_merge` (standaard 0,5%) liggen. Een harde bovengrens `max_parcels` (standaard 50) garandeert eindige rekentijd. Hetzelfde geldt voor de knooppuntuitvoer in `Junction.mix()`.

### Modulaire opbouw

| Module | Klasse(n) | Verantwoordelijkheid |
|---|---|---|
| `victoria.py` | `Victoria` | Hoofd-API; orkestreert solver, quality en segmentatie |
| `solver.py` | `Solver`, `HydraulicCache` | BFS-traversal, adjacency, hydraulische caching |
| `models.py` | `Models` | Aanmaken van FIFO/MIX-modellen per netwerkelement |
| `fifo.py` | `FIFO`, `Pipe`, `Pump`, `Valve` | Leidingmodel met parcel push/pull en merging |
| `mix.py` | `MIX`, `Junction`, `Reservoir`, `Tank_*` | Knooppuntmenging (PHREEQC of analytisch) |
| `quality.py` | `Quality` | Opvragen van concentraties en watereigenschappen |
| `segmentation.py` | `PipeSegmentation` | Vaste-lengte segmenten, time-series opname |

---

## API-referentie

### Victoria (klasse)

```python
Victoria(network: epynet.Network, pp: PhreeqPython)
```

#### Simulatiemethoden

| Methode | Omschrijving |
|---|---|
| `step(timestep, input_sol)` | Voer één kwaliteitstijdstap uit. Aanroepen ná `network.solve()`. |
| `fill_network(input_sol, from_reservoir=True)` | Initialiseer het netwerk. Eenmalig vóór de simulatielus. |
| `check_flow_direction()` | Detecteer flow reversals en bouw adjacency-caches op. Elke hydraulische stap aanroepen. |
| `garbage_collect(input_sol=None, preserve=None)` | Verwijder ongebruikte PHREEQC-solutions. Periodiek aanroepen bij lange simulaties. |

#### Concentratie-opvraagmethoden

| Methode | Retourtype | Omschrijving |
|---|---|---|
| `get_conc_node(node, element, units='mmol')` | `float` | Instantane concentratie bij knooppuntuitgang |
| `get_conc_node_avg(node, element, units='mmol')` | `float` | Tijdsgemiddelde concentratie bij knooppuntuitgang |
| `get_mixture_node(node)` | `dict[int, float]` | Instantaan oplossingmengsel `{sol_nr: fractie}` |
| `get_mixture_node_avg(node)` | `dict[int, float]` | Tijdsgemiddeld oplossingmengsel |
| `get_conc_pipe(link, element, units='mmol')` | `list[dict]` | Concentratieprofiel langs een leiding |
| `get_conc_pipe_avg(link, element, units='mmol')` | `float` | Volumegemiddelde concentratie in een leiding |
| `get_parcels(link)` | `list[dict]` | Alle parcels in een leiding |
| `get_properties_node(node)` | `list[float]` | `[pH, SC, temperatuur]` — instantaan |
| `get_properties_node_avg(node)` | `list[float]` | `[pH, SC, temperatuur]` — tijdsgemiddeld |

#### Segmentatiemethoden

| Methode | Omschrijving |
|---|---|
| `segmentation(seg_length_m=6.0)` | Maak een `PipeSegmentation`-object voor time-series opname. |
| `segment_pipe(pipe, species, units='mg', seg_length_m=6.0)` | Concentratie per segment voor één leiding (snapshot). |
| `segment_network(network, species, units='mg', seg_length_m=6.0)` | Concentratie per segment voor alle leidingen (snapshot als DataFrame). |

---

### Models

```python
Models(network: epynet.Network)
```

Aangemaakt intern door `Victoria`. Bevat alle FIFO/MIX-modellen geïndexeerd op uid.

| Attribuut | Type | Inhoud |
|---|---|---|
| `nodes` | `dict[str, MIX]` | Alle knooppuntmodellen (junctions + reservoirs + tanks) |
| `junctions` | `dict[str, Junction]` | Junction-modellen |
| `reservoirs` | `dict[str, Reservoir]` | Reservoir-modellen |
| `tanks` | `dict[str, Tank_*]` | Tank-modellen (standaard `Tank_CSTR`) |
| `links` | `dict[str, FIFO]` | Alle leidingmodellen (pipes + pumps + valves) |
| `pipes` | `dict[str, Pipe]` | Pipe-modellen |
| `pumps` | `dict[str, Pump]` | Pump-modellen |
| `valves` | `dict[str, Valve]` | Valve-modellen |
| `get_node_model(uid)` | `MIX` | Geeft knooppuntmodel; `KeyError` als niet gevonden |
| `get_link_model(uid)` | `FIFO` | Geeft leidingmodel; `KeyError` als niet gevonden |

---

### Solver & HydraulicCache

```python
Solver(models: Models, network: epynet.Network)
```

| Methode | Omschrijving |
|---|---|
| `run_trace(start_node, timestep, input_sol)` | BFS vanuit `start_node`; voert mix + push\_pull uit |
| `fill_network(start_node, input_sol)` | Initialiseer-traversal; vult leidingen met beginoplossing |
| `check_connections()` | Detecteer flow reversals; spiegel parcels in omgekeerde leidingen |
| `reset_ready_state()` | Reset `ready`-vlaggen na elke tijdstap |
| `set_hydraulic_cache(hcache)` | Koppel een `HydraulicCache` voor pre-berekende hydraulica |

```python
from victoria.solver import HydraulicCache
HydraulicCache(network: epynet.Network)
```

| Methode / Attribuut | Omschrijving |
|---|---|
| `precompute(hydstep_s, n_steps)` | Pre-bereken flow, velocity, demand en tankvolume voor alle tijdstappen |
| `apply(step)` | Laad tijdstap `step` in de EPyNet `_values`-cache |
| `n_steps` | Aantal gecachede tijdstappen |
| `flows_at(step)` | `dict[uid, float]` — debieten bij tijdstap `step` |
| `velocities_at(step)` | `dict[uid, float]` — snelheden bij tijdstap `step` |

---

### Quality

```python
Quality(pp: PhreeqPython, models: Models)
```

Berekent concentraties en watereigenschappen door PHREEQC-solutions te mengen. Normaal via `Victoria`-methoden gebruikt; ook rechtstreeks beschikbaar op `victoria.quality`.

---

### FIFO & Pipe

```python
Pipe(volume: float)   # leidingvolume [m³] — berekend als π/4 · L · D²
Pump()                # nul-lengte FIFO (ZeroLengthFIFO)
Valve()               # nul-lengte FIFO (ZeroLengthFIFO)
```

**Parcelformaat (in `state` en `output_state`):**

```python
{
    'x0':     float,           # beginpositie, genormaliseerd op leidinglengte [0.0–1.0]
    'x1':     float,           # eindpositie
    'q':      dict[int,float], # {solution_nummer: fractie, ...}
    'volume': float,           # [m³] — alleen aanwezig in output_state
}
```

**Configureerbare klasse-attributen:**

| Attribuut | Standaard | Omschrijving |
|---|---|---|
| `Pipe.eps_merge` | `0.005` | Max concentratieverschil voor parcel merging (0,5%) |
| `Pipe.max_parcels` | `50` | Harde bovengrens op parcellijstlengte |

**Methoden:**

| Methode | Omschrijving |
|---|---|
| `push_pull(flow, volumes)` | Verschuif parcels; stuur overschot naar `output_state` |
| `push_in(volumes)` | Voeg nieuwe parcels in aan het begin (O(1) via cumulatieve offset) |
| `fill(input_sol)` | Initialiseer leiding met één homogene oplossing |
| `connections(downstream, upstream)` | Sla stroomopwaarts/afwaarts knooppunt op |
| `reverse_parcels(downstream, upstream)` | Spiegel parcelposities bij flow reversal |

---

### MIX & knooppuntmodellen

Alle modellen erven van `MIX` en implementeren `mix(inflow, node, timestep, input_sol)`.

| Klasse | Mengmodel | Toepassing |
|---|---|---|
| `Junction` | O(n log n) grenspuntsweep + PHREEQC | Standaard knooppunt met watervraag |
| `Reservoir` | Vaste invoeroplossing | Waterreservoir / inlaatpunt |
| `Tank_CSTR` | Volledig gemengd (impliciet Euler) | Tank met continue doorstroming |
| `Tank_FIFO` | First-In First-Out | Gestratificeerde tank |
| `Tank_LIFO` | Last-In First-Out | Tank met LIFO-uitstroom |

**Na `mix()` beschikbare attributen:**

| Attribuut | Type | Omschrijving |
|---|---|---|
| `mixed_parcels` | `list[dict]` | Uitvoerprofiel; input voor downstream leidingen |
| `outflow` | `list[list]` | Parcels per downstream leiding (gevuld door `parcels_out()`) |

**Configuratie (klasse-breed):**

```python
from victoria.mix import MIX
MIX.eps_merge   = 0.001  # strenger: 0.1% verschil
MIX.max_parcels = 100
```

---

### PipeSegmentation

```python
PipeSegmentation(model: Victoria, seg_length_m: float = 6.0)
# Of via:
seg = vic.segmentation(seg_length_m=10.0)
```

#### Calibratie (aanbevolen — bypast PHREEQC volledig)

```python
seg.calibrate(
    sol_high,          # PhreeqPython solution (hoge-concentratie end-member)
    sc_high=600.0,     # elektrische geleidbaarheid van sol_high [µS/cm]
    sc_low=0.0,        # geleidbaarheid van achtergrondoplossing
    species='Ca',
    units='mg',
)
```

Na calibratie worden concentratie en SC lineair berekend uit parcel-fracties — geen PHREEQC-aanroepen meer nodig.

#### Methoden

| Methode | Omschrijving |
|---|---|
| `record_step(network, species, units, time_s, step)` | Sla segment-concentraties op voor huidige tijdstap |
| `to_dataframe()` | Geef alle opgeslagen tijdstappen terug als pandas DataFrame |
| `segment_pipe(pipe, species, units)` | Concentratie per segment voor één leiding (snapshot) |
| `segment_network(network, species, units)` | Concentratie per segment voor alle leidingen (snapshot) |
| `pipe_metadata(network)` | DataFrame met leidinglengtes, segmentaantal en laatste segmentlengte |
| `reset()` | Verwijder alle opgeslagen tijdstapgegevens |

#### DataFrame-kolommen (`to_dataframe()`)

```
pipe        — leiding-uid
step        — tijdstapnummer
time_s      — simulatietijd [s]
time_min    — simulatietijd [min]
seg_id      — segmentnummer (1-based)
x_start_m   — beginpositie [m]
x_end_m     — eindpositie [m]
x_mid_m     — middelpositie [m]
length_m    — segmentlengte [m]
conc        — concentratie [opgegeven eenheid]
sc          — elektrische geleidbaarheid [µS/cm]  (alleen na calibratie)
n_parcels   — aantal parcels dat bijdraagt aan segment
```

#### Aanbevolen segmentlengte bepalen

```python
from victoria.segmentation import suggest_seg_length, print_seg_advice

advies = suggest_seg_length(network, hydstep_s=3600, min_segs_per_pipe=5)
print_seg_advice(advies)
```

---

## Geavanceerd gebruik

### Tankmodel wijzigen

```python
from victoria.mix import Tank_FIFO

tank_vol = network.tanks['T1'].initvolume
vic.models.tanks['T1'] = Tank_FIFO(tank_vol)
vic.models.nodes['T1'] = vic.models.tanks['T1']
```

### Parcel merging aanpassen

```python
from victoria.fifo import Pipe
from victoria.mix import MIX

Pipe.eps_merge   = 0.001   # nauwkeuriger: 0.1%
Pipe.max_parcels = 100
MIX.eps_merge    = 0.001
MIX.max_parcels  = 100
```

### Garbage collection bij lange simulaties

```python
for step in range(n_steps):
    network.solve(simtime=step * hydstep)
    vic.check_flow_direction()
    vic.step(timestep=hydstep, input_sol=input_sol)
    if step % 10 == 0:
        vic.garbage_collect(input_sol=input_sol)
```

### Meerdere reservoirs met verschillende watertypen

```python
sol_hard = pp.add_solution({'units': 'mmol/kgw', 'Ca': 10, 'Mg': 2})
sol_soft  = pp.add_solution({'units': 'mmol/kgw', 'Ca': 1})
input_sol = {
    'R_HARD': sol_hard,
    'R_SOFT': sol_soft,
    '_bg':    pp.add_solution({}),
}
```

### Profilen van de simulatie

```bash
python profile_victoria.py netwerk.inp
# Schrijft gesorteerde cProfile-output naar profile_output.txt
```

---

## Parcel merging

Victoria implementeert twee mechanismen om de parcellijst beheersbaar te houden:

### `_merge_adjacent(state, eps_merge)`

Loopt door de parcellijst en voegt aangrenzende parcels samen als alle fracties in `q` binnen `eps_merge` van elkaar liggen. Gewicht is `volume` (als aanwezig) of breedte (`x1 - x0`). Concentraties worden volumegewogen gemiddeld.

### `_enforce_max_parcels(state, max_parcels)`

Als de lijst langer is dan `max_parcels`, worden herhaaldelijk de twee aangrenzende parcels met het kleinste concentratieverschil samengevoegd. Garandeert een harde bovengrens op rekentijd.

Beide functies worden toegepast in `Pipe.push_pull()` én in `Junction.mix()`.

---

## Veelgestelde vragen

**Q: In welke volgorde roep ik de methoden aan?**

```
1. network.solve(simtime=0)
2. vic.fill_network(input_sol)
3. Per tijdstap:
   a. network.solve(simtime=t)      ← of via HydraulicCache
   b. vic.check_flow_direction()
   c. vic.step(timestep, input_sol)
   d. [optioneel] vic.garbage_collect(input_sol)
```

**Q: Wat is het verschil tussen instantaan en tijdsgemiddeld?**

Instantaan (`get_conc_node`) geeft de concentratie van het eerste parcel dat de knoop bereikt — representatief voor de leidende waterkwaliteit. Tijdsgemiddeld (`get_conc_node_avg`) is een volumegewogen gemiddelde over alle `mixed_parcels` — representatief voor de gemiddeld geleverde kwaliteit.

**Q: Wanneer gebruik ik `garbage_collect()`?**

Bij simulaties langer dan ~1000 tijdstappen groeit het aantal PHREEQC-solutions snel. Roep `garbage_collect()` elke 10–50 stappen aan.

**Q: Kan ik een ander tankmodel gebruiken?**

Ja, zie [Tankmodel wijzigen](#tankmodel-wijzigen). `Tank_FIFO` is geschikt voor gestratificeerde tanks; `Tank_LIFO` voor volledig gemengde tanks met LIFO-uitstroom.

---

## Woordenlijst

| Term | Omschrijving |
|---|---|
| **parcel** | Discrete waterprop met vaste samenstelling `{sol_nr: fractie}` |
| **FIFO** | First-In First-Out: eerst ingepompt water verlaat de leiding als eerste |
| **CSTR** | Continuously Stirred Tank Reactor: perfect gemengde tank |
| **BFS** | Breadth-First Search: traversalstrategie vanuit reservoirs |
| **adjacency** | Vooraf berekende upstream/downstream verbindingen per knooppunt |
| **eps\_merge** | Max concentratieverschil voor parcel merging |
| **max\_parcels** | Harde bovengrens op parcellijstlengte |
| **mixed\_parcels** | Uitvoerprofiel van een knooppunt na menging |
| **output\_state** | Buffer met parcels die een leiding verlaten |
| **SC** | Elektrische geleidbaarheid [µS/cm] |
| **flow reversal** | Stroomrichtingsomkering tussen twee hydraulische tijdstappen |

---

## Versiehistorie

### 1.1.0
- Parcel merging op leidingen (`_merge_adjacent`, `_enforce_max_parcels`)
- Parcel merging op knooppuntuitvoer in `Junction.mix()`
- `HydraulicCache` voor pre-berekende hydraulica
- O(n log n) grenspuntsweep in `Junction.mix()`
- Lineaire segmentatie via `PipeSegmentation.calibrate()`
- Precomputed adjacency per hydraulische stap via `_build_adjacency()`

### 1.0.0
- Eerste release — FIFO-leidingmodel, PHREEQC-menging, BFS-traversal
