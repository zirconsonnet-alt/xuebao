# Implementation Plan: Storage Growth Guard

**Branch**: `001-storage-growth-guard` | **Date**: 2026-04-29 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/001-storage-growth-guard/spec.md`

## Summary

Add a storage guard layer around disk growth sources not covered by the existing four runtime cache cleanups. The implementation will keep existing cache cleanup behavior, add a read-only storage review for protected/manual categories, add explicit cleanup only for categories marked safe, and gate optional large file-producing operations when free disk space is below a configurable safety threshold.

## Technical Context

**Language/Version**: Python >=3.12,<3.15  
**Primary Dependencies**: NoneBot2, nonebot-plugin-apscheduler, nonebot-plugin-localstore, nonebot-plugin-chatrecorder, nonebot-plugin-orm/datastore, aiofiles/httpx, yt-dlp, existing `src.support.cache_cleanup` helpers  
**Storage**: Local filesystem under repo/runtime cwd, `.venv`, `data/`, `cache/`, SQLite/database files, plugin localstore cache/data paths, external host/Docker/log locations reported when discoverable  
**Testing**: pytest, pytest-asyncio, compile-time smoke checks  
**Target Platform**: Long-running NoneBot service on a disk-limited server  
**Project Type**: Single Python bot/service repository  
**Performance Goals**: Storage review should avoid blocking the event loop and run in a background thread; scheduled review must finish within one interval for normal repo-sized storage trees  
**Constraints**: Do not auto-delete `.venv`, databases, host-managed logs, Docker artifacts, or chat recorder data without explicit policy; no `from __future__ import annotations`; keep cleanup scoped to resolved paths under configured roots  
**Scale/Scope**: One bot process, multiple groups/plugins, storage growth sources under `.venv`, `cache/`, `data/`, database files, and externally managed operator storage

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

The constitution file still contains template placeholders rather than ratified project rules. No enforceable constitution gates are available for this feature. Project-specific AGENTS rules apply:

- Chinese communication and minimal necessary changes.
- Do not delete protected/runtime data without explicit policy.
- Do not add `from __future__ import annotations`.
- Plan only for this command; implementation code changes belong to later phases.

Status: PASS, with no active constitution constraints.

## Project Structure

### Documentation (this feature)

```text
specs/001-storage-growth-guard/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── storage-growth-guard.md
└── tasks.md
```

### Source Code (repository root)

```text
src/
├── app.py                         # startup/scheduled storage review integration
├── support/
│   ├── cache_cleanup.py            # existing bounded cleanup for the four current categories
│   └── storage_guard.py            # planned review, classification, low-disk guard
├── services/
│   ├── _ai/group_state.py          # optional media cache writes
│   ├── bison.py                    # optional music-card download/transcode writes
│   └── composition.py              # optional music-card transcode writes
└── support/ai/__init__.py          # optional speech generation writes

tests/
├── test_storage_growth_guard.py
├── test_ai_group_context.py
├── test_speech_generator_runtime.py
├── test_bison_music_card_runtime.py
└── test_composition_music_card_runtime.py
```

**Structure Decision**: Keep this as a single-project Python change. Add one focused support module for storage review and low-disk decisions, then wire it into existing startup/scheduled cleanup and known optional file-producing write paths.

## Complexity Tracking

No constitution violations or extra project complexity are planned.
