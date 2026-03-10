# Java Upgrade Paths

Use this file when the repository needs a Java major-version upgrade with or without Spring Boot changes.

## Rules

- Prefer staged LTS upgrades: 8 -> 11 -> 17 -> 21.
- For Spring Boot 3.x, require Java 17 or later.
- Do not adopt new language features during the same phase as breaking dependency upgrades unless the user asks for modernization.
- Treat reflective-access errors as dependency or framework compatibility issues first, not as a reason to blanket-add JVM flags.

## Scan First

Inspect:

- `pom.xml`, `build.gradle`, `build.gradle.kts`, `gradle.properties`, `libs.versions.toml`
- CI files that pin JDK versions
- Dockerfiles and runtime images
- Tooling versions for Surefire, Failsafe, Gradle wrapper, SpotBugs, Checkstyle, JaCoCo, Lombok, Mockito

## Migration Order

1. Lift the toolchain and CI runtime.
2. Upgrade plugins and build infrastructure.
3. Recompile and fix source incompatibilities.
4. Run tests.
5. Only after stability, optionally adopt new language features.

## Common Findings

- `javax.xml.bind` or `javax.activation` missing after JDK upgrades
- `sun.*` or `com.sun.*` internal API usage
- Outdated test or annotation processors failing on newer JDKs
- Old bytecode tooling that breaks on JDK 17+

## Commands

```bash
java -version
./mvnw -q -DskipTests compile
./gradlew help
python3 <skill-dir>/scripts/search_repo.py <repo> --pattern "sun\\.|com\\.sun\\.|javax\\.xml\\.bind|SecurityManager"
```
