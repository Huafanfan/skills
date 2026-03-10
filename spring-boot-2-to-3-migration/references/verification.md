# Verification

Use this file after each migration phase and before declaring the repository migrated.

## Repair Loop

- Run compile first, then tests, then startup, then smoke checks.
- Stop at the first failed stage.
- Summarize the first root-cause error instead of pasting the whole build log.
- Apply the smallest fix that addresses that failed stage.
- Rerun the same stage before moving on.

Use `scripts/verify_repo.py` when possible so the repository gets a stable `verification.md`, `failure-summary.md`, and raw logs under `logs/`.

## Required Outputs

- Current detected state
- High-severity blockers still open
- Commands run
- Result of compile, tests, and application startup
- Remaining manual follow-ups

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

## Failure Categories To Triage First

- Dependency or plugin resolution failures
- Jakarta namespace or missing class failures
- Bean creation and auto-configuration failures
- Spring Security DSL or filter-chain failures
- Hibernate and JPA compatibility failures
- Config Data, bootstrap, or property-binding failures
- Plain test regressions after compile is already green
