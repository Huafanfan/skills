# Migration Plan

## Detected State

- Build tool:
- Modules:
- Java:
- Spring Boot:
- High-risk areas:

## Phase Plan

### Phase 0: Baseline

- Create branch and capture current build and test results.

### Phase 1: Build and Runtime Baseline

- Upgrade Java toolchain, wrapper, and parent/BOM coordinates.

### Phase 2: Dependencies

- Align Spring, Security, Hibernate, testing, and plugin versions.

### Phase 3: Source and Config Changes

- Apply Jakarta renames, security DSL changes, auto-configuration updates, and property migrations.

### Phase 4: Verification

- Compile, test, start the app, and verify endpoints plus runtime warnings.

## Exit Criteria

- Clean compile
- Tests passing
- App starts on target runtime
- No remaining high-severity migration blockers
