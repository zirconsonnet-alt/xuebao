# Feature Specification: Storage Growth Guard

**Feature Branch**: `001-storage-growth-guard`  
**Created**: 2026-04-29  
**Status**: Draft  
**Input**: User description: "现在压一下：不在这 4 类里的目录继续增长，比如 .venv、系统日志、Docker、cache/nonebot_plugin_chatrecorder、数据库、其他插件缓存。"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Identify Remaining Disk Growth Sources (Priority: P1)

As the bot operator, I need the system to identify storage growth outside the four already bounded cache categories, so I can see what can still fill the server disk.

**Why this priority**: The current cleanup covers the main runtime media caches, but the server can still run out of space if other storage categories grow silently.

**Independent Test**: Can be tested by checking the storage report after startup or scheduled review and verifying that all requested remaining categories are listed with size and risk status.

**Acceptance Scenarios**:

1. **Given** the bot is running on a limited-disk server, **When** storage review runs, **Then** dependency/runtime storage, host or service logs, container artifacts, message recording cache, persistent database storage, and other plugin caches are each classified.
2. **Given** a category is not covered by an automatic cleanup policy, **When** it appears in the storage review, **Then** the operator sees whether it is safe to clean automatically, requires manual action, or must be preserved.

---

### User Story 2 - Bound Safe-To-Clean Growth (Priority: P2)

As the bot operator, I need safe-to-clean non-core caches to have clear retention or size limits, so plugin caches do not grow without an upper bound.

**Why this priority**: Plugin caches can grow after the main media directories are controlled, and they need bounded behavior where deletion is safe.

**Independent Test**: Can be tested by creating old or oversized plugin cache files and verifying that only safe-to-clean items are removed or capped while protected data remains.

**Acceptance Scenarios**:

1. **Given** a safe-to-clean plugin cache exceeds its configured retention or size limit, **When** cleanup runs, **Then** old or excess files are removed until the category is within policy.
2. **Given** a cache contains records that must be preserved for normal operation or audit, **When** cleanup runs, **Then** protected records are not deleted by the automatic policy.

---

### User Story 3 - Prevent New Large Writes When Disk Is Low (Priority: P3)

As the bot operator, I need large optional file-producing operations to stop before exhausting disk space, so one new download, render, recording cache, or generated file does not crash the server.

**Why this priority**: Cleanup after writing is not enough when the disk is already low or a single new file is too large.

**Independent Test**: Can be tested by lowering available free space below the configured safety threshold and verifying that optional large writes are refused or degraded with a clear reason.

**Acceptance Scenarios**:

1. **Given** free disk space is below the configured safety threshold, **When** a large optional file-producing operation is requested, **Then** the operation is refused or downgraded before creating a large file.
2. **Given** free disk space is above the configured safety threshold, **When** a normal file-producing operation is requested, **Then** the operation proceeds and remains subject to cleanup policy afterward.

### Edge Cases

- Disk space is already below the safety threshold at startup.
- A single incoming file is larger than remaining safe free space.
- A storage category is outside the bot process, such as host logs or container artifacts, and cannot be safely removed by the bot.
- Database storage grows due to retained operational records and cannot be truncated without data loss.
- A plugin creates a new cache directory that is not yet classified.
- A cleanup or review action fails due to permissions, locked files, or files changing while being scanned.
- Multiple groups or plugins each stay within their own limits but collectively push total storage near the safety threshold.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST maintain a storage review covering growth sources outside the four already bounded cache categories.
- **FR-002**: The storage review MUST include, at minimum, dependency/runtime storage, host or service logs, container artifacts, message recording cache, persistent database storage, and other plugin caches.
- **FR-003**: Each reviewed storage category MUST be classified as one of: safe for automatic cleanup, safe only with explicit policy, manual-action required, or protected from automatic cleanup.
- **FR-004**: Safe-to-clean categories MUST have a retention limit, size limit, or both, unless explicitly marked manual-action required.
- **FR-005**: The system MUST NOT automatically delete protected storage categories such as dependency/runtime files, persistent database records, host-managed logs, or container-managed artifacts without an explicit policy.
- **FR-006**: The system MUST report current size, growth risk, and recommended operator action for categories that are not automatically cleaned.
- **FR-007**: The system MUST detect low free disk space before starting optional large file-producing operations.
- **FR-008**: When free disk space is below the configured safety threshold, the system MUST refuse or degrade optional large file-producing operations before writing large new files.
- **FR-009**: Cleanup and low-disk protection outcomes MUST be visible to the operator through concise status or warning records.
- **FR-010**: Unknown new storage categories created by plugins MUST be surfaced as unclassified growth risks until assigned a cleanup or preservation policy.

### Key Entities

- **Storage Category**: A named source of disk usage, with ownership, cleanup safety, size, growth risk, retention policy, and recommended action.
- **Storage Review**: A point-in-time summary of storage categories, free disk space, warnings, and unclassified growth risks.
- **Storage Action**: A cleanup, refusal, warning, or manual-action recommendation produced by the storage review or low-disk guard.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of the requested remaining growth categories appear in the storage review with a cleanup-safety classification.
- **SC-002**: 100% of safe-to-clean non-core cache categories have an explicit retention limit, size limit, or both.
- **SC-003**: When free disk space is below the configured safety threshold, 100% of optional large file-producing operations are refused or degraded before creating large new files.
- **SC-004**: Manual-action or protected categories produce an actionable operator warning within one scheduled review cycle.
- **SC-005**: Unknown plugin-created storage categories are reported as unclassified risks within one scheduled review cycle after they appear.
- **SC-006**: During seven days of normal operation, storage categories controlled by automatic policy remain within their configured limits.

## Assumptions

- The four already bounded runtime cache categories remain covered by the existing cleanup policy and are not redefined by this feature.
- Some listed growth sources are not safe for automatic deletion and should be reported rather than cleaned by default.
- The disk safety threshold is configurable; the specification requires behavior relative to that threshold rather than fixing one universal number.
- Operator-facing warnings are sufficient for storage categories that the bot cannot safely manage directly.
