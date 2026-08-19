<p align="center">
  <img src="https://raw.githubusercontent.com/opentreecz/.github/master/profile/img/opentreeczlogo.jpeg" alt="opentree.cz" width="150"/>
</p>

> **Full documentation:** [opentreecz.github.io/openrepo](https://opentreecz.github.io/openrepo/)

# Contributing to OpenRepo

Thank you for your interest in contributing to OpenRepo! This document provides guidelines and instructions for contributing.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Making Changes](#making-changes)
- [Coding Standards](#coding-standards)
- [Testing](#testing)
- [Submitting Changes](#submitting-changes)
- [Issue Reporting](#issue-reporting)
- [Architecture Overview](#architecture-overview)

## Code of Conduct

By participating in this project, you agree to be respectful and constructive in all interactions. We are committed to providing a welcoming and inclusive environment for everyone.

## Getting Started

1. **Fork the repository** on GitHub
2. **Clone your fork** locally:
   ```bash
   git clone https://github.com/<your-username>/openrepo.git
   cd openrepo
   ```
3. **Add the upstream remote**:
   ```bash
   git remote add upstream https://github.com/opentreecz/openrepo.git
   ```
4. **Create a feature branch**:
   ```bash
   git checkout -b feature/your-feature-name
   ```

## Development Setup

### Prerequisites

- Python 3.10+
- Node.js 20.x
- PostgreSQL 16 (or SQLite for quick development)
- System packages: `createrepo-c`, `gpg`, `libapt-pkg-dev`

### Backend Setup

```bash
cd web
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Create required directories
mkdir -p /tmp/openrepo/storage /tmp/openrepo/repos /tmp/openrepo/keyring

# Run migrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Run the development server
python manage.py runserver
```

### Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

### Running with Docker (recommended for full stack)

```bash
docker compose up --build
```

## Making Changes

1. **Keep changes focused**: Each PR should address a single concern
2. **Follow existing patterns**: Look at how similar features are implemented
3. **Update tests**: Add tests for new functionality, update tests for changed behavior
4. **Update documentation**: If your changes affect user-facing behavior

## Coding Standards

### Python (Backend)

- Follow PEP 8 with a max line length of 120 characters
- Use `flake8` for linting (configuration in `.flake8`)
- Use meaningful variable and function names
- Add docstrings to public functions and classes
- Use type hints where practical

```bash
# Run linting
cd web && flake8 .
cd cli && flake8 .
```

### TypeScript/Vue (Frontend)

- Follow the existing Vue 3 Composition/Options API patterns
- Use TypeScript types where possible
- Follow ESLint rules (configuration in `frontend/.eslintrc.*`)

```bash
# Run linting
cd frontend && npm run lint

# Run type checking
cd frontend && npm run type-check
```

### Commit Messages

- Use clear, descriptive commit messages
- Start with a verb in present tense (e.g., "Add", "Fix", "Update")
- Reference issue numbers when applicable (e.g., "Fix #123: ...")
- Keep the first line under 72 characters

Examples:
```
Add multi-arch checkbox to create repository dialog
Fix retention policy not applying per-architecture
Update documentation for bare-metal deployment
```

## Testing

### Backend Tests

```bash
cd web
python manage.py test repo.tests --verbosity=2
```

### Running with Coverage

```bash
cd web
coverage run manage.py test repo.tests
coverage report --show-missing
```

### CLI Tests

```bash
cd cli
PYTHONPATH=. python tests/test_cli.py
```

### Frontend

```bash
cd frontend
npm run lint
npm run type-check
```

### Integration Tests

Integration tests require system packages (`createrepo-c`, `gpg`, `python3-apt`):

```bash
cd web
python manage.py test repo.tests.test_integration --verbosity=2
```

## Submitting Changes

1. **Ensure all tests pass** locally
2. **Ensure linting passes** (`flake8` and `eslint`)
3. **Push your branch** to your fork:
   ```bash
   git push origin feature/your-feature-name
   ```
4. **Open a Pull Request** against the `main` branch
5. **Fill in the PR template** completely
6. **Respond to review feedback** promptly

### PR Review Process

- All PRs require at least one approval before merging
- CI checks (tests, linting) must pass
- PRs should be rebased on the latest `main` before merging
- Squash commits if the history is noisy

## Issue Reporting

### Bug Reports

Use the [Bug Report template](https://github.com/opentreecz/openrepo/issues/new?template=bug_report.yml) and include:

- Steps to reproduce
- Expected vs. actual behavior
- Environment details (OS, deployment method, version)
- Relevant logs

### Feature Requests

Use the [Feature Request template](https://github.com/opentreecz/openrepo/issues/new?template=feature_request.yml) and include:

- Problem statement
- Proposed solution
- Alternatives considered

## Architecture Overview

OpenRepo runs as four cooperating processes:

1. **Nginx** - Serves the Vue frontend, static files, and hosted repository files. Proxies API requests to Django.
2. **Django** (Gunicorn) - REST API and admin interface.
3. **Worker** - Background process that regenerates repository metadata and applies retention policies.
4. **PostgreSQL** - Relational database.

### Key Directories

| Directory | Purpose |
|-----------|---------|
| `web/repo/` | Django app: models, API, signals, worker |
| `web/adapters/` | Package format adapters (deb, rpm, generic) |
| `frontend/src/` | Vue.js 3 SPA with Vuetify |
| `cli/` | Python CLI tool for CI/CD integration |
| `docs/` | GitHub Pages documentation (Jekyll) |
| `deploy/` | Nginx configs, startup scripts |

### Multi-Architecture Support

OpenRepo supports hosting packages for multiple architectures in a single repository:

- **Debian repos**: Enable `multi_arch` to generate per-architecture `binary-<arch>/` directories (e.g., `binary-amd64/`, `binary-arm64/`). `Architecture: all` packages are included in every arch index per Debian Policy.
- **RPM repos**: Architecture is handled natively by `createrepo`. All architectures coexist in a single repo, and `dnf`/`yum` clients filter by their system architecture.

### Adding a New Package Format

1. Create a file adapter in `web/adapters/file/` implementing `RepoFileAdapter`
2. Create a repo adapter in `web/adapters/repo/` implementing `BaseRepoAdapter`
3. Register the adapter in the respective `__init__.py` factory functions
4. Add the repo type choice to `Repository.REPO_TYPES`
5. Update frontend to include the new type in the create dialog

## License

By contributing to OpenRepo, you agree that your contributions will be licensed under the GNU Affero General Public License v3.0 (AGPL-3.0).

## Questions?

If you have questions about contributing, please open a [Discussion](https://github.com/opentreecz/openrepo/discussions) or reach out via the issue tracker.
