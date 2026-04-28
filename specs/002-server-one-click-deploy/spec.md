# Feature Specification: Server One-Click Deploy

**Feature Branch**: `002-server-one-click-deploy`  
**Created**: 2026-04-29  
**Status**: Draft  
**Input**: User description: "基于 Docker Compose，为 Linux 服务器提供一键部署能力；覆盖环境文件初始化、数据挂载/备份、日志、自动重启，并支持 push 后自动部署到服务器。"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - First Server Deploy (Priority: P1)

As the bot operator, I need to run one clear deployment entry on a fresh Linux server so the bot can be installed, configured, and started without manually piecing together setup steps.

**Why this priority**: This is the minimum useful one-click deployment path and removes the current manual deployment gap.

**Independent Test**: Can be tested on a clean Linux server by preparing required secrets, running the documented one-click deploy entry, and verifying the bot service starts successfully with persistent data directories in place.

**Acceptance Scenarios**:

1. **Given** a Linux server with the required base runtime available, **When** the operator runs the one-click deploy entry, **Then** the deployment creates or verifies the required runtime directories, prepares configuration from an example, installs or updates the deployable service, and starts the bot.
2. **Given** required secrets or configuration values are missing, **When** the operator runs the one-click deploy entry, **Then** deployment stops before starting the bot and reports the missing items clearly.
3. **Given** deployment completes, **When** the server restarts or the bot process exits unexpectedly, **Then** the bot is restored automatically according to the deployment policy.

---

### User Story 2 - Persistent Data, Logs, and Backup Safety (Priority: P2)

As the bot operator, I need deployment to keep bot data and logs outside disposable runtime layers so updates do not erase state and backups can be managed predictably.

**Why this priority**: A deployment that starts but loses data is unsafe for a long-running bot.

**Independent Test**: Can be tested by deploying, creating sample runtime data, redeploying or restarting, and verifying data remains available while logs can be inspected.

**Acceptance Scenarios**:

1. **Given** the bot has existing runtime data, **When** the operator redeploys, **Then** persistent data remains available after the new service starts.
2. **Given** the bot produces operational logs, **When** the operator inspects the deployment, **Then** logs are accessible through the documented server workflow.
3. **Given** backup is enabled or requested by the operator, **When** deployment or update runs, **Then** critical persistent data is copied or preserved according to the documented backup policy before risky changes proceed.

---

### User Story 3 - Push-To-Deploy Update (Priority: P3)

As the bot operator, I need repository updates to deploy automatically after an accepted push so routine releases do not require manually logging into the server.

**Why this priority**: Automated updates complete the one-click deployment story after the first server setup, but the initial server deployment is still useful without it.

**Independent Test**: Can be tested by pushing a harmless change to the configured branch and verifying the server updates, restarts the bot, and reports success or failure.

**Acceptance Scenarios**:

1. **Given** automated deployment is configured for an allowed branch, **When** a new push is accepted, **Then** the server updates to that revision and restarts the bot without manual SSH commands.
2. **Given** automated deployment fails, **When** the failure occurs, **Then** the operator can see a clear failure record and the previous running service is not silently replaced by a broken one.
3. **Given** a push targets a non-deployment branch, **When** the repository receives it, **Then** the production server is not updated.

### Edge Cases

- The server lacks a required base dependency or has an unsupported operating system version.
- The repository is already deployed and the operator runs deployment again.
- Required configuration exists but is incomplete or points to missing files.
- Persistent data directories already contain production data.
- The new revision fails to start after update.
- The server has low disk space before deployment or backup.
- Automated deployment credentials are missing, expired, or scoped incorrectly.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST provide a single documented deployment entry for Linux server operators to install or update the bot deployment.
- **FR-002**: The deployment MUST use Docker Compose as the primary server runtime path.
- **FR-003**: The deployment MUST include a checked-in example environment file that lists required configuration values without exposing real secrets.
- **FR-004**: The deployment MUST refuse to start the bot when required configuration values are missing or visibly placeholder values.
- **FR-005**: The deployment MUST define persistent storage locations for bot runtime data so redeploys do not erase operational state.
- **FR-006**: The deployment MUST define a backup workflow for critical persistent data before updates that may affect runtime state.
- **FR-007**: The deployment MUST expose a clear log inspection workflow for operators.
- **FR-008**: The deployed bot MUST be configured to restart automatically after server reboot or unexpected process exit.
- **FR-009**: The deployment MUST support automated deployment after pushes to an explicitly allowed branch.
- **FR-010**: Automated deployment MUST require explicit deployment credentials and MUST NOT embed private keys, tokens, or real server addresses in tracked files.
- **FR-011**: Automated deployment MUST report deployment success or failure in a place the operator can inspect after the push.
- **FR-012**: Failed automated deployment MUST leave the previous working deployment running whenever the update cannot be safely completed.
- **FR-013**: The deployment documentation MUST explain first-time setup, repeat deployment, update, rollback or recovery, logs, backups, and required secrets.
- **FR-014**: The deployment MUST keep existing local Windows install and run scripts usable unless they directly conflict with the server deployment path.

### Key Entities *(include if feature involves data)*

- **Deployment Configuration**: Operator-provided values needed to start the bot safely, including secrets, service options, and deployment targets.
- **Persistent Data Set**: Runtime state that must survive deploys and restarts, including bot data and operator-selected backup targets.
- **Deployment Run**: A single manual or automated deployment attempt, with trigger, target revision, result, and inspectable logs.
- **Backup Artifact**: A preserved copy or snapshot of critical data created before risky updates or on operator request.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A prepared operator can complete first-time server deployment in under 15 minutes after base server access is available.
- **SC-002**: A repeat deployment can be completed with one operator command and no manual dependency or process setup steps.
- **SC-003**: 100% of documented required configuration fields are validated before the bot starts.
- **SC-004**: Persistent bot data remains available after at least three consecutive redeploys in verification.
- **SC-005**: After a simulated process crash or server reboot, the bot is automatically running again within 2 minutes.
- **SC-006**: A push to the allowed deployment branch updates the server and reports a visible result within 10 minutes for a normal repository-sized change.
- **SC-007**: A deliberately broken update does not silently replace the previous working service during verification.

## Assumptions

- The first supported server target is Linux only.
- The operator can install or provide the base container runtime before running project deployment.
- The first supported one-click deployment path is Docker Compose, not systemd or native Poetry.
- Automated deployment targets one explicitly configured branch.
- Real production secrets, private keys, hostnames, and tokens are supplied outside tracked repository files.
- Windows local scripts remain local-development conveniences and are not part of the Linux one-click deployment path.
