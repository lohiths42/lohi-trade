# Contributing to LoHi-Trade

Thanks for your interest in contributing! We welcome improvements, bug fixes, and new strategies.

Quickstart
- Fork the repository and open a feature branch from `main`.
- Run tests locally:

```bash
source lohi_trade_venv/bin/activate
pip install -e .[dev]
pytest -q
```

Code style
- Use `ruff` for linting and formatting.
- Follow existing project conventions for type hints and logging.

Pull requests
- Keep PRs small and focused.
- Target the `main` branch and describe the change in the PR body.
- Include tests for new behavior or bug fixes.

Issue reporting
- Search existing issues before opening a new one.
- Provide reproducible steps and any logs or test failures.

Security
- Do not commit secrets or credentials. Use environment variables and `.env.*` templates.
- If you find a security issue, please open a private issue or contact the maintainers.

Maintainers
- The core maintainers will review incoming PRs and merge when ready.
# Contributing to LOHI-TRADE

Thank you for your interest in contributing to LOHI-TRADE! This document provides guidelines and instructions for contributing to the project.

## Table of Contents

1. [Code of Conduct](#code-of-conduct)
2. [Getting Started](#getting-started)
3. [Development Workflow](#development-workflow)
4. [Coding Standards](#coding-standards)
5. [Testing](#testing)
6. [Submitting Changes](#submitting-changes)
7. [Reporting Bugs](#reporting-bugs)
8. [Requesting Features](#requesting-features)

---

## Code of Conduct

We are committed to providing a welcoming and inspiring community for all. Please read and adhere to our [Code of Conduct](CODE_OF_CONDUCT.md) in all interactions.

**TL;DR**: Be respectful, inclusive, and constructive. No harassment, discrimination, or toxic behavior.

---

## Getting Started

### Prerequisites

- Python 3.11+
- Git
- Docker & Docker Compose (for full-stack testing)
- Node.js 18+ (for frontend)

### Setting Up Development Environment

```bash
# 1. Clone the repository
git clone https://github.com/AdhirU/Lohi-Trade-OpenSource.git
cd Lohi-Trade-OpenSource

# 2. Create and activate virtual environment
python -m venv lohi_dev_venv
source lohi_dev_venv/bin/activate  # On Windows: lohi_dev_venv\Scripts\activate

# 3. Install in editable mode with all dependencies
pip install -e .[all,dev]

# 4. Verify installation
lohi doctor

# 5. Run tests
pytest tests/ --ignore=tests/research -v

# 6. Start the application (optional)
lohi setup --skip-docker --skip-frontend --no-browser
```

---

## Development Workflow

### 1. Create an Issue (For Non-Trivial Changes)

Before starting work on a significant feature or bug fix:
- Check if an issue already exists
- Create a new issue with:
  - Clear description of the problem/feature
  - Expected vs actual behavior (for bugs)
  - Proposed solution (optional)

### 2. Fork and Branch

```bash
# Fork the repository on GitHub

# Clone your fork
git clone https://github.com/YOUR_USERNAME/Lohi-Trade-OpenSource.git
cd Lohi-Trade-OpenSource

# Add upstream remote
git remote add upstream https://github.com/AdhirU/Lohi-Trade-OpenSource.git

# Create a feature branch
git checkout -b feature/your-feature-name
# or
git checkout -b fix/your-bug-fix-name
```

### 3. Make Changes

- Write clean, well-documented code
- Follow the coding standards below
- Add tests for new functionality
- Update relevant documentation

### 4. Keep Your Branch Updated

```bash
git fetch upstream
git rebase upstream/main
```

### 5. Commit with Clear Messages

```bash
git commit -m "feat: Add new signal filter for oversold conditions

- Implements RSI < 30 filter
- Adds configuration option in settings.yaml
- Includes unit tests in test_signal_filter.py
- Resolves #123"
```

**Commit message format**:
```
<type>: <subject>

<body>

<footer>
```

**Types**: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `chore`

### 6. Push and Create Pull Request

```bash
git push origin feature/your-feature-name
```

Then open a Pull Request on GitHub with:
- Clear title describing the change
- Reference to related issue (e.g., "Fixes #123")
- Description of changes and testing performed
- Checklist of requirements

---

## Coding Standards

### Python Style Guide

We follow [PEP 8](https://www.python.org/dev/peps/pep-0008/) with these extensions:

#### Line Length
- Maximum 100 characters (not strict for docstrings/URLs)

#### Type Hints
- Use type hints for function parameters and return types
```python
from typing import Optional, Dict, List

def process_signals(
    signals: List[Dict[str, float]],
    rms_check: bool = True
) -> Optional[Dict[str, float]]:
    """Process trading signals with optional RMS validation."""
    pass
```

#### Docstrings
- Use Google-style docstrings
```python
def calculate_position_size(
    capital: float,
    risk_percent: float,
    stop_loss_distance: float
) -> float:
    """Calculate position size based on risk management.

    Args:
        capital: Total trading capital in rupees.
        risk_percent: Risk per trade as percentage (e.g., 2.0 for 2%).
        stop_loss_distance: Distance to stop loss in rupees.

    Returns:
        Position size in shares (quantity).

    Raises:
        ValueError: If risk_percent > 100 or any input negative.
    """
    pass
```

#### Imports
- Group imports: stdlib → third-party → local
- Sort alphabetically within groups
```python
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional

import aioredis
import pandas as pd
from pydantic import BaseModel

from src.broker import BrokerInterface
from src.utils import logger
```

### Formatting

**Automatic formatting** (required):
```bash
# Format with black
black src/ tests/ scripts/

# Check with ruff
ruff check src/ tests/ scripts/ --fix

# Type check with mypy
mypy src/
```

**Before committing**:
```bash
# Run all checks
black src/ tests/ scripts/
ruff check src/ tests/ scripts/ --fix
mypy src/
```

### Naming Conventions

| Type | Convention | Example |
|------|-----------|---------|
| Functions | snake_case | `process_orders()` |
| Classes | PascalCase | `OrderManagementSystem` |
| Constants | UPPER_SNAKE_CASE | `MAX_POSITION_SIZE` |
| Private methods | _snake_case | `_validate_signal()` |
| Module names | snake_case | `position_manager.py` |

---

## Testing

### Test Coverage Requirements

- Minimum 80% for new code
- Maintain or improve overall coverage (currently 39%)
- Use descriptive test names

### Running Tests

```bash
# Run all core tests
pytest tests/ --ignore=tests/research -v

# Run specific test file
pytest tests/test_rms.py -v

# Run with coverage report
pytest tests/ --ignore=tests/research --cov=src --cov-report=html

# Run property-based tests only
pytest tests/ -k "prop_" -v

# Run with specific markers
pytest tests/ -m "integration" -v
```

### Writing Tests

```python
import pytest
from hypothesis import given, strategies as st

def test_position_sizing_respects_capital_limit():
    """Position size should never exceed capital."""
    sizer = PositionSizer(capital=100_000)

    size = sizer.calculate(risk_percent=2.0, stop_distance=50)

    assert size * current_price <= 100_000
    assert size > 0


@given(st.floats(min_value=0.1, max_value=10.0))
def test_position_size_scales_with_risk(risk_percent):
    """Larger risk should produce larger positions."""
    sizer = PositionSizer(capital=100_000)

    small = sizer.calculate(risk_percent=1.0, stop_distance=100)
    large = sizer.calculate(risk_percent=risk_percent, stop_distance=100)

    if risk_percent > 1.0:
        assert large >= small
```

### Test Organization

```
tests/
├── test_broker_*.py        # Broker integration tests
├── test_rms*.py            # Risk management tests
├── test_oms*.py            # Order management tests
├── test_prop_*.py          # Property-based tests
├── test_integration_*.py   # Integration tests
└── research/               # Research subsystem tests
    ├── test_*.py
    └── conftest.py
```

---

## Submitting Changes

### Pull Request Checklist

- [ ] Code follows project style guide
- [ ] All tests pass locally: `pytest tests/ --ignore=tests/research -v`
- [ ] Code coverage maintained or improved
- [ ] New features include documentation/docstrings
- [ ] Commit messages are clear and descriptive
- [ ] Branch is up-to-date with main: `git rebase upstream/main`
- [ ] No merge conflicts

### PR Review Process

1. **CI Checks**: GitHub Actions runs tests, linting, coverage
2. **Code Review**: At least one maintainer reviews the code
3. **Discussion**: Address feedback and make requested changes
4. **Approval**: PR is approved and merged

---

## Reporting Bugs

### Bug Report Template

```markdown
## Description
Brief description of the bug.

## Steps to Reproduce
1. Install with `pip install lohi-trade[all]`
2. Run `lohi setup`
3. Configure broker X
4. ...
5. Bug occurs

## Expected Behavior
What should happen.

## Actual Behavior
What actually happens.

## Error Message/Logs
```
[error stack trace]
```

## Environment
- OS: macOS 14.0
- Python: 3.13.0
- Branch: main
- Commit: abc123def
- Optional features: `pip install lohi-trade[ml]` or `lohi-trade[all]`

## Additional Context
Any other relevant information.
```

---

## Requesting Features

### Feature Request Template

```markdown
## Summary
One-sentence description of the feature.

## Motivation
Why would this feature be useful? What problem does it solve?

## Proposed Solution
How should the feature work? Any design thoughts?

## Alternatives Considered
What else could solve this problem?

## Additional Context
Any mockups, links, or examples?
```

---

## Areas We're Looking For Help

### High Priority
- [ ] CLI integration tests (currently untested)
- [ ] Mobile app documentation/testing
- [ ] Broker-specific setup guides
- [ ] Performance optimization

### Medium Priority
- [ ] Example strategies (beyond mean reversion, ORB, trend)
- [ ] Documentation improvements
- [ ] Code examples and tutorials
- [ ] Community support in discussions

### Low Priority (But Welcome)
- [ ] UI/UX improvements
- [ ] Additional indicators
- [ ] New broker integrations
- [ ] Helm charts/Kubernetes support

---

## Documentation

### Update Documentation When

- Adding a new feature
- Changing existing behavior
- Fixing a bug that affects usage
- Adding a new broker/strategy

### Documentation Locations

- **Setup**: `SETUP.md`
- **Architecture**: `docs/ARCHITECTURE.md`
- **API**: Backend code docstrings
- **Troubleshooting**: `README.md#troubleshooting`

---

## Questions?

- **GitHub Discussions**: Ask questions in [Discussions](https://github.com/AdhirU/Lohi-Trade-OpenSource/discussions)
- **Issues**: Report bugs in [Issues](https://github.com/AdhirU/Lohi-Trade-OpenSource/issues)
- **Reach Out**: Email or Telegram (add contact if available)

---

## Recognition

Contributors will be:
- Added to `CONTRIBUTORS.md`
- Thanked in release notes
- Given credit in commit messages

**Thank you for contributing to LOHI-TRADE!** 🙏
