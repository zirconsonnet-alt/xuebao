# Research: Server One-Click Deploy

## Decision: Docker Compose is the primary server runtime

**Rationale**: The user confirmed Docker Compose. It gives a single operator command, restart policy, env-file handling, persistent volume mounts, and repeatable server updates without changing the bot runtime architecture.

**Alternatives considered**:

- `systemd + Poetry`: closer to current local scripts, but exposes the server to Python/Poetry dependency drift and is less portable.
- Plain shell script without containers: simple initially, but weaker isolation and harder repeat deploys.
- Kubernetes or hosted PaaS: too large for the confirmed single-server scope.

## Decision: Keep first-time server prerequisites explicit

**Rationale**: Installing Docker itself is host-sensitive and often needs root/package-manager choices. The one-click project deployment should assume a Linux server with Docker Engine and Compose plugin available, then validate that precondition clearly.

**Alternatives considered**:

- Auto-install Docker in project script: rejected because it changes host package state and can be unsafe across distributions.
- Document only manual Docker checks: rejected because deploy should fail early with clear guidance.

## Decision: Use host bind mounts for persistent data

**Rationale**: The existing bot stores runtime state under `data/`, with docs already calling out SQLite and group-management data. Bind mounts make data location obvious to the operator and easy to back up.

**Alternatives considered**:

- Anonymous Docker volumes: harder for operators to inspect and back up.
- Baking data into the image: unsafe because redeploys could erase state.
- Mount only selected database files: too brittle because plugin storage can expand.

## Decision: Validate env before starting the service

**Rationale**: The spec requires refusing startup when required values are missing or placeholders. A small validation script can check `.env` against `.env.example` conventions before Compose starts.

**Alternatives considered**:

- Let the bot fail at runtime: slower feedback and can produce partial startup side effects.
- Hardcode required values in Compose: risks exposing secrets or coupling deployment to one operator.

## Decision: Implement push-to-deploy via GitHub Actions over SSH

**Rationale**: The user requested push-based CI/CD. GitHub Actions can run tests/checks, then invoke the same server deploy script over SSH using repository secrets. This keeps manual and automated deployment behavior aligned.

**Alternatives considered**:

- Self-hosted runner on the server: powerful but increases long-running server attack surface.
- Pull-based cron on the server: simpler credentials but less visible from push results.
- Webhook receiver on the server: requires adding and securing another service.

## Decision: Failed automated deploy must preserve previous working service

**Rationale**: The spec requires failed updates not to silently replace a working deployment. The deploy flow should validate configuration, optionally back up data, build/pull, and only replace/restart after preflight steps pass.

**Alternatives considered**:

- Stop first, then update: rejected because failure can create avoidable downtime.
- Always deploy latest regardless of checks: rejected because it violates failure-safety requirements.

## Decision: Logs are accessed through container logs and documented server commands

**Rationale**: Docker Compose already provides a standard log inspection path. It avoids introducing a separate logging stack for one bot service.

**Alternatives considered**:

- Dedicated log files inside the container: harder to persist and rotate correctly.
- External logging system: too large for this feature.
