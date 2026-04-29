# Contract: Storage Growth Guard

This feature exposes internal Python contracts and operator-visible log/status output. It does not introduce a new HTTP API.

## Category Review Contract

```python
def review_storage_growth(reason: str = "manual") -> StorageReview:
    ...
```

Expected behavior:

- Returns one `StorageReview` containing all requested categories.
- Never deletes protected/manual/unclassified categories.
- Includes size, risk, and recommended action for each category.
- Records scan errors without failing the whole review.

Required category keys:

- `venv`
- `host_logs`
- `docker_artifacts`
- `chatrecorder_cache`
- `database_files`
- `other_plugin_caches`

## Cleanup Contract

```python
def run_storage_guard(reason: str = "scheduled") -> StorageReview:
    ...
```

Expected behavior:

- Runs existing four-category cleanup through current cleanup code.
- Reviews remaining growth sources.
- Cleans only categories classified as `auto_cleanup`.
- Emits concise warnings for low disk, manual-action, protected, or unclassified growth.

## Low Disk Guard Contract

```python
def ensure_optional_write_allowed(
    operation: str,
    *,
    target_path: Path | str | None = None,
    expected_bytes: int | None = None,
) -> DiskGuardDecision:
    ...
```

Expected behavior:

- Checks free space before optional large writes.
- Returns `allowed=False` when free disk is below configured threshold.
- Returns `allowed=False` when `expected_bytes` would consume the configured safe reserve.
- Does not create, delete, or mutate files.

Caller rule:

- If `allowed=False`, the caller must return a refusal/degraded result before writing.

## Operator Output Contract

Warnings must be concise and actionable.

Examples:

```text
存储警告（scheduled）：可用空间低于阈值，已限制可选大文件生成。
存储警告（scheduled）：cache/nonebot_plugin_chatrecorder 为受保护类别，仅报告不自动清理。
存储警告（scheduled）：发现未分类插件缓存 cache/example_plugin，请补充清理或保留策略。
```

## Safety Contract

Automatic deletion is forbidden for:

- `.venv`
- database files and database sidecar files
- `cache/nonebot_plugin_chatrecorder`
- host-managed logs
- Docker/container artifacts
- unknown plugin caches

Deletion requires:

- resolved root containment check
- explicit category policy
- file-level matching against allowed patterns when patterns are configured
- deletion result accounting
