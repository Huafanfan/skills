---
name: spring-boot-2-to-3-migration
description: Scan and migrate Spring Boot 2.x repositories to Spring Boot 3.x with repeatable workflows for Maven or Gradle projects. Use when Codex needs to upgrade Java 8 or 11 projects to the Java 17+ baseline, handle Jakarta namespace changes, migrate Spring Security 5-era DSLs, review Hibernate and auto-configuration compatibility, or assess a Spring Boot 2.x repo before making migration edits.
---

# Spring Boot 2 To 3 Migration

Use this skill to make Spring Boot 2.x to 3.x migration start from repository facts instead of guesswork.

## Workflow

### 1. Scan The Repository First

Never migrate blindly.

Before writing scan or verification outputs into the repository, ensure the target repository `.gitignore` contains:

```gitignore
.migration-work/
```

Do this early so migration artifacts are not committed by accident.

Run:

```bash
python3 <skill-dir>/scripts/scan_repo.py <repo> \
  --format both \
  --output-dir <repo>/.migration-work/spring-boot-2-to-3
```

Read `<repo>/.migration-work/spring-boot-2-to-3/scan.md` first for the high-level picture.
Read `<repo>/.migration-work/spring-boot-2-to-3/todo.md` next for the file-by-file execution list.
Use `scan.json` and `todo.json` only when you need structured fields.

The scan classifies repository support into three states:

- `directly_supported`: Spring Boot versioning is managed directly in the current repository build files.
- `supported_via_local_parent`: the current module inherits Spring Boot versioning through a parent POM that also exists inside the current repository.
- `blocked_by_external_parent`: Spring Boot usage exists, but the effective Boot version is inherited from a parent or BOM outside the current repository.

If the state is `blocked_by_external_parent`, stop migration work, explain the limitation, and ask the user for the external parent repository, effective POM, or a checkout that includes the version-managing build files.

The scanner detects:

- Maven and Gradle entrypoints
- Java and Spring Boot versions when available
- Jakarta migration candidates
- legacy Spring Security DSL usage
- custom starters and auto-configuration patterns
- JPA, JUnit 4, JAXB, internal JDK API usage

This skill does not require `rg`.
Use `scripts/search_repo.py` for portable text search across macOS and Linux.
If `rg` is installed, you can still use it manually for faster ad hoc searches.

### 2. Load Only The Needed References

- First load the files listed under `Recommended References` in `scan.md`.
- Always load `references/verification.md`.
- Load `references/java-upgrade-paths.md` when the repo needs a Java major-version upgrade.
- Load `references/spring-boot-2-to-3.md` when Spring Boot 2.x, Jakarta migration, old Spring Security DSL, or custom auto-configuration is detected.
- Load `references/spring-cloud-config-and-bootstrap.md` when Spring Cloud, `bootstrap.*`, or Config Server usage is detected.

Do not load every reference file by default.

### 3. Produce A Fixed Migration Plan

After scanning, use the generated outputs and respond with these sections in this order:

1. Detected state
2. High-severity blockers
3. Phase plan
4. File TODO summary
5. Commands you will run next
6. Verification status

Use `assets/migration-plan-template.md` when you need a starting structure.
If support status is `blocked_by_external_parent`, the plan must stop after explaining the limitation and required user input.

### 4. Execute In Phases

Default phases:

1. Baseline current build, tests, runtime entrypoint, and working tree state
2. Raise Java toolchain and build infrastructure
3. Align Spring and third-party dependency versions
4. Apply source and configuration changes
5. Compile, test, start the app, and smoke critical flows

If Spring Boot 2.x is detected, insert an intermediate step to move to the latest 2.7.x patch before the Boot 3 upgrade.
This is not busywork: 2.7.x is the last Spring Boot 2 line, surfaces the closest set of deprecations and config changes, and reduces the jump size before Jakarta, Security 6, and Boot 3 behavior changes land together.

### 5. Verification And Repair Loop

After each meaningful batch of edits, run verification instead of guessing.

A meaningful batch is intentionally small:

- one blocker type at a time
- or at most three files from the same blocker category
- do not mix dependency alignment, Jakarta edits, Spring Security rewrites, and config migration in one batch

Default verification loop:

1. Run compile verification.
2. If compile passes, run test verification.
3. If a startup command is known, run startup verification. If it is unknown, mark startup as not configured and do not guess.
4. If a smoke command is known, run smoke verification. If it is unknown, mark smoke as not configured and do not guess.
5. If a code or configuration stage fails, stop, read `failure-summary.md`, fix the first failed stage, and rerun that stage before moving forward.
6. If verification is blocked by environment, permissions, wrapper state, or dependency access, write the handoff, skip the remaining verification steps, and continue static migration work where possible.

Special rule for Maven dependency resolution failures:

- Do not immediately mark the repository blocked when the build tool can still reach Nexus or the repository manager.
- Run `scripts/probe_versions.py` to collect visible versions for Spring Boot or Spring Cloud anchor artifacts and probe them until a downloadable candidate is found.
- Update the version-managing build file to the first downloadable candidate and rerun the failed stage.
- Only treat the repository as blocked when repository access itself is broken, local cache state is unusable, or no relevant candidate can be probed at all.

State machine:

- `passed`: move to the next phase
- `failed`: stay in the current phase and fix only the first root-cause error
- `blocked`: continue static migration work, but final status must be a handoff, not success

Fallback rule for uncovered build and runtime failures:

- If the error is not explicitly covered by this skill, do not stop just because no rule matched.
- Continue with normal debugging using the repository context, logs, and failing tests.
- Prefer the smallest defensible fix for the first root-cause error.
- Create or update `.migration-work/spring-boot-2-to-3/risk-register.md` from `assets/risk-register-template.md`.
- Record every material out-of-skill fix attempt and unresolved risk in that file.
- If the issue remains unresolved, report the attempted fixes, the remaining risk, and why the user may need to take over.

Run:

```bash
python3 <skill-dir>/scripts/verify_repo.py <repo> \
  --stage all \
  --output-dir <repo>/.migration-work/spring-boot-2-to-3
```

The verifier writes:

- `verification.md` and `verification.json`
- `failure-summary.md` and `failure-summary.json` when a stage fails
- `verification-handoff.md` and `verification-handoff.json` when verification is blocked by environment or permissions
- `version-probe.md` and `version-probe.json` when Maven dependency resolution failures trigger artifact version probing
- `logs/*.log` for the raw command output

The agent must create and maintain `risk-register.md` when it goes beyond the explicit skill rules or leaves residual risk behind.

Do not dump raw Maven or Gradle logs back to the user when the verifier already extracted the root cause. Use the summary, fix the first failure, and rerun.
If the verifier produces a handoff instead of a failure summary, continue source-level migration work and report that final verification must be rerun by the user in a permitted environment.

### 6. Apply Migration Rules

- Treat `javax.*` carefully. Only Jakarta EE packages move to `jakarta.*`; JDK packages like `javax.crypto` and `javax.sql` stay as-is.
- Treat `WebSecurityConfigurerAdapter`, `authorizeRequests`, `antMatchers`, and `mvcMatchers` as security migration blockers.
- Treat `spring.factories`, starter modules, and custom auto-configuration as bean-loading risks that need manual review.
- Treat JPA usage as a Hibernate 6 review surface, not only an import-rename task.
- Prefer removing root causes over adding blanket JVM flags.
- Do not guess startup commands, smoke commands, HTTP endpoints, or deployment topology.
- Do not start the next phase while the current phase is still `failed`.

### 7. Verification Contract

Do not declare success until you have, or have explicitly failed to obtain:

- clean compile on the target JDK
- test execution result
- application startup result
- one representative runtime smoke check

If you cannot run one of these, say exactly what blocked it.
If the blocker is environmental rather than code-related, do not present it as a migration regression.

## Commands

```bash
# Standard scan
python3 <skill-dir>/scripts/scan_repo.py <repo> --format both --output-dir <repo>/.migration-work/spring-boot-2-to-3

# Quick stdout-only scan
python3 <skill-dir>/scripts/scan_repo.py <repo>

# Verification loop with captured logs and failure summary
python3 <skill-dir>/scripts/verify_repo.py <repo> --stage all --output-dir <repo>/.migration-work/spring-boot-2-to-3

# Startup verification when the repository has a known runnable entrypoint
python3 <skill-dir>/scripts/verify_repo.py <repo> --stage startup --startup-command "<repo-specific startup command>" --output-dir <repo>/.migration-work/spring-boot-2-to-3
```

## Resources

- `scripts/scan_repo.py`
- `scripts/search_repo.py`
- `scripts/verify_repo.py`
- `scripts/probe_versions.py`
- `references/java-upgrade-paths.md`
- `references/spring-boot-2-to-3.md`
- `references/verification.md`
- `references/spring-cloud-config-and-bootstrap.md`
- `assets/migration-plan-template.md`
- `assets/risk-register-template.md`
