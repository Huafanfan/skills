# Spring Boot 2 To 3 Migration

Scan Spring Boot 2.x repositories, identify migration blockers, and drive phased upgrades to Spring Boot 3.x.

## What It Covers

- Java 8 or 11 to Java 17+ baseline upgrades required by Spring Boot 3
- Spring Boot 2.x to 3.x migrations, including Jakarta and Spring Security changes
- Multi-module repositories, starter libraries, and auto-configuration migrations
- Fixed scan output so Codex starts from detected Spring Boot facts instead of guesses

## Bundled Resources

- `scripts/scan_repo.py`: scans the repository and writes both a migration report and an execution-oriented TODO pack in Markdown and JSON
- `scripts/verify_repo.py`: runs compile, test, startup, or smoke verification, captures logs, and writes a repair-oriented failure summary
- `references/java-upgrade-paths.md`: staged Java upgrade rules
- `references/spring-boot-2-to-3.md`: Spring Boot migration hotspots and remediation order
- `references/spring-cloud-config-and-bootstrap.md`: Spring Cloud Config and bootstrap/config-data migration rules
- `references/verification.md`: verification contract and exit criteria
- `assets/migration-plan-template.md`: reusable output template

## Typical Usage

1. Run the scanner against the target repository.
2. Read `scan.md` for the high-level picture and `todo.md` for the file-by-file execution list.
3. Propose a phased plan.
4. Execute a small batch of changes.
5. Run `verify_repo.py` and fix only the first failed stage before continuing.

`verify_repo.py` auto-detects Maven or Gradle and provides default `compile` and `test` commands.
Pass `--startup-command` or `--smoke-command` when the repository has a known runnable entrypoint or smoke probe.

## Agent Prompt Templates

Use the skill name explicitly so the agent triggers the right workflow.

### Basic Scan

```text
Use $spring-boot-2-to-3-migration on the current repository.
Scan it first, generate scan.md and todo.md, then summarize the main migration blockers.
```

### Full Migration

```text
Use $spring-boot-2-to-3-migration to upgrade this repository from Spring Boot 2.x to 3.x.
Scan first, generate the migration TODO, then start applying changes phase by phase.
```

### Migration With Repair Loop

```text
Use $spring-boot-2-to-3-migration to migrate this repository to Spring Boot 3.x.
After each batch of changes, run verification.
If compile, test, or startup fails, read failure-summary.md and continue fixing the first failed stage until it passes or you hit a real blocker.
```

### Conservative Review-First Mode

```text
Use $spring-boot-2-to-3-migration in review mode.
Do not change code yet.
Scan the repository, generate scan.md and todo.md, and give me a phased migration plan with the highest-risk files first.
```

### Startup-Aware Mode

```text
Use $spring-boot-2-to-3-migration to migrate this repository to Spring Boot 3.x.
After code changes, run verification and use this startup command:
./mvnw -q -DskipTests spring-boot:run
Keep fixing issues until compile, test, and startup are green or clearly blocked.
```

## Example

```bash
python3 /path/to/spring-boot-2-to-3-migration/scripts/scan_repo.py /path/to/repo \
  --format both \
  --output-dir /path/to/repo/.codex/spring-boot-2-to-3-migration

python3 /path/to/spring-boot-2-to-3-migration/scripts/verify_repo.py /path/to/repo \
  --stage all \
  --output-dir /path/to/repo/.codex/spring-boot-2-to-3-migration

python3 /path/to/spring-boot-2-to-3-migration/scripts/verify_repo.py /path/to/repo \
  --stage startup \
  --startup-command "./mvnw -q -DskipTests spring-boot:run"
```
