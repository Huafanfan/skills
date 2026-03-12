# Spring Boot 2.x To 3.x

Use this file when the scan detects Spring Boot 2.x, Jakarta-related imports, Spring Security 5-era APIs, or custom auto-configuration.

Do not use this file to continue migration when scan support status is `blocked_by_external_parent`.
In that case the effective Boot version is not visible inside the current repository and the migration should stop until the missing parent or BOM context is available.

## Non-Negotiable Rules

- Upgrade to the latest Spring Boot 2.7.x patch before moving to 3.x.
- Require Java 17+ before the Spring Boot 3 cutover.
- Do not rename `javax.*` blindly. Only Jakarta EE packages move; JDK `javax.*` packages like `javax.crypto` and `javax.sql` do not.
- Treat custom starters, `spring.factories`, and security configuration as high-risk migration areas.
- Add `.migration-work/` to the target repository `.gitignore` before writing migration artifacts under that directory.
- If a build failure falls outside the hotspots in this file, keep debugging the first root cause and log any out-of-skill fixes or residual risk in `.migration-work/spring-boot-2-to-3/risk-register.md`.
- Do not create new environment-specific config files or Java configuration classes unless the existing repository structure proves they are required.

Why 2.7.x first:

- it is the last Spring Boot 2 line and the closest supported baseline before Boot 3
- it surfaces deprecations, property changes, and ecosystem alignment issues earlier
- it reduces the number of variables that change at once when Jakarta, Security 6, and Boot 3 behavior changes land

## Hotspots

### Jakarta

Check for:

- `javax.persistence`
- `javax.validation`
- `javax.servlet`
- `javax.ws.rs`
- `javax.annotation`
- `javax.jms`

Move only Jakarta EE APIs to `jakarta.*` and update matching dependencies.

### Spring Security

Check for:

- `WebSecurityConfigurerAdapter`
- `authorizeRequests`
- `antMatchers`
- `mvcMatchers`
- method security annotations that rely on parameter names

Expected remediation:

- replace `WebSecurityConfigurerAdapter` with `SecurityFilterChain`
- replace matcher APIs with `requestMatchers`
- compile with `-parameters` if method security relies on names
- do not generate new security configuration that still uses Boot 2 or Security 5 APIs

### Auto-Configuration And Beans

Check for:

- `META-INF/spring.factories`
- `META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports`
- custom `EnableAutoConfiguration` entries
- starter modules and framework integration libraries
- brittle bean ordering or conditional configuration

Expected remediation:

- migrate auto-configuration registration to `META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports`
- if the library must support Boot 2.7 and 3.x during transition, verify dual registration behavior intentionally instead of assuming it
- verify bean conditions, ordering, and conditional imports after the upgrade

### Configuration Properties

Check for renamed or removed properties and use the Spring properties migrator only as a temporary aid during the transition.

Also check for:

- `@ConstructorBinding` on the type itself
- removed or deprecated configuration helper APIs

Expected remediation:

- remove obsolete type-level `@ConstructorBinding` where Boot 3 no longer needs it
- treat the properties migrator as discovery tooling, not a permanent dependency

### Hibernate And JPA

Check for:

- raw `createQuery(...)` usage
- custom dialect configuration
- deprecated identifier generators
- old Hibernate 5 contracts

### Config Processing And Parsing

Check for:

- `bootstrap.yml`, `bootstrap.yaml`, `bootstrap.properties`
- `spring-cloud-starter-bootstrap`
- `spring.config.import=configserver:`
- `YamlJsonParser`

Expected remediation:

- migrate bootstrap-era assumptions to the supported Config Data model where required
- replace `YamlJsonParser` usages with a supported alternative

### HTTP Client Integrations

Check for:

- `RestTemplate` customizations backed by Apache HttpClient 4
- `HttpComponentsClientHttpRequestFactory`
- direct `org.apache.http.*` integrations around `RestTemplate`

Expected remediation:

- review and update the HTTP client stack instead of assuming old Apache HttpClient integrations keep working unchanged

## Phase Order

1. Baseline on latest 2.7.x with green tests.
2. Raise Java to 17+ and align build plugins.
3. Upgrade Boot, ecosystem, and blocked plugin dependencies.
4. Apply source changes: Jakarta, Security, auto-config, config properties, Hibernate.
5. Verify compile, tests, startup, and smoke flows.

## Commands

```bash
python3 <skill-dir>/scripts/search_repo.py <repo> --pattern "import javax\\.(persistence|validation|servlet|annotation|ws\\.rs|jms)\\."
python3 <skill-dir>/scripts/search_repo.py <repo> --pattern "WebSecurityConfigurerAdapter|authorizeRequests\\(|antMatchers\\(|mvcMatchers\\("
python3 <skill-dir>/scripts/search_repo.py <repo> --pattern "spring\\.factories|EnableAutoConfiguration"
python3 <skill-dir>/scripts/search_repo.py <repo> --pattern "createQuery\\("
```
