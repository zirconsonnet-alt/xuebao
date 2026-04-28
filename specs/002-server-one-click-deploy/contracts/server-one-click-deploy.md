# Contract: Server One-Click Deploy

## Operator Command Contract

### `scripts/deploy.sh`

**Purpose**: One-command Linux server deploy/update entry.

**Expected Inputs**:

- Run from repository root on the target Linux server.
- `.env` exists and contains required non-placeholder values.
- Docker Engine and Compose plugin are available.
- Host data and backup directories are writable by the deploy operator.

**Expected Behavior**:

- Validate server prerequisites.
- Validate required environment values.
- Create required host directories if missing.
- Back up critical data before risky update steps when backup is enabled or required.
- Build or refresh the bot service image.
- Start or update the Compose service.
- Verify the service is running.
- Print a clear success or failure result.

**Failure Contract**:

- Missing prerequisites or env values fail before service replacement.
- Backup failure blocks risky update steps.
- Failed update must not silently replace a previously running service.

## Environment Template Contract

### `.env.example`

**Purpose**: Non-secret template for required server configuration.

**Expected Contents**:

- Required bot runtime variables from existing docs, including bot API authentication values.
- Deployment-related paths and branch values.
- Placeholder values that are visibly invalid for production.

**Rules**:

- Must not contain real secrets, private keys, hostnames, tokens, cookies, or production identifiers.
- Every required field must be documented either inline or in `docs/deployment-guide.md`.

## Compose Contract

### `docker-compose.yml`

**Purpose**: Define the Linux server runtime.

**Expected Behavior**:

- Runs the bot through the existing `bot.py` entry.
- Loads configuration from `.env`.
- Mounts persistent `data/` host storage.
- Optionally mounts cache storage if retained by implementation.
- Uses an automatic restart policy.
- Exposes only required ports, if any are needed by the bot runtime.

**Rules**:

- Must not bake secrets into image or compose file.
- Must not store persistent bot data only inside the disposable container layer.

## CI/CD Contract

### `.github/workflows/deploy.yml`

**Purpose**: Deploy accepted pushes from an explicitly allowed branch.

**Expected Inputs**:

- Repository secrets for SSH host, user, key, target path, and optional port.
- Allowed branch configured in the workflow.

**Expected Behavior**:

- Ignore non-deployment branches.
- Run repository validation steps before remote deployment where practical.
- Connect to the server using secrets.
- Invoke the same server deployment entry used by manual deployment.
- Report success or failure in workflow logs.

**Security Rules**:

- No secrets or real server addresses in tracked workflow files.
- SSH credentials must come only from repository secrets.
- Workflow must not deploy arbitrary branches by default.
