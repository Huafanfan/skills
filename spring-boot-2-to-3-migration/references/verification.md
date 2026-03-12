# Verification

Use this file after each migration phase and before declaring the repository migrated.

## Repair Loop

- Run compile first, then tests, then startup, then smoke checks.
- Stop at the first failed stage.
- Summarize the first root-cause error instead of pasting the whole build log.
- Apply the smallest fix that addresses that failed stage.
- Rerun the same stage before moving on.
- If the blocked stage is caused by permissions, dependency access, private registries, wrapper state, or local cache access, mark verification as blocked and continue static migration work instead of treating it as a code failure.
- If startup or smoke commands are unknown, mark them as not configured. Do not guess.
- Do not move to the next phase while the current phase is still failed.
- If Maven dependency resolution fails but repository access still exists, probe visible Spring Boot, Spring Cloud, and failing plugin artifact versions and retry with the first downloadable candidate before treating the repository as blocked.
- If the failure does not match one of the known categories, continue debugging the first root cause anyway instead of stopping at "unknown".
- Record every material out-of-skill fix attempt and any remaining uncertainty in `.migration-work/spring-boot-2-to-3/risk-register.md`.
- If the issue is still unresolved at handoff time, summarize the attempted fixes and residual risk for the user.
- Do not create speculative config files or profile overlays while debugging. If configuration intent is unclear, report it as a user decision instead of inventing an environment model.

Use `scripts/verify_repo.py` when possible so the repository gets a stable `verification.md`, `failure-summary.md`, `verification-handoff.md`, and raw logs under `logs/`.

## Required Outputs

- Current detected state
- High-severity blockers still open
- Commands run
- Result of compile, tests, and application startup
- Remaining manual follow-ups
- Out-of-skill fix attempts and residual risks when applicable

## Minimum Checks

### Build

- Maven: `./mvnw test` or `mvn test`
- Gradle: `./gradlew test`
- Prefer running compile and test via `verify_repo.py` so failures are normalized and logged.

### Startup

- Start the main application on the target JDK.
- Confirm Spring context loads without bean creation failures.
- Confirm no remaining startup failures from missing Jakarta classes or invalid auto-configuration.

### Runtime

- Hit one representative HTTP endpoint, one persistence path, and one secured path if present.
- Check logs for reflective access failures, missing classes, or property binding failures.

### Config

- Remove temporary migration helpers before finishing, such as the Spring properties migrator if it was only used for discovery.

## Exit Criteria

- Clean compile on target JDK
- Test suite passes or known failures are documented and accepted
- Application starts successfully
- No unresolved high-severity findings from the scanner

If verification is blocked by the environment, the migration can still be handed off, but it is not complete until the user reruns compile, test, and startup checks in an allowed environment.
If verification finishes with unresolved out-of-skill risk, the handoff must say exactly what was tried, what still looks risky, and what the user should validate next.

## Failure Categories To Triage First

- Dependency or plugin resolution failures
- Dependency versions rejected by a repository gateway or policy engine
- Maven plugin versions rejected by a repository gateway or policy engine
- Jakarta namespace or missing class failures
- Bean creation and auto-configuration failures
- Spring Security DSL or filter-chain failures
- Hibernate and JPA compatibility failures
- Config Data, bootstrap, or property-binding failures
- Plain test regressions after compile is already green
