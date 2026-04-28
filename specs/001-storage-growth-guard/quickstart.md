# Quickstart: Storage Growth Guard

## Plan Scope

This slice adds storage growth review, explicit safe-cache cleanup, and low-disk refusal for optional large file writes.

## Expected Implementation Checks

Run focused tests:

```powershell
poetry run pytest tests/test_storage_growth_guard.py -q
```

Run regression tests for existing file-producing paths:

```powershell
poetry run pytest tests/test_ai_group_context.py tests/test_speech_generator_runtime.py tests/test_bison_music_card_runtime.py tests/test_composition_music_card_runtime.py -q
```

Run compile smoke checks:

```powershell
poetry run python -m compileall src/support/cache_cleanup.py src/support/storage_guard.py src/app.py
```

## Manual Verification

1. Set `STORAGE_GUARD_SAFE_PLUGIN_CACHE_ROOTS` to a safe test plugin cache root.
2. Create old or oversized files under that safe test plugin cache root.
3. Create protected test files representing `.venv`, database files, and `cache/nonebot_plugin_chatrecorder`.
4. Run the storage review or wait for the scheduled storage guard.
5. Confirm safe cache files are cleaned only when policy allows it.
6. Confirm protected/manual/unclassified categories are reported and not deleted.
7. Raise `STORAGE_GUARD_MIN_FREE_BYTES` or `STORAGE_GUARD_MIN_FREE_RATIO` above current free space for a test run.
8. Trigger an optional large file-producing path.
9. Confirm it refuses or degrades before creating the output file.

Optional category roots:

- `STORAGE_GUARD_HOST_LOG_ROOTS`: semicolon-separated host/service log roots to report.
- `STORAGE_GUARD_DOCKER_ROOTS`: semicolon-separated Docker-related roots to report.
- `STORAGE_GUARD_SAFE_PLUGIN_CACHE_ROOTS`: semicolon-separated plugin cache roots that may use the built-in 7-day / 300 MB cleanup policy.

## Operator Outcome

The bot should keep long-running cleanup active, surface categories it cannot safely clean, and stop optional large writes when the disk is already unsafe.
