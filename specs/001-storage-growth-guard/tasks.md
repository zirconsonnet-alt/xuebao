# Tasks: Storage Growth Guard

**Input**: Design documents from `specs/001-storage-growth-guard/`
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/storage-growth-guard.md`, `quickstart.md`
**Tests**: Included because the feature specification defines mandatory independent tests and measurable outcomes.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel because it touches different files or independent test surfaces.
- **[Story]**: User story traceability label.
- Every task names exact file paths.

---

## Phase 1: Setup

**Purpose**: Confirm existing cleanup and write-path surfaces before adding the storage guard.

- [X] T001 Review current cleanup and optional file write entry points in `src/support/cache_cleanup.py`, `src/app.py`, `src/services/_ai/group_state.py`, `src/support/ai/__init__.py`, `src/services/bison.py`, and `src/services/composition.py`
- [X] T002 Create the focused storage guard test module with temp-path helpers in `tests/test_storage_growth_guard.py`

---

## Phase 2: Foundational

**Purpose**: Shared storage guard infrastructure that blocks all user stories.

- [X] T003 Add a public reusable bounded-root cleanup helper or wrapper in `src/support/cache_cleanup.py`
- [X] T004 Define `StorageSafetyClass`, `StorageCategoryDefinition`, `StorageCategoryReport`, `StorageReview`, `DiskGuardDecision`, and `StorageAction` in `src/support/storage_guard.py`
- [X] T005 Implement resolved-root containment, size scanning, error accounting, and threshold defaults in `src/support/storage_guard.py`
- [X] T006 Implement concise operator warning formatting in `src/support/storage_guard.py`

**Checkpoint**: Storage guard primitives exist; user stories can start.

---

## Phase 3: User Story 1 - Identify Remaining Disk Growth Sources (Priority: P1) 🎯 MVP

**Goal**: Review and report remaining growth categories outside the four existing bounded caches.

**Independent Test**: Run storage review against temp roots and verify requested categories, sizes, safety classes, warnings, and unclassified plugin caches are present.

### Tests for User Story 1

- [X] T007 [US1] Add category coverage and safety-class tests for required keys in `tests/test_storage_growth_guard.py`
- [X] T008 [US1] Add unknown plugin cache reporting tests in `tests/test_storage_growth_guard.py`

### Implementation for User Story 1

- [X] T009 [US1] Build the category registry for `.venv`, host logs, Docker artifacts, `cache/nonebot_plugin_chatrecorder`, database files, and other plugin caches in `src/support/storage_guard.py`
- [X] T010 [US1] Implement `review_storage_growth(reason="manual")` and `StorageReview` assembly in `src/support/storage_guard.py`
- [X] T011 [US1] Add warning generation for protected, manual-action, and unclassified categories in `src/support/storage_guard.py`
- [X] T012 [US1] Integrate startup and scheduled storage review logging in `src/app.py`

**Checkpoint**: US1 is independently testable as the MVP.

---

## Phase 4: User Story 2 - Bound Safe-To-Clean Growth (Priority: P2)

**Goal**: Apply limits only to explicitly safe non-core cache categories while preserving protected records.

**Independent Test**: Create oversized safe test plugin cache files and protected files, run guard cleanup, and verify only policy-covered safe files are removed.

### Tests for User Story 2

- [X] T013 [US2] Add safe auto-cleanup policy tests in `tests/test_storage_growth_guard.py`
- [X] T014 [US2] Add protected category no-delete tests for database, `.venv`, and `cache/nonebot_plugin_chatrecorder` paths in `tests/test_storage_growth_guard.py`

### Implementation for User Story 2

- [X] T015 [US2] Add explicit auto-cleanup policy validation and registration for safe plugin cache roots in `src/support/storage_guard.py`
- [X] T016 [US2] Implement `run_storage_guard(reason="scheduled")` to run existing four-category cleanup and then only clean `auto_cleanup` categories in `src/support/storage_guard.py`
- [X] T017 [US2] Add cleanup result accounting to storage category reports in `src/support/storage_guard.py`
- [X] T018 [US2] Wire scheduled execution to call `run_storage_guard` in `src/app.py`

**Checkpoint**: US1 and US2 both work without automatic deletion of protected categories.

---

## Phase 5: User Story 3 - Prevent New Large Writes When Disk Is Low (Priority: P3)

**Goal**: Refuse or degrade optional large file-producing operations before they write when disk space is unsafe.

**Independent Test**: Force the disk threshold above available space and verify each optional write path exits before creating large output files.

### Tests for User Story 3

- [X] T019 [US3] Add low-disk and `expected_bytes` decision tests in `tests/test_storage_growth_guard.py`
- [X] T020 [P] [US3] Add AI media-cache refusal regression tests in `tests/test_ai_group_context.py`
- [X] T021 [P] [US3] Add speech generation refusal regression tests in `tests/test_speech_generator_runtime.py`
- [X] T022 [P] [US3] Add bison music-card refusal regression tests in `tests/test_bison_music_card_runtime.py`
- [X] T023 [P] [US3] Add composition music-card refusal regression tests in `tests/test_composition_music_card_runtime.py`

### Implementation for User Story 3

- [X] T024 [US3] Implement `ensure_optional_write_allowed(...)` and `DiskGuardDecision` behavior in `src/support/storage_guard.py`
- [X] T025 [US3] Guard optional AI media cache writes before file creation in `src/services/_ai/group_state.py`
- [X] T026 [US3] Guard optional speech generation writes before file creation in `src/support/ai/__init__.py`
- [X] T027 [US3] Guard bison music-card download and transcode writes before file creation in `src/services/bison.py`
- [X] T028 [US3] Guard composition music-card transcode writes before file creation in `src/services/composition.py`

**Checkpoint**: All user stories are independently functional.

---

## Phase 6: Polish & Verification

**Purpose**: Documentation and focused verification for the completed slice.

- [X] T029 [P] Update operator verification notes for thresholds and warnings in `specs/001-storage-growth-guard/quickstart.md`
- [X] T030 Run focused storage guard tests for `tests/test_storage_growth_guard.py`
- [X] T031 Run regression tests for `tests/test_ai_group_context.py`, `tests/test_speech_generator_runtime.py`, `tests/test_bison_music_card_runtime.py`, and `tests/test_composition_music_card_runtime.py`
- [X] T032 Run compile smoke checks for `src/support/cache_cleanup.py`, `src/support/storage_guard.py`, and `src/app.py`
- [X] T033 Run `rg "from __future__ import annotations" src tests` and report any locations before completion

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup; blocks all user stories.
- **US1 (Phase 3)**: Depends on Foundational; MVP.
- **US2 (Phase 4)**: Depends on Foundational and uses US1 review/report structures.
- **US3 (Phase 5)**: Depends on Foundational and can proceed after storage guard decisions exist.
- **Polish (Phase 6)**: Depends on the implemented stories selected for delivery.

### User Story Dependencies

- **US1**: First delivery target; no dependency on US2 or US3.
- **US2**: Builds on US1 reporting structures so cleanup results remain visible.
- **US3**: Uses shared guard thresholds and decision records; can be implemented after Phase 2, but should be verified with the final regression suite.

### Within Each User Story

- Write or update tests before implementation tasks in that story.
- Complete `src/support/storage_guard.py` changes before wiring callers.
- Validate each story at its checkpoint before moving to broader integration.

---

## Parallel Opportunities

- T020, T021, T022, and T023 can run in parallel because they update different regression test files.
- After T024, T025, T026, T027, and T028 can be split by file if each caller follows the same `DiskGuardDecision` contract.
- T029 can run in parallel with final verification once behavior and config names are stable.

---

## Implementation Strategy

### MVP First

1. Complete T001-T006.
2. Complete T007-T012.
3. Validate US1 with `tests/test_storage_growth_guard.py`.

### Incremental Delivery

1. Deliver US1 to make remaining disk growth visible.
2. Deliver US2 to bound only explicitly safe caches.
3. Deliver US3 to prevent low-disk optional writes.
4. Run Phase 6 verification before completion.

### Verification Commands

```powershell
poetry run pytest tests/test_storage_growth_guard.py -q
poetry run pytest tests/test_ai_group_context.py tests/test_speech_generator_runtime.py tests/test_bison_music_card_runtime.py tests/test_composition_music_card_runtime.py -q
poetry run python -m compileall src/support/cache_cleanup.py src/support/storage_guard.py src/app.py
rg "from __future__ import annotations" src tests
```
