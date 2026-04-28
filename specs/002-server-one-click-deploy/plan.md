# Implementation Plan: Server One-Click Deploy

**Branch**: `002-server-one-click-deploy` | **Date**: 2026-04-29 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/002-server-one-click-deploy/spec.md`

## Summary

Add a Linux server deployment path centered on Docker Compose. The plan adds a container build definition, compose service definition, operator deploy/backup/validation scripts, safe example environment files, CI/CD workflow for push-to-deploy, and deployment documentation. Existing Windows local scripts remain local-development conveniences and are not part of the Linux deployment path.

## Technical Context

**Language/Version**: Python >=3.12,<3.15; Dockerfile/Compose YAML; POSIX shell for Linux operator scripts; GitHub Actions workflow YAML  
**Primary Dependencies**: Existing Poetry project and `bot.py` runtime; Docker Engine with Compose plugin on the server; GitHub Actions plus SSH-based deployment credentials for automated deploy  
**Storage**: Host-mounted `data/`, optional `cache/`, deployment logs through container logs, timestamped backups under an operator-visible backup directory  
**Testing**: Static checks for deployment files, shell syntax checks when available, Docker Compose config validation, existing pytest smoke/regression tests where practical  
**Target Platform**: Linux server running Docker Compose  
**Project Type**: Single Python bot/service repository with deployment automation  
**Performance Goals**: First prepared deployment under 15 minutes; repeat deploy via one command; push-to-deploy result visible within 10 minutes for normal changes; restart after crash/reboot within 2 minutes  
**Constraints**: Do not commit real secrets, private keys, server addresses, or production env values; do not break existing Windows `install.bat`/`run.bat`; no `from __future__ import annotations`; protect existing production data before risky update steps  
**Scale/Scope**: One bot service container, one Linux host target, one explicitly allowed deploy branch, persistent local host volumes for runtime data

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

The constitution file still contains template placeholders rather than ratified project rules. No enforceable constitution gates are available for this feature. Project-specific AGENTS rules apply:

- Chinese communication and minimal necessary changes.
- Only execute confirmed decisions.
- Keep implementation scoped to Docker Compose + Linux + CI/CD deployment, as confirmed by the user.
- Do not add `from __future__ import annotations`.
- Do not delete or rewrite existing runtime data or unrelated scripts.

Status: PASS, with no active constitution constraints.

## Project Structure

### Documentation (this feature)

```text
specs/002-server-one-click-deploy/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── server-one-click-deploy.md
└── tasks.md
```

### Source Code (repository root)

```text
Dockerfile                         # planned Linux container image definition
docker-compose.yml                 # planned service, restart, env, and volume policy
.env.example                       # planned non-secret configuration template
.dockerignore                      # planned build context exclusions
.github/
└── workflows/
    └── deploy.yml                 # planned push-to-deploy workflow

scripts/
├── deploy.sh                      # planned one-command server deploy/update entry
├── backup-data.sh                 # planned data backup helper
└── validate-deploy-env.sh         # planned required configuration validator

docs/
└── deployment-guide.md            # planned expanded Linux deployment guide

bot.py                             # existing runtime entry, no planned behavior change unless required for deployment
pyproject.toml                     # existing dependency source, no planned dependency changes unless Docker build proves necessary
data/                              # host-mounted persistent runtime state
cache/                             # optional host-mounted cache depending on final compose policy
```

**Structure Decision**: Keep deployment at the repository root where operators expect `Dockerfile`, `docker-compose.yml`, and `.env.example`. Put reusable Linux operator scripts in existing `scripts/`. Keep GitHub Actions under `.github/workflows/`. Update only deployment documentation under `docs/`.

## Complexity Tracking

No constitution violations or extra project complexity are planned.
