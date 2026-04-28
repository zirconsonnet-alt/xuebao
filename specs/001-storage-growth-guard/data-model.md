# Data Model: Storage Growth Guard

## StorageSafetyClass

Enum-like value describing what automatic action is allowed.

- `auto_cleanup`: Safe for automatic cleanup under retention/size policy.
- `explicit_policy`: May be cleaned only after a category-specific policy exists.
- `manual_action`: Bot should report and recommend operator action.
- `protected`: Bot must not delete automatically.
- `unclassified`: Newly discovered category awaiting policy.

## StorageCategoryDefinition

Defines a storage source.

Fields:

- `key`: stable identifier, e.g. `venv`, `chatrecorder_cache`, `database_files`.
- `label`: operator-facing category name.
- `roots`: filesystem roots or discovery patterns.
- `owner`: `bot`, `plugin`, `python_runtime`, `host`, `docker`, or `unknown`.
- `safety_class`: one StorageSafetyClass value.
- `retention_seconds`: optional age limit for `auto_cleanup`.
- `max_total_bytes`: optional size cap for `auto_cleanup`.
- `patterns`: optional file patterns to include.
- `recommended_action`: concise operator action for non-cleaned categories.

Validation:

- `auto_cleanup` must define `retention_seconds`, `max_total_bytes`, or both.
- `protected` and `manual_action` must not define destructive cleanup behavior.
- Roots must be resolved before scanning or deletion.

## StorageCategoryReport

Point-in-time category result.

Fields:

- `key`
- `label`
- `roots`
- `safety_class`
- `exists`
- `scanned_files`
- `total_bytes`
- `risk_level`: `ok`, `watch`, `high`, `unknown`
- `recommended_action`
- `errors`
- `cleanup_result`: optional cleanup summary when cleanup is allowed and executed.

Validation:

- Missing roots are reported with `exists=false`, not as failures.
- Permission/locked-file errors increment `errors` and keep partial scan results.

## StorageReview

Full report from one review cycle.

Fields:

- `created_at`
- `reason`: `startup`, `scheduled`, `manual`, or operation-triggered reason.
- `free_bytes`
- `total_bytes`
- `free_ratio`
- `threshold_bytes`
- `threshold_ratio`
- `low_disk`
- `categories`: list of StorageCategoryReport.
- `warnings`: concise warning strings for operator logs.

Validation:

- Requested remaining growth categories must appear in `categories`.
- Unknown plugin cache roots must be represented as `unclassified`.

## DiskGuardDecision

Decision made before an optional large write.

Fields:

- `operation`: stable operation name.
- `target_path`
- `expected_bytes`: optional estimate.
- `free_bytes`
- `safe_free_bytes`
- `allowed`
- `reason`
- `degraded`: whether the operation can continue in a smaller/no-file mode.

Validation:

- If `allowed=false`, caller must not create the large output file.
- Missing `expected_bytes` still requires checking global free-space threshold.

## StorageAction

Represents a cleanup, refusal, warning, or manual-action recommendation.

Fields:

- `action_type`: `cleanup`, `warning`, `refusal`, `manual_action`.
- `category_key`
- `operation`
- `message`
- `deleted_files`
- `deleted_bytes`
- `errors`
