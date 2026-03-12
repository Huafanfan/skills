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
- `scripts/search_repo.py`: portable repository search helper used when `rg` is unavailable or when you want the same workflow across macOS and Linux
- `scripts/probe_versions.py`: collects visible Maven artifact versions from configured repositories and probes them until a downloadable candidate is found
- `references/java-upgrade-paths.md`: staged Java upgrade rules
- `references/spring-boot-2-to-3.md`: Spring Boot migration hotspots and remediation order
- `references/spring-cloud-config-and-bootstrap.md`: Spring Cloud Config and bootstrap/config-data migration rules
- `references/verification.md`: verification contract and exit criteria
- `assets/migration-plan-template.md`: reusable output template
- `assets/risk-register-template.md`: reusable record for out-of-skill fixes and unresolved migration risk

## Typical Usage

Before writing scan or verification outputs into a target repository, add `.migration-work/` to that repository's `.gitignore`.

The scanner classifies applicability as:

- `directly_supported`
- `supported_via_local_parent`
- `blocked_by_external_parent`

If the scan reports `blocked_by_external_parent`, do not continue migration edits in that checkout. Ask the user for the external parent repository, effective POM, or a checkout that contains the version-managing build files.

1. Run the scanner against the target repository.
2. Read `scan.md` for the high-level picture and `todo.md` for the file-by-file execution list.
3. Load only the reference files listed under `Recommended References` in `scan.md`.
4. Propose a phased plan.
5. Execute a small batch of changes.
6. Run `verify_repo.py` and fix only the first failed stage before continuing.
7. If verification is blocked by permissions, dependency access, or local build environment issues, keep applying static migration changes and hand final verification back to the user.
8. If the failure is outside the skill's named rules, keep debugging anyway, but record out-of-skill fix attempts and residual risk in `risk-register.md`.

`verify_repo.py` auto-detects Maven or Gradle and provides default `compile` and `test` commands.
Pass `--startup-command` or `--smoke-command` when the repository has a known runnable entrypoint or smoke probe.
The skill does not require `rg`; its generated search commands now use `search_repo.py`, which only needs `python3`.
When verification is environment-blocked, the verifier writes `verification-handoff.md` instead of treating that situation as a source-code migration failure.
Do not guess startup commands, smoke commands, or endpoints. If they are unknown, leave them unconfigured.
Keep each edit batch narrow: one blocker type at a time, or at most three files from the same blocker category.
For Maven dependency resolution failures, probe Spring Boot, Spring Cloud, and the failing Maven plugin artifact for visible and downloadable versions before declaring the migration blocked.
If a build or runtime problem falls outside the skill's explicit coverage, do not stop at "unknown error". Keep working the first root cause, use normal repository debugging, and leave a clear `risk-register.md` trail for anything that remains uncertain.
Do not invent new `application-dev.yml`, `application-perf.yml`, `application-prod.yml`, or similar environment files just to make Boot 3 start. If config structure is unclear, report the incompatibility and ask for the intended runtime layout instead.
Prefer editing existing Java configuration classes over generating new ones. If a new class is unavoidable, it must use Boot 3 and Security 6 APIs only.

The intermediate Spring Boot `2.7.x` step is intentional.
It is the last Boot 2 line, exposes the closest compatible deprecations and property changes, and makes the final jump to Boot 3 materially safer than jumping from older 2.x baselines.

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
If verification is blocked by permissions or dependency access, continue static migration work and leave a verification handoff instead of declaring success.
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
  --output-dir /path/to/repo/.migration-work/spring-boot-2-to-3

python3 /path/to/spring-boot-2-to-3-migration/scripts/verify_repo.py /path/to/repo \
  --stage all \
  --output-dir /path/to/repo/.migration-work/spring-boot-2-to-3

python3 /path/to/spring-boot-2-to-3-migration/scripts/verify_repo.py /path/to/repo \
  --stage startup \
  --startup-command "./mvnw -q -DskipTests spring-boot:run"
```
