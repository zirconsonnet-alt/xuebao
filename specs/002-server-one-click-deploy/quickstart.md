# Quickstart: Server One-Click Deploy

## Scope

This quickstart describes the operator verification flow for the Linux Docker Compose deployment feature.

## Prerequisites

- Linux server access.
- Docker Engine and Docker Compose plugin installed.
- Repository checked out on the server.
- Required production values prepared outside tracked files.
- GitHub repository secrets prepared for automated deployment, if push-to-deploy is enabled.

## Manual Deployment Verification

1. Create `.env` from `.env.example`.
2. Fill required bot and deployment values with non-placeholder production values.
3. Run the environment validation command:

   ```bash
   scripts/validate-deploy-env.sh
   ```

4. Run the one-command deploy entry:

   ```bash
   scripts/deploy.sh
   ```

5. Verify the service is running:

   ```bash
   docker compose ps
   ```

6. Inspect logs:

   ```bash
   docker compose logs --tail=100 bot
   ```

## Persistence Verification

1. Deploy once and allow the bot to create runtime data under the mounted data path.
2. Run the deploy command again.
3. Confirm the same runtime data remains available after redeploy.
4. Run the backup helper:

   ```bash
   scripts/backup-data.sh
   ```

5. Confirm a new timestamped backup appears in the configured backup location.

## Restart Verification

1. Stop the running bot container unexpectedly.
2. Confirm the restart policy restores it.
3. Reboot a test server where safe.
4. Confirm the bot service is running again within the target window.

## Push-To-Deploy Verification

1. Configure repository secrets for SSH deployment.
2. Push a harmless change to the allowed deployment branch.
3. Confirm the workflow runs.
4. Confirm the server updates to the pushed revision.
5. Confirm workflow logs report success.
6. Push or simulate a deliberately broken update in a safe test branch/environment.
7. Confirm failure is visible and the previous working deployment is not silently replaced.

## Expected Operator Outcomes

- First deployment can be completed from a prepared server without manual dependency setup beyond Docker prerequisites.
- Repeated deployment uses the same command.
- Missing required env values fail before startup.
- Persistent data survives redeploys.
- Logs and backups have documented inspection paths.
