---
name: spring-boot-2-to-3-migration
description: Scan and migrate Spring Boot 2.x repositories to Spring Boot 3.x with repeatable workflows for Maven or Gradle projects. Use when Codex needs to upgrade Java 8 or 11 projects to the Java 17+ baseline, handle Jakarta namespace changes, migrate Spring Security 5-era DSLs, review Hibernate and auto-configuration compatibility, or assess a Spring Boot 2.x repo before making migration edits.
---

# Spring Boot 2 To 3 Migration

Use this skill to make Spring Boot 2.x to 3.x migration start from repository facts instead of guesswork.

## Workflow

### 1. Scan The Repository First

Never migrate blindly.

Run:

```bash
python3 <skill-dir>/scripts/scan_repo.py <repo> \
  --format both \
  --output-dir <repo>/.migration-work/spring-boot-2-to-3
```

Read `<repo>/.migration-work/spring-boot-2-to-3/scan.md` first for the high-level picture.
Read `<repo>/.migration-work/spring-boot-2-to-3/todo.md` next for the file-by-file execution list.
Use `scan.json` and `todo.json` only when you need structured fields.

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

### 4. Execute In Phases

Default phases:

1. Baseline current build, tests, runtime entrypoint, and create a branch
2. Raise Java toolchain and build infrastructure
3. Align Spring and third-party dependency versions
4. Apply source and configuration changes
5. Compile, test, start the app, and smoke critical flows

If Spring Boot 2.x is detected, insert an intermediate step to move to the latest 2.7.x patch before the Boot 3 upgrade.

### 5. Verification And Repair Loop

After each meaningful batch of edits, run verification instead of guessing.

Default verification loop:

1. Run compile verification.
2. If compile passes, run test verification.
3. If a startup command is known, run startup verification.
4. If a smoke command is known, run smoke verification.
5. If a code or configuration stage fails, stop, read `failure-summary.md`, fix the first failed stage, and rerun that stage before moving forward.
6. If verification is blocked by environment, permissions, wrapper state, or dependency access, write the handoff, skip the remaining verification steps, and continue static migration work where possible.

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
- `logs/*.log` for the raw command output

Do not dump raw Maven or Gradle logs back to the user when the verifier already extracted the root cause. Use the summary, fix the first failure, and rerun.
If the verifier produces a handoff instead of a failure summary, continue source-level migration work and report that final verification must be rerun by the user in a permitted environment.

### 6. Apply Migration Rules

- Treat `javax.*` carefully. Only Jakarta EE packages move to `jakarta.*`; JDK packages like `javax.crypto` and `javax.sql` stay as-is.
- Treat `WebSecurityConfigurerAdapter`, `authorizeRequests`, `antMatchers`, and `mvcMatchers` as security migration blockers.
- Treat `spring.factories`, starter modules, and custom auto-configuration as bean-loading risks that need manual review.
- Treat JPA usage as a Hibernate 6 review surface, not only an import-rename task.
- Prefer removing root causes over adding blanket JVM flags.

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
- `references/java-upgrade-paths.md`
- `references/spring-boot-2-to-3.md`
- `references/verification.md`
- `references/spring-cloud-config-and-bootstrap.md`
- `assets/migration-plan-template.md`
