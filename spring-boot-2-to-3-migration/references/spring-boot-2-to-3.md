# Spring Boot 2.x To 3.x

Use this file when the scan detects Spring Boot 2.x, Jakarta-related imports, Spring Security 5-era APIs, or custom auto-configuration.

## Non-Negotiable Rules

- Upgrade to the latest Spring Boot 2.7.x patch before moving to 3.x.
- Require Java 17+ before the Spring Boot 3 cutover.
- Do not rename `javax.*` blindly. Only Jakarta EE packages move; JDK `javax.*` packages like `javax.crypto` and `javax.sql` do not.
- Treat custom starters, `spring.factories`, and security configuration as high-risk migration areas.

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
3. Upgrade Boot and ecosystem dependencies.
4. Apply source changes: Jakarta, Security, auto-config, config properties, Hibernate.
5. Verify compile, tests, startup, and smoke flows.

## Commands

```bash
rg -n "import javax\\.(persistence|validation|servlet|annotation|ws\\.rs|jms)\\." .
rg -n "WebSecurityConfigurerAdapter|authorizeRequests\\(|antMatchers\\(|mvcMatchers\\(" .
rg -n "spring.factories|EnableAutoConfiguration" .
rg -n "createQuery\\(" .
```
