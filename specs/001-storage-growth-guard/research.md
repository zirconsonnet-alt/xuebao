# Research: Storage Growth Guard

## Decision 1: Treat protected and external growth sources as review/report targets by default

**Decision**: `.venv`, persistent databases, chat recorder records, host/service logs, and Docker artifacts are reported with size/risk/action, not deleted automatically.

**Rationale**: These categories can contain dependencies, audit/history records, or resources owned by the host/container runtime. Automatic deletion can break the bot or lose data.

**Alternatives Considered**:

- Auto-delete by age: rejected because database/log/container ownership differs and may cause data loss.
- Ignore external categories: rejected because the user explicitly called out these sources as remaining disk-fill risks.

## Decision 2: Add one storage guard module instead of expanding per-feature cleanup logic

**Decision**: Add a planned `src/support/storage_guard.py` module responsible for category definitions, size scanning, classification, warnings, and low-disk decisions.

**Rationale**: Existing `cache_cleanup.py` is intentionally narrow and already handles four safe cache categories. The new feature needs review/report/protect semantics, not just deletion.

**Alternatives Considered**:

- Put all logic into `cache_cleanup.py`: rejected because protected/manual categories would blur cleanup with reporting.
- Put logic in each service: rejected because `.venv`, databases, Docker, logs, and unknown plugin caches cross service boundaries.

## Decision 3: Classify categories before any cleanup

**Decision**: Each category must have one of four safety classes before action: safe automatic cleanup, explicit-policy cleanup, manual action, or protected.

**Rationale**: This matches the spec and prevents accidental deletion of categories that merely look like cache directories.

**Alternatives Considered**:

- Path-name heuristic only: rejected because names like `cache/nonebot_plugin_chatrecorder` can still contain records that should be preserved.

## Decision 4: Gate optional large writes before writing

**Decision**: Add a reusable low-disk check for optional large file-producing operations. If free space is below the configured safety threshold, the operation returns a clear refusal/degraded result before creating large files.

**Rationale**: Cleanup after write cannot protect a disk that is already low or an operation that would consume the remaining safe space.

**Alternatives Considered**:

- Only run scheduled cleanup more often: rejected because a single write can still fill the disk between cleanup cycles.
- Check disk only at startup: rejected because the bot may run for weeks.

## Decision 5: Use configurable thresholds with a conservative default

**Decision**: Plan for configuration of minimum free bytes and minimum free ratio, with a documented default used when no config is provided.

**Rationale**: Different servers have different disk sizes. A configurable threshold satisfies the requirement without hardcoding one operator policy.

**Alternatives Considered**:

- Fixed threshold only: rejected because it does not fit both small VPS disks and larger hosts.
- No default: rejected because low-disk protection would be inactive until configured.

## Decision 6: Surface unknown plugin caches as unclassified risks

**Decision**: Scan likely plugin cache roots and report directories not covered by known policies as unclassified risks.

**Rationale**: The user specifically wants growth outside the current four categories covered. Unknown plugin caches should be visible before they become disk-fill surprises.

**Alternatives Considered**:

- Auto-clean all unknown cache directories: rejected because cache ownership and recoverability are unknown.
