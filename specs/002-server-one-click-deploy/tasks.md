# Tasks: Server One-Click Deploy

**Input**: Design documents from `specs/002-server-one-click-deploy/`
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md`

**Tests**: The feature specification requires independent verification for each user story. Verification tasks below focus on deploy configuration, script behavior, persistence, and workflow behavior without requiring unrelated application changes.

**Organization**: Tasks are grouped by user story so each story can be implemented and verified independently.

## Phase 1: Setup (Shared Deployment Files)

**Purpose**: Create the deployment file surface without changing bot behavior.

- [X] T001 Review current runtime and documented environment assumptions in `bot.py`, `pyproject.toml`, `docs/README.md`, and `docs/deployment-guide.md`
- [X] T002 Create deployment file skeletons in `Dockerfile`, `docker-compose.yml`, `.dockerignore`, and `.env.example`
- [X] T003 Create Linux deployment script skeletons in `scripts/deploy.sh`, `scripts/validate-deploy-env.sh`, and `scripts/backup-data.sh`
- [X] T004 Create push-to-deploy workflow skeleton in `.github/workflows/deploy.yml`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Define shared deployment contracts that all user stories rely on.

**Critical**: No user story work should begin until this phase is complete.

- [X] T005 Define safe Docker build exclusions in `.dockerignore`
- [X] T006 Define non-secret required configuration placeholders in `.env.example`
- [X] T007 Implement required environment and placeholder validation in `scripts/validate-deploy-env.sh`
- [X] T008 Implement the container image build for the existing `bot.py` entry in `Dockerfile`
- [X] T009 Define the base bot service, `.env` loading, restart policy, and persistent mount placeholders in `docker-compose.yml`
- [X] T010 Add deployment guide sections for prerequisites, configuration, manual deploy, logs, backups, and push-to-deploy in `docs/deployment-guide.md`

**Checkpoint**: Docker, Compose, env validation, and documentation structure are ready.

---

## Phase 3: User Story 1 - First Server Deploy (Priority: P1) MVP

**Goal**: A prepared Linux server can deploy and run the bot with one clear command, and missing configuration fails before startup.

**Independent Test**: On a Linux host with Docker installed, create `.env` from `.env.example`, confirm placeholder values fail validation, fill required values, run `scripts/deploy.sh`, and verify `docker compose ps` shows the bot service running.

### Implementation for User Story 1

- [X] T011 [US1] Implement Linux prerequisite checks for Docker, Docker Compose, repository root, and writable paths in `scripts/deploy.sh`
- [X] T012 [US1] Wire `scripts/deploy.sh` to call `scripts/validate-deploy-env.sh` before any service start in `scripts/deploy.sh`
- [X] T013 [US1] Implement first-time directory creation for configured data, cache, and backup paths in `scripts/deploy.sh`
- [X] T014 [US1] Implement build and startup flow using `docker-compose.yml` in `scripts/deploy.sh`
- [X] T015 [US1] Implement running-service verification and clear success or failure output in `scripts/deploy.sh`
- [X] T016 [US1] Document first-time deployment and missing-configuration failure behavior in `docs/deployment-guide.md`
- [X] T017 [US1] Verify Compose configuration and first-deploy commands against `specs/002-server-one-click-deploy/quickstart.md`

**Checkpoint**: User Story 1 is independently deployable and testable.

---

## Phase 4: User Story 2 - Persistent Data, Logs, and Backup Safety (Priority: P2)

**Goal**: Runtime data and logs survive restarts and redeploys, and risky updates create a visible backup first.

**Independent Test**: Deploy once, create or observe data under the mounted data path, redeploy, confirm data remains, run `scripts/backup-data.sh`, confirm a timestamped backup appears, and inspect logs through `docker compose logs --tail=100 bot`.

### Implementation for User Story 2

- [X] T018 [US2] Implement timestamped backup creation for configured data paths in `scripts/backup-data.sh`
- [X] T019 [US2] Implement backup failure handling that blocks risky update steps in `scripts/backup-data.sh`
- [X] T020 [US2] Wire pre-update backup behavior into `scripts/deploy.sh`
- [X] T021 [US2] Finalize data, optional cache, and backup host path variables in `.env.example`
- [X] T022 [US2] Finalize persistent data and optional cache mounts in `docker-compose.yml`
- [X] T023 [US2] Document persistent storage, backup, restore expectations, and log inspection in `docs/deployment-guide.md`
- [X] T024 [US2] Verify persistence, backup, and log inspection steps against `specs/002-server-one-click-deploy/quickstart.md`

**Checkpoint**: User Stories 1 and 2 work independently without losing runtime data.

---

## Phase 5: User Story 3 - Push-To-Deploy Update (Priority: P3)

**Goal**: Pushes to the allowed deployment branch trigger automated server deployment, while failures are visible and do not silently replace the previous working service.

**Independent Test**: Configure repository secrets, push to the allowed branch, confirm the workflow runs and invokes `scripts/deploy.sh` on the server, confirm non-deploy branches do not deploy, and confirm a simulated safe failure reports visibly without silently replacing the working service.

### Implementation for User Story 3

- [X] T025 [US3] Configure allowed-branch trigger rules in `.github/workflows/deploy.yml`
- [X] T026 [US3] Define required SSH and target path secret inputs in `.github/workflows/deploy.yml`
- [X] T027 [US3] Add repository validation steps before remote deployment in `.github/workflows/deploy.yml`
- [X] T028 [US3] Add SSH remote deployment step that invokes `scripts/deploy.sh` from the server checkout in `.github/workflows/deploy.yml`
- [X] T029 [US3] Add workflow result output and failure visibility guidance in `.github/workflows/deploy.yml`
- [X] T030 [US3] Document required GitHub secrets and push-to-deploy verification in `docs/deployment-guide.md`
- [X] T031 [US3] Verify allowed-branch and non-deploy branch behavior against `.github/workflows/deploy.yml`

**Checkpoint**: All user stories are independently functional and documented.

---

## Phase 6: Polish & Cross-Cutting Verification

**Purpose**: Validate the deployment feature as a whole without expanding scope.

- [ ] T032 [P] Validate shell script syntax for `scripts/deploy.sh`, `scripts/validate-deploy-env.sh`, and `scripts/backup-data.sh`
- [X] T033 [P] Validate that tracked deployment files contain no real secrets in `.env.example`, `docker-compose.yml`, and `.github/workflows/deploy.yml`
- [ ] T034 [P] Run existing regression checks with `poetry run pytest -q`
- [X] T035 Update `specs/002-server-one-click-deploy/quickstart.md` if implemented commands differ from the planned verification flow
- [X] T036 Confirm existing Windows local-development scripts remain usable in `install.bat` and `run.bat`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 Setup**: No dependencies.
- **Phase 2 Foundational**: Depends on Phase 1 and blocks all user stories.
- **Phase 3 US1**: Depends on Phase 2 and is the MVP.
- **Phase 4 US2**: Depends on Phase 2; can be developed after US1 or in parallel with care because it touches `scripts/deploy.sh`, `docker-compose.yml`, `.env.example`, and docs.
- **Phase 5 US3**: Depends on Phase 2 and the manual deployment entry in `scripts/deploy.sh`.
- **Phase 6 Polish**: Depends on the desired user stories being complete.

### User Story Dependencies

- **US1 First Server Deploy**: Independent after Foundation.
- **US2 Persistent Data, Logs, and Backup Safety**: Independent after Foundation, but final integration uses the deploy command from US1.
- **US3 Push-To-Deploy Update**: Depends on the manual deploy entry from US1 because CI/CD invokes the same script.

### Within Each User Story

- Validation and safety checks should precede service replacement.
- Script behavior should be implemented before documentation verification.
- Story verification should run before moving to the next story when delivering incrementally.

---

## Parallel Opportunities

- T002, T003, and T004 can run in parallel after T001.
- T005, T006, T008, T009, and T010 can run in parallel; T007 depends on the required keys defined by T006.
- In US2, T018 and T021 can run in parallel; T020 depends on T018 and T019.
- In US3, T025 and T026 can run in parallel; T028 depends on the workflow inputs from T026.
- T032, T033, and T034 can run in parallel during final verification.

---

## Parallel Example: User Story 2

```bash
# Parallelizable work once Foundation is complete:
Task: "Implement timestamped backup creation for configured data paths in scripts/backup-data.sh"
Task: "Finalize data, optional cache, and backup host path variables in .env.example"
Task: "Finalize persistent data and optional cache mounts in docker-compose.yml"
```

---

## Implementation Strategy

### MVP First

1. Complete Phase 1.
2. Complete Phase 2.
3. Complete Phase 3 for US1.
4. Stop and validate first server deployment with `scripts/deploy.sh` and `docker compose ps`.

### Incremental Delivery

1. Deliver US1 for first deploy.
2. Add US2 for persistence, backups, and logs.
3. Add US3 for push-to-deploy.
4. Run Phase 6 verification.

### Scope Guard

- Do not change bot runtime behavior unless deployment wiring proves it is required.
- Do not commit real secrets, hostnames, tokens, private keys, cookies, or production identifiers.
- Do not remove or break `install.bat` or `run.bat`; they remain local Windows development entry points.
