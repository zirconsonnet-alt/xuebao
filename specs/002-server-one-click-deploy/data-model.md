# Data Model: Server One-Click Deploy

## Deployment Configuration

Represents operator-provided values needed to run the bot on a Linux server.

**Fields**:

- `environment_name`: deployment environment label, defaulting to production for server use.
- `bot_runtime_env`: values consumed by the bot from `.env`.
- `required_secret_values`: secret or token values that must be present outside tracked files.
- `deploy_branch`: the only branch allowed to trigger automated deployment.
- `server_target`: SSH target supplied through secret configuration, not tracked in repository files.
- `data_mount_path`: host path mounted as bot persistent data.
- `cache_mount_path`: optional host path mounted as cache.
- `backup_path`: host path used for deployment backups.

**Validation Rules**:

- Required values must exist before bot startup.
- Placeholder values from examples are invalid for real deployment.
- Secret values must not be present in tracked templates.
- Automated deployment must only target the configured deployment branch.

## Persistent Data Set

Represents runtime data that must survive restarts and redeploys.

**Fields**:

- `data_root`: persistent `data/` mount.
- `critical_paths`: data paths called out for backup, including group-management and internal database paths.
- `optional_cache_root`: cache mount if enabled.
- `owner`: operator-managed host storage.
- `backup_required`: whether deploy/update should preserve data before risky steps.

**Relationships**:

- A deployment run may create a backup artifact from one persistent data set.
- Docker Compose service mounts the persistent data set into the bot runtime.

## Deployment Run

Represents one manual or automated deployment attempt.

**Fields**:

- `trigger`: manual server command or push-to-deploy.
- `revision`: source revision being deployed.
- `started_at`: run start timestamp.
- `result`: success, failed-preflight, failed-build, failed-start, or skipped.
- `log_location`: where the operator can inspect the run result.
- `backup_artifact`: backup produced before update, if any.

**State Transitions**:

```text
requested -> preflight_passed -> backup_completed -> service_updated -> verified -> success
requested -> failed-preflight
preflight_passed -> failed-build
backup_completed -> failed-start
```

Failed states must preserve or restore the previous working service whenever safe completion is not possible.

## Backup Artifact

Represents a preserved copy of critical runtime data.

**Fields**:

- `created_at`: backup creation timestamp.
- `source_paths`: persistent paths included.
- `destination_path`: operator-visible backup location.
- `trigger`: manual backup, manual deploy, or automated deploy.
- `status`: completed or failed.

**Validation Rules**:

- Backup must not overwrite another backup with the same timestamp.
- Backup failure must block risky update steps when backup is required.
- Backup location must be outside disposable container layers.
