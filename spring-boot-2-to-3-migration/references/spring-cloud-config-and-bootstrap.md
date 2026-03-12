# Spring Cloud Config And Bootstrap

Use this file when the scan detects Spring Cloud dependencies, `spring-cloud-starter-config`, `spring-cloud-config-server`, `bootstrap.yml`, `bootstrap.properties`, or `spring.config.import=configserver:`.

## Why This Matters

Spring Boot 2.x to 3.x migrations often fail in configuration loading before business code even starts. Spring Cloud version alignment and config-loading behavior must be reviewed with the same care as Jakarta or Security changes.

## Checks

- Identify the Spring Cloud release train in use.
- Confirm it is compatible with the target Spring Boot version.
- Inspect whether the repository still relies on `bootstrap.*` files or `spring-cloud-starter-bootstrap`.
- Inspect whether Config Data imports are already used via `spring.config.import=configserver:`.
- Verify config clients, config servers, discovery, and encryption behavior after upgrade.

## Migration Guidance

### Release Train Alignment

- Do not upgrade Spring Boot without also aligning Spring Cloud.
- Treat `spring-cloud.version`, `version.spring.cloud`, and direct `spring-cloud-*` dependency versions as hard compatibility constraints.

### Bootstrap And Config Data

- `bootstrap.*` usually indicates older config-loading behavior.
- Prefer the current Config Data approach where supported.
- If both legacy bootstrap and newer config imports appear in the same repository, treat that as a manual-review hotspot.
- Do not invent new `application-dev.yml`, `application-perf.yml`, `application-prod.yml`, or other profile overlays unless those files already exist or the user explicitly asks for them.
- If the intended config-loading order is unclear, stop and ask for the expected runtime model instead of synthesizing new config files.

### Verification

- Start the config server first if present.
- Start the client on the target JDK and confirm external properties are loaded.
- Check one encrypted, profile-specific, or remote property path if the project uses one.
- Verify config loading order and precedence if the app relies on profile overlays.
