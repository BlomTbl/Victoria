# Contributing to Victoria

Bedankt voor je interesse om bij te dragen aan Victoria! We waarderen alle bijdragen, of het nu gaat om bug reports, feature requests, documentatie verbeteringen of code bijdragen.

## Code of Conduct

Wees respectvol en professioneel in alle interacties.

## Development Setup

### 1. Fork en Clone

```bash
# Fork het project op GitLab
# Clone je fork
git clone https://gitlab.com/jouw-username/victoria.git
cd victoria

# Voeg upstream remote toe
git remote add upstream https://gitlab.com/originele-username/victoria.git
```

### 2. Maak een Virtual Environment

```bash
# Maak virtual environment
python -m venv venv

# Activeer het
source venv/bin/activate  # Linux/Mac
# of
venv\Scripts\activate  # Windows
```

### 3. Installeer Development Dependencies

```bash
# Installeer package in editable mode met dev dependencies
pip install -e ".[dev]"
```

## Development Workflow

### 1. Maak een Branch

```bash
git checkout -b feature/mijn-feature
# of
git checkout -b fix/mijn-bugfix
```

Branch naming conventions:
- `feature/beschrijving` - voor nieuwe features
- `fix/beschrijving` - voor bug fixes
- `docs/beschrijving` - voor documentatie updates
- `refactor/beschrijving` - voor code refactoring

### 2. Maak je Changes

- Schrijf duidelijke, leesbare code
- Volg de bestaande code stijl
- Voeg docstrings toe aan alle functies/classes
- Update documentatie indien nodig

### 3. Run Tests

```bash
# Run alle tests
pytest tests/ -v

# Run met coverage
pytest tests/ --cov=victoria --cov-report=term-missing

# Run specifieke test
pytest tests/test_victoria.py::test_functie_naam
```

### 4. Code Quality Checks

```bash
# Format code met Black
black victoria/

# Lint met Flake8
flake8 victoria/ --max-line-length=100

# Type checking met MyPy
mypy victoria/
```

### 5. Commit Changes

```bash
git add .
git commit -m "feat: beschrijving van je feature"
```

Commit message conventie:
- `feat: ...` - nieuwe feature
- `fix: ...` - bug fix
- `docs: ...` - documentatie wijzigingen
- `style: ...` - code formatting
- `refactor: ...` - code refactoring
- `test: ...` - test toevoegingen/wijzigingen
- `chore: ...` - maintenance taken

### 6. Push en Maak Merge Request

```bash
# Push naar je fork
git push origin feature/mijn-feature
```

Ga naar GitLab en maak een Merge Request:
1. Klik op "Create merge request"
2. Vul een duidelijke titel en beschrijving in
3. Link relevante issues
4. Wacht op review

## Testing Guidelines

### Test Structure

```
tests/
├── __init__.py
├── test_victoria.py      # Tests voor main Victoria class
├── test_models.py        # Tests voor Models
├── test_solver.py        # Tests voor Solver
├── test_quality.py       # Tests voor Quality
├── test_fifo.py         # Tests voor FIFO classes
└── test_mix.py          # Tests voor MIX classes
```

### Writing Tests

```python
import pytest
from victoria import Victoria

def test_victoria_initialization():
    """Test dat Victoria correct initialiseert."""
    # Arrange
    network = create_test_network()
    pp = create_test_phreeqc()
    
    # Act
    vic = Victoria(network, pp)
    
    # Assert
    assert vic.net == network
    assert vic.pp == pp
    assert vic.models is not None

def test_step_with_invalid_timestep():
    """Test dat step een fout geeft bij negatieve timestep."""
    vic = create_victoria_instance()
    
    with pytest.raises(ValueError):
        vic.step(timestep=-1, input_sol={})
```

## Documentation

### Docstrings

Gebruik Google-stijl docstrings:

```python
def get_conc_node(self, node: Any, element: str, units: str = 'mmol') -> float:
    """
    Get instantaneous concentration at node exit.
    
    Args:
        node: Node object
        element: Chemical element/species (e.g., 'Ca', 'Cl')
        units: Units for concentration (default: 'mmol')
        
    Returns:
        Concentration value
        
    Raises:
        ValueError: If units are not supported
        
    Example:
        >>> vic = Victoria(network, pp)
        >>> cl_conc = vic.get_conc_node(node, 'Cl', 'mg/L')
        >>> print(f"Chloride: {cl_conc:.2f} mg/L")
    """
```

## Code Style

### Python Style Guide

- Volg [PEP 8](https://www.python.org/dev/peps/pep-0008/)
- Maximale line length: 100 karakters
- Use 4 spaties voor indentatie (geen tabs)
- Use snake_case voor variabelen en functies
- Use PascalCase voor classes

### Type Hints

Gebruik type hints waar mogelijk:

```python
from typing import List, Dict, Any, Optional

def process_data(
    data: List[Dict[str, Any]], 
    options: Optional[Dict] = None
) -> Dict[str, float]:
    """Process input data."""
    if options is None:
        options = {}
    # ...
    return results
```

## Reporting Issues

### Bug Reports

Gebruik de bug report template en voeg toe:
- Victoria versie
- Python versie
- EPyNet versie
- PhreeqPython versie
- Stappen om te reproduceren
- Verwacht gedrag
- Actueel gedrag
- Error messages / stack traces

### Feature Requests

Gebruik de feature request template en beschrijf:
- Probleem dat je wilt oplossen
- Voorgestelde oplossing
- Alternatieven die je hebt overwogen
- Impact op bestaande functionaliteit

## Release Process

Alleen voor maintainers:

1. Update version in `setup.py` en `victoria/__init__.py`
2. Update `CHANGELOG.md`
3. Commit: `git commit -m "chore: bump version to X.Y.Z"`
4. Tag: `git tag -a vX.Y.Z -m "Release vX.Y.Z"`
5. Push: `git push && git push --tags`
6. GitLab CI maakt automatisch release

## Questions?

- Open een issue voor vragen
- Check de documentatie
- Kijk naar bestaande issues en merge requests

## License

Door bij te dragen ga je akkoord dat je bijdragen worden gelicenseerd onder de MIT License.
