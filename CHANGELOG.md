# Changelog

Alle belangrijke wijzigingen aan dit project worden gedocumenteerd in dit bestand.

Het formaat is gebaseerd op [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
en dit project volgt [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned
- Unit tests voor alle modules
- Integration tests met EPyNet en PHREEQC
- Performance optimalisaties voor grote netwerken
- Ondersteuning voor meer tank modellen
- Export functionaliteit naar CSV/Excel

## [1.0.0] - 2024-02-11

### Added
- **Core Functionaliteit**
  - Victoria hoofdclass voor water quality simulatie
  - Integratie met EPyNet voor hydraulische simulatie
  - Integratie met PHREEQC voor water chemie berekeningen

- **FIFO Module** (`fifo.py`)
  - `FIFO` basisclass voor link objecten
  - `Pipe` class met volume-based parcel tracking
  - `Pump` class voor instantaneous passage
  - `Valve` class voor instantaneous passage
  - Parcel push/pull mechanisme
  - Flow reversal handling

- **MIX Module** (`mix.py`)
  - `MIX` basisclass voor node mixing
  - `Junction` met ideal mixing en demand handling
  - `Reservoir` als water bron
  - `Tank_CSTR` - Continuous Stirred Tank Reactor model
  - `Tank_FIFO` - First In First Out tank model
  - `Tank_LIFO` - Last In First Out tank model
  - Compatibility layer voor verschillende EPyNet API versies

- **Models Module** (`models.py`)
  - Automatische model creatie voor alle network componenten
  - Volume berekening voor pipes
  - Model lookup functionaliteit
  - Support voor junctions, reservoirs, tanks, pipes, pumps, valves

- **Solver Module** (`solver.py`)
  - Recursive water parcel tracing
  - Network filling functionaliteit
  - Flow direction checking
  - Ready state management
  - EPyNet API compatibility layer

- **Quality Module** (`quality.py`)
  - Concentratie berekeningen voor nodes en pipes
  - PHREEQC solution mixing
  - Support voor instantaneous en time-averaged waarden
  - Water properties (pH, conductivity, temperature)
  - Multiple unit support (mmol, mg/L, mol, ppm)

- **API Methods**
  - `fill_network()` - initialiseer netwerk met start kwaliteit
  - `step()` - simuleer één tijdstap
  - `check_flow_direction()` - handel flow reversals af
  - `garbage_collect()` - memory management
  - `get_conc_node()` - concentratie aan node
  - `get_conc_node_avg()` - tijdgemiddelde concentratie aan node
  - `get_mixture_node()` - solution mixture aan node
  - `get_conc_pipe()` - concentratie profiel in pipe
  - `get_conc_pipe_avg()` - volume-gewogen gemiddelde in pipe
  - `get_parcels()` - alle parcels in pipe
  - `get_properties_node()` - water eigenschappen aan node

- **Documentatie**
  - Uitgebreide README met voorbeelden
  - Docstrings voor alle classes en methods
  - Type hints voor betere IDE ondersteuning
  - Installatie instructies
  - API reference

- **Package Configuratie**
  - `setup.py` voor package installatie
  - `pyproject.toml` voor moderne Python packaging
  - `requirements.txt` met dependencies
  - `MANIFEST.in` voor file inclusion
  - `.gitignore` voor proper version control
  - MIT License

### Features
- Support voor complexe hydraulische netwerken
- Parcel tracking met hoge nauwkeurigheid
- Flexible tank mixing modellen
- Complete PHREEQC chemie ondersteuning
- Efficient memory management
- Cross-platform compatibiliteit (Windows, Linux, macOS)

### Dependencies
- Python >= 3.7
- epynet >= 0.2.0
- phreeqpython >= 1.2.0

### Technical Details
- Pipe volume berekening: V = π/4 × L × D²
- CSTR mixing: exponential decay model
- FIFO/LIFO: position-based parcel tracking
- Numerical precision: 6-10 decimal places voor stability

### Known Limitations
- Network egress vereist active internet (indien geconfigureerd)
- PHREEQC solution nummers moeten uniek zijn
- Flow reversals vereisen expliciete check_flow_direction() aanroep
- Zeer kleine flows (< 0.001 m/s) worden geskipped

## [0.9.0] - Pre-release (Internal)

### Added
- Initiële implementatie van core functionaliteit
- Basis FIFO en MIX modules
- Eerste PHREEQC integratie tests

---

## Toekomstige Versies

### [1.1.0] - Gepland
- [ ] Unit test suite
- [ ] Integration tests
- [ ] Performance benchmarks
- [ ] Additional tank models (2-layer, multi-compartment)
- [ ] Export functionaliteit (CSV, Excel, HDF5)
- [ ] Visualisatie tools
- [ ] Parallel processing support

### [1.2.0] - Gepland
- [ ] Real-time monitoring mode
- [ ] Database integration
- [ ] REST API
- [ ] Web interface
- [ ] Advanced reporting
- [ ] Uncertainty analysis

### [2.0.0] - Gepland
- [ ] Complete rewrite in Cython voor performance
- [ ] GPU acceleration voor grote netwerken
- [ ] Machine learning water quality predictions
- [ ] Cloud deployment support
- [ ] Microservices architecture

---

## Contribution Guidelines

Zie [CONTRIBUTING.md](CONTRIBUTING.md) voor details over hoe bij te dragen aan dit project.

## Links

- **GitLab Repository**: [Link naar repo]
- **Documentation**: [Link naar docs]
- **Issue Tracker**: [Link naar issues]
- **PyPI Package**: [Link naar PyPI]

## Versioning

We volgen [Semantic Versioning](https://semver.org/):
- MAJOR version voor incompatible API changes
- MINOR version voor nieuwe functionaliteit (backwards compatible)
- PATCH version voor bug fixes

## Maintainers

- Victoria Contributors

## License

Dit project is gelicenseerd onder de MIT License - zie [LICENSE](LICENSE) voor details.
