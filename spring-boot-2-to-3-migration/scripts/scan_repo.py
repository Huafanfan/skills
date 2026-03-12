#!/usr/bin/env python3
"""Scan a Java repository and emit migration findings."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
import textwrap
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

IGNORE_DIRS = {
    ".codex",
    ".git",
    ".gradle",
    ".idea",
    ".migration-work",
    ".mvn",
    ".settings",
    "build",
    "node_modules",
    "out",
    "target",
}

TEXT_SUFFIXES = {
    ".gradle",
    ".java",
    ".kts",
    ".properties",
    ".toml",
    ".xml",
    ".yaml",
    ".yml",
}

JAKARTA_PREFIXES = (
    "javax.annotation",
    "javax.ejb",
    "javax.el",
    "javax.inject",
    "javax.interceptor",
    "javax.jms",
    "javax.mail",
    "javax.persistence",
    "javax.servlet",
    "javax.transaction",
    "javax.validation",
    "javax.websocket",
    "javax.ws.rs",
)


def find_files(root: Path, names: Iterable[str] | None = None, suffixes: Iterable[str] | None = None) -> list[Path]:
    matches: list[Path] = []
    wanted_names = set(names or [])
    wanted_suffixes = set(suffixes or [])
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in IGNORE_DIRS]
        current = Path(dirpath)
        for filename in filenames:
            path = current / filename
            if wanted_names and filename in wanted_names:
                matches.append(path)
            elif wanted_suffixes and path.suffix in wanted_suffixes:
                matches.append(path)
    return sorted(matches)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")


def rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def xml_namespace(element: ET.Element) -> str:
    if element.tag.startswith("{"):
        return element.tag.split("}", 1)[0][1:]
    return ""


def child_text(element: ET.Element, tag: str, namespace: str) -> str | None:
    name = f"{{{namespace}}}{tag}" if namespace else tag
    child = element.find(name)
    if child is not None and child.text:
        return child.text.strip()
    return None


def parse_properties(element: ET.Element | None, namespace: str) -> dict[str, str]:
    properties: dict[str, str] = {}
    if element is None:
        return properties
    for child in list(element):
        tag = child.tag.split("}", 1)[1] if "}" in child.tag else child.tag
        if child.text and child.text.strip():
            properties[tag] = child.text.strip()
    return properties


def resolve_property(value: str | None, properties: dict[str, str]) -> str | None:
    if not value:
        return value
    match = re.fullmatch(r"\$\{([^}]+)\}", value.strip())
    if match:
        return properties.get(match.group(1), value)
    return value


def parse_pom(path: Path, root: Path) -> dict:
    result = {
        "path": rel(path, root),
        "java_version": None,
        "spring_boot_version": None,
        "spring_boot_version_source": None,
        "spring_cloud_version": None,
        "dependencies": [],
        "parent_group_id": None,
        "parent_artifact_id": None,
        "parent_version": None,
        "parent_relative_path": None,
        "declares_spring_boot_usage": False,
    }
    try:
        tree = ET.parse(path)
    except ET.ParseError:
        return result
    project = tree.getroot()
    namespace = xml_namespace(project)

    properties_name = f"{{{namespace}}}properties" if namespace else "properties"
    properties = parse_properties(project.find(properties_name), namespace)
    if properties:
        for key in ("java.version", "maven.compiler.release", "maven.compiler.target", "maven.compiler.source"):
            if properties.get(key):
                result["java_version"] = properties[key]
                break
        for key in ("spring-boot.version", "spring.boot.version", "version.spring.boot"):
            if properties.get(key):
                result["spring_boot_version"] = properties[key]
                result["spring_boot_version_source"] = "property"
                break
        for key in ("spring-cloud.version", "version.spring.cloud", "version.spring.cloud.config"):
            if properties.get(key):
                result["spring_cloud_version"] = properties[key]
                break

    parent_name = f"{{{namespace}}}parent" if namespace else "parent"
    parent = project.find(parent_name)
    if parent is not None:
        group_id = child_text(parent, "groupId", namespace)
        artifact_id = child_text(parent, "artifactId", namespace)
        version = resolve_property(child_text(parent, "version", namespace), properties)
        result["parent_group_id"] = group_id
        result["parent_artifact_id"] = artifact_id
        result["parent_version"] = version
        result["parent_relative_path"] = child_text(parent, "relativePath", namespace)
        if group_id == "org.springframework.boot" and artifact_id == "spring-boot-starter-parent":
            result["spring_boot_version"] = version
            result["spring_boot_version_source"] = "boot_parent"
            result["declares_spring_boot_usage"] = True

    dependency_name = f".//{{{namespace}}}dependency" if namespace else ".//dependency"
    for dependency in project.findall(dependency_name):
        group_id = child_text(dependency, "groupId", namespace) or ""
        artifact_id = child_text(dependency, "artifactId", namespace) or ""
        version = resolve_property(child_text(dependency, "version", namespace), properties)
        if group_id and artifact_id:
            if group_id == "org.springframework.boot" or artifact_id.startswith("spring-boot"):
                result["declares_spring_boot_usage"] = True
            result["dependencies"].append(
                {
                    "group_id": group_id,
                    "artifact_id": artifact_id,
                    "version": version,
                }
            )
            if artifact_id == "spring-boot-dependencies" and group_id == "org.springframework.boot" and version:
                result["spring_boot_version"] = version
                result["spring_boot_version_source"] = "boot_bom"
            if artifact_id.startswith("spring-cloud-") and group_id == "org.springframework.cloud" and version:
                result["spring_cloud_version"] = version
    return result


def parse_gradle(path: Path, root: Path) -> dict:
    text = read_text(path)
    result = {
        "path": rel(path, root),
        "java_version": None,
        "spring_boot_version": None,
        "spring_boot_version_source": None,
        "declares_spring_boot_usage": False,
    }
    if "org.springframework.boot" in text or "spring-boot-starter" in text:
        result["declares_spring_boot_usage"] = True
    patterns = [
        r'id\(["\']org\.springframework\.boot["\']\)\s+version\s+["\']([^"\']+)["\']',
        r'id\s+["\']org\.springframework\.boot["\']\s+version\s+["\']([^"\']+)["\']',
        r'springBootVersion\s*=\s*["\']([^"\']+)["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            result["spring_boot_version"] = match.group(1)
            result["spring_boot_version_source"] = "gradle_plugin"
            break
    java_patterns = [
        r'JavaLanguageVersion\.of\((\d+)\)',
        r'sourceCompatibility\s*=\s*["\']?VERSION_(\d+)["\']?',
        r'sourceCompatibility\s*=\s*["\']?(\d+)["\']?',
        r'targetCompatibility\s*=\s*["\']?(\d+)["\']?',
    ]
    for pattern in java_patterns:
        match = re.search(pattern, text)
        if match:
            result["java_version"] = match.group(1)
            break
    return result


def major_version(version: str | None) -> int | None:
    if not version:
        return None
    match = re.search(r"(\d+)", version)
    return int(match.group(1)) if match else None


def java_major_version(version: str | None) -> int | None:
    if not version:
        return None
    normalized = version.strip()
    if normalized.startswith("1."):
        parts = normalized.split(".")
        if len(parts) > 1 and parts[1].isdigit():
            return int(parts[1])
    return major_version(version)


def prefer_concrete_versions(versions: list[str]) -> list[str]:
    concrete = [value for value in versions if not value.startswith("${")]
    chosen = concrete or versions
    return sorted(set(chosen))


def resolve_local_parent_path(model: dict, root: Path) -> Path | None:
    if not model.get("parent_group_id") or not model.get("parent_artifact_id"):
        return None
    relative_path = model.get("parent_relative_path")
    if relative_path == "":
        return None
    base_dir = (root / model["path"]).resolve().parent
    candidate = (base_dir / (relative_path or "../pom.xml")).resolve()
    if not candidate.exists():
        return None
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def resolve_boot_via_local_parent(model: dict, root: Path, models_by_abs_path: dict[Path, dict], visited: set[Path] | None = None) -> tuple[str | None, str | None]:
    visited = visited or set()
    parent_path = resolve_local_parent_path(model, root)
    if not parent_path or parent_path in visited:
        return (None, None)
    visited.add(parent_path)
    parent_model = models_by_abs_path.get(parent_path)
    if not parent_model:
        return (None, None)
    if parent_model.get("spring_boot_version"):
        return (parent_model["spring_boot_version"], parent_model["path"])
    return resolve_boot_via_local_parent(parent_model, root, models_by_abs_path, visited)


def classify_support_status(root: Path, maven_models: list[dict], gradle_models: list[dict]) -> tuple[str, str, list[str], list[str]]:
    direct_evidence: list[str] = []
    local_parent_evidence: list[str] = []
    blocked_evidence: list[str] = []
    resolved_versions: list[str] = []

    models_by_abs_path = {(root / model["path"]).resolve(): model for model in maven_models}

    for model in maven_models:
        direct_version = model.get("spring_boot_version")
        if direct_version and not direct_version.startswith("${"):
            resolved_versions.append(direct_version)
            if model.get("declares_spring_boot_usage") or model.get("spring_boot_version_source"):
                direct_evidence.append(model["path"])
            continue

        local_version, parent_path = resolve_boot_via_local_parent(model, root, models_by_abs_path)
        if local_version:
            resolved_versions.append(local_version)
            if model.get("declares_spring_boot_usage"):
                local_parent_evidence.append(model["path"])
            model["resolved_spring_boot_version"] = local_version
            model["resolved_spring_boot_source_path"] = parent_path
            continue

        if model.get("declares_spring_boot_usage"):
            blocked_evidence.append(model["path"])

    for model in gradle_models:
        direct_version = model.get("spring_boot_version")
        if direct_version and not direct_version.startswith("${"):
            resolved_versions.append(direct_version)
            if model.get("declares_spring_boot_usage"):
                direct_evidence.append(model["path"])

    if blocked_evidence:
        return (
            "blocked_by_external_parent",
            "Spring Boot usage was detected, but the effective Boot version is controlled outside the current repository through an external parent or BOM that cannot be resolved here.",
            sorted(set(blocked_evidence)),
            prefer_concrete_versions(resolved_versions),
        )
    if local_parent_evidence:
        return (
            "supported_via_local_parent",
            "Spring Boot versioning is inherited through a parent POM that exists inside the current repository, so the skill can continue after resolving that local parent chain.",
            sorted(set(local_parent_evidence)),
            prefer_concrete_versions(resolved_versions),
        )
    if direct_evidence:
        return (
            "directly_supported",
            "Spring Boot versioning is managed directly by the current repository build files.",
            sorted(set(direct_evidence)),
            prefer_concrete_versions(resolved_versions),
        )
    return (
        "not_applicable",
        "No directly supported Spring Boot version management was detected in the current repository.",
        [],
        prefer_concrete_versions(resolved_versions),
    )


def scan_text_files(root: Path) -> dict:
    stats = Counter()
    evidence: dict[str, list[str]] = defaultdict(list)
    paths = {
        *find_files(root, suffixes=TEXT_SUFFIXES),
        *find_files(root, names=["spring.factories", "org.springframework.boot.autoconfigure.AutoConfiguration.imports"]),
    }
    for path in sorted(paths):
        text = read_text(path)
        relative = rel(path, root)
        if "WebSecurityConfigurerAdapter" in text:
            stats["web_security_configurer_adapter"] += 1
            evidence["web_security_configurer_adapter"].append(relative)
        if "authorizeRequests(" in text:
            stats["authorize_requests"] += 1
            evidence["authorize_requests"].append(relative)
        if "antMatchers(" in text:
            stats["ant_matchers"] += 1
            evidence["ant_matchers"].append(relative)
        if "mvcMatchers(" in text:
            stats["mvc_matchers"] += 1
            evidence["mvc_matchers"].append(relative)
        if path.name in {"bootstrap.yml", "bootstrap.yaml", "bootstrap.properties"}:
            stats["bootstrap_config"] += 1
            evidence["bootstrap_config"].append(relative)
        if "spring.cloud.config" in text or "spring-cloud-starter-config" in text:
            stats["spring_cloud_config"] += 1
            evidence["spring_cloud_config"].append(relative)
        if "spring-cloud-starter-bootstrap" in text or "spring.cloud.bootstrap.enabled" in text:
            stats["spring_cloud_bootstrap"] += 1
            evidence["spring_cloud_bootstrap"].append(relative)
        if "spring.config.import" in text and "configserver:" in text:
            stats["config_data_import"] += 1
            evidence["config_data_import"].append(relative)
        if (
            path.name == "spring.factories"
            or path.name == "org.springframework.boot.autoconfigure.AutoConfiguration.imports"
            or "EnableAutoConfiguration" in text
        ):
            stats["auto_configuration"] += 1
            evidence["auto_configuration"].append(relative)
        if "@ConfigurationProperties" in text:
            stats["configuration_properties"] += 1
            evidence["configuration_properties"].append(relative)
        if "@ConstructorBinding" in text:
            stats["constructor_binding"] += 1
            evidence["constructor_binding"].append(relative)
        if "createQuery(" in text:
            stats["hibernate_queries"] += 1
            evidence["hibernate_queries"].append(relative)
        if "YamlJsonParser" in text:
            stats["yaml_json_parser"] += 1
            evidence["yaml_json_parser"].append(relative)
        if (
            "RestTemplate" in text
            and (
                "org.apache.http." in text
                or "HttpComponentsClientHttpRequestFactory" in text
                or "CloseableHttpClient" in text
            )
        ):
            stats["resttemplate_httpclient"] += 1
            evidence["resttemplate_httpclient"].append(relative)
        if "org.junit.Test" in text or "org.junit.Before" in text:
            stats["junit4"] += 1
            evidence["junit4"].append(relative)
        if "javax.xml.bind" in text:
            stats["jaxb"] += 1
            evidence["jaxb"].append(relative)
        if "SecurityManager" in text or "System.getSecurityManager" in text:
            stats["security_manager"] += 1
            evidence["security_manager"].append(relative)
        if "sun.misc.Unsafe" in text or "com.sun." in text or "sun." in text:
            stats["internal_apis"] += 1
            evidence["internal_apis"].append(relative)
        for prefix in JAKARTA_PREFIXES:
            if f"import {prefix}." in text or f"{prefix}." in text:
                stats["jakarta_candidates"] += 1
                evidence["jakarta_candidates"].append(relative)
                break
    return {"stats": stats, "evidence": evidence}


def detect_build(root: Path) -> dict:
    poms = find_files(root, names=["pom.xml"])
    gradle_files = find_files(root, names=["build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts", "gradle.properties", "libs.versions.toml"])
    maven_models = [parse_pom(path, root) for path in poms]
    gradle_models = [parse_gradle(path, root) for path in gradle_files if path.name in {"build.gradle", "build.gradle.kts"}]
    support_status, support_reason, support_evidence, resolved_boot_versions = classify_support_status(root, maven_models, gradle_models)

    java_versions = [model["java_version"] for model in maven_models + gradle_models if model["java_version"]]
    spring_versions = resolved_boot_versions
    spring_cloud_versions = [model["spring_cloud_version"] for model in maven_models if model["spring_cloud_version"]]

    dependencies = []
    for model in maven_models:
        dependencies.extend(model["dependencies"])
    return {
        "has_maven": bool(poms),
        "has_gradle": any(path.name.startswith("build.gradle") for path in gradle_files),
        "maven_files": [rel(path, root) for path in poms],
        "gradle_files": [rel(path, root) for path in gradle_files],
        "java_versions": sorted(set(java_versions)),
        "spring_boot_versions": prefer_concrete_versions(spring_versions),
        "spring_cloud_versions": prefer_concrete_versions(spring_cloud_versions),
        "dependencies": dependencies,
        "support_status": support_status,
        "support_reason": support_reason,
        "support_evidence": support_evidence,
    }


def summarize_dependencies(build: dict) -> dict:
    summary = {
        "uses_spring_boot": False,
        "uses_spring_security": False,
        "uses_spring_data_jpa": False,
        "uses_spring_cloud": False,
        "uses_config_client": False,
        "uses_config_server": False,
        "uses_testcontainers": False,
        "uses_lombok": False,
    }
    for dependency in build["dependencies"]:
        gav = f'{dependency["group_id"]}:{dependency["artifact_id"]}'
        if dependency["group_id"] == "org.springframework.boot":
            summary["uses_spring_boot"] = True
        if dependency["group_id"] == "org.springframework.cloud":
            summary["uses_spring_cloud"] = True
        if dependency["group_id"].startswith("org.springframework.security"):
            summary["uses_spring_security"] = True
        if gav == "org.springframework.boot:spring-boot-starter-data-jpa":
            summary["uses_spring_data_jpa"] = True
        if gav == "org.springframework.cloud:spring-cloud-starter-config":
            summary["uses_config_client"] = True
        if gav == "org.springframework.cloud:spring-cloud-config-server":
            summary["uses_config_server"] = True
        if dependency["group_id"].startswith("org.testcontainers"):
            summary["uses_testcontainers"] = True
        if gav == "org.projectlombok:lombok":
            summary["uses_lombok"] = True
    if build["spring_boot_versions"]:
        summary["uses_spring_boot"] = True
    if build["spring_cloud_versions"]:
        summary["uses_spring_cloud"] = True
    return summary


def add_finding(findings: list[dict], severity: str, title: str, detail: str, evidence: list[str]) -> None:
    findings.append(
        {
            "severity": severity,
            "title": title,
            "detail": detail,
            "evidence": sorted(set(evidence))[:12],
        }
    )


def add_todo(
    todos: list[dict],
    *,
    phase: str,
    path: str,
    title: str,
    action: str,
    verify: str,
    priority: str,
) -> None:
    item = {
        "phase": phase,
        "path": path,
        "title": title,
        "action": action,
        "verify": verify,
        "priority": priority,
    }
    if item not in todos:
        todos.append(item)


def preferred_maven_command(root: Path) -> str:
    return "./mvnw" if (root / "mvnw").exists() else "mvn"


def preferred_gradle_command(root: Path) -> str:
    return "./gradlew" if (root / "gradlew").exists() else "gradle"


def preferred_pom_path(root: Path, build: dict) -> Path:
    root_pom = root / "pom.xml"
    if root_pom.exists():
        return root_pom
    if build["maven_files"]:
        return root / build["maven_files"][0]
    return root_pom


def build_compile_command(root: Path, build: dict) -> str | None:
    if build["has_maven"]:
        wrapper = root / "mvnw"
        if wrapper.exists() and os.access(wrapper, os.X_OK):
            return f"{shlex.quote(str(wrapper))} -q -DskipTests compile"
        pom = preferred_pom_path(root, build)
        return f"mvn -f {shlex.quote(str(pom))} -q -DskipTests compile"
    if build["has_gradle"]:
        wrapper = root / "gradlew"
        if wrapper.exists() and os.access(wrapper, os.X_OK):
            return f"{shlex.quote(str(wrapper))} compileJava"
        return f"gradle -p {shlex.quote(str(root))} compileJava"
    return None


def build_test_command(root: Path, build: dict) -> str | None:
    if build["has_maven"]:
        wrapper = root / "mvnw"
        if wrapper.exists() and os.access(wrapper, os.X_OK):
            return f"{shlex.quote(str(wrapper))} test"
        pom = preferred_pom_path(root, build)
        return f"mvn -f {shlex.quote(str(pom))} test"
    if build["has_gradle"]:
        wrapper = root / "gradlew"
        if wrapper.exists() and os.access(wrapper, os.X_OK):
            return f"{shlex.quote(str(wrapper))} test"
        return f"gradle -p {shlex.quote(str(root))} test"
    return None


def build_openrewrite_command(root: Path, build: dict) -> str | None:
    if not build["has_maven"]:
        return None
    wrapper = root / "mvnw"
    prefix = shlex.quote(str(wrapper)) if wrapper.exists() and os.access(wrapper, os.X_OK) else f"mvn -f {shlex.quote(str(preferred_pom_path(root, build)))}"
    return (
        f"{prefix} org.openrewrite.maven:rewrite-maven-plugin:run "
        "-Drewrite.recipeArtifactCoordinates=org.openrewrite.recipe:rewrite-spring:LATEST "
        "-Drewrite.activeRecipes=org.openrewrite.java.spring.boot3.UpgradeSpringBoot_3_0"
    )


def build_findings(root: Path, build: dict, text_scan: dict, dep_summary: dict) -> list[dict]:
    findings: list[dict] = []
    stats = text_scan["stats"]
    evidence = text_scan["evidence"]
    java_majors = [java_major_version(value) for value in build["java_versions"]]
    java_major = min([value for value in java_majors if value is not None], default=None)
    spring_version = build["spring_boot_versions"][0] if build["spring_boot_versions"] else None
    spring_major = major_version(spring_version)
    spring_cloud_version = build["spring_cloud_versions"][0] if build["spring_cloud_versions"] else None

    if not build["has_maven"] and not build["has_gradle"]:
        add_finding(
            findings,
            "medium",
            "No supported Java build file detected",
            "The repository does not expose pom.xml or build.gradle at the scanned paths. Migration can continue only after locating the real build entrypoint.",
            [],
        )
        return findings

    if build["support_status"] == "blocked_by_external_parent":
        add_finding(
            findings,
            "high",
            "Spring Boot version is controlled outside this repository",
            (
                f"{build['support_reason']} Stop migration work here, explain the limitation to the user, "
                "and ask for the external parent or BOM context, an effective POM, or a repository checkout that includes the version-managing build files."
            ),
            build["support_evidence"] or build["maven_files"] or build["gradle_files"],
        )
        return findings

    if spring_major == 2:
        detail = (
            "Spring Boot 2.x was detected. Plan a staged upgrade through latest 2.7.x before moving to 3.x. "
            "The 2.7.x step reduces migration risk by surfacing the closest deprecations, property changes, and ecosystem alignment issues before the Boot 3 cutover."
        )
        if java_major is not None and java_major < 17:
            detail += f" Current detected Java baseline is {java_major}, so Java 17+ must land before the Boot 3 cutover."
        add_finding(findings, "high", "Spring Boot 2.x to 3.x migration required", detail, build["maven_files"] + build["gradle_files"])
    elif spring_major is not None and spring_major < 2:
        add_finding(
            findings,
            "high",
            "Spring Boot baseline is older than 2.x",
            f"Detected Spring Boot baseline is {spring_version}. This repository needs staged upgrades before any Boot 3 migration plan is realistic.",
            build["maven_files"] + build["gradle_files"],
        )
    elif spring_major is not None and spring_major < 3:
        add_finding(
            findings,
            "medium",
            "Spring Boot baseline is pre-3.x",
            f"Detected Spring Boot baseline is {spring_version}. Plan staged framework upgrades before modernization work.",
            build["maven_files"] + build["gradle_files"],
        )

    if java_major is not None and java_major < 17 and spring_major == 2:
        add_finding(
            findings,
            "high",
            "Java baseline too old for Spring Boot 3",
            f"Detected Java baseline is {java_major}. Spring Boot 3 requires Java 17 or later.",
            build["maven_files"] + build["gradle_files"],
        )
    elif java_major is not None and java_major < 17:
        add_finding(
            findings,
            "medium",
            "Legacy Java baseline detected",
            f"Detected Java baseline is {java_major}. Plan an LTS upgrade before or alongside framework migration.",
            build["maven_files"] + build["gradle_files"],
        )

    if dep_summary["uses_spring_cloud"] or stats["spring_cloud_config"] or stats["bootstrap_config"]:
        detail = "Spring Cloud components were detected. Validate the Spring Cloud release train against the target Boot version and review config loading behavior."
        if spring_cloud_version:
            detail += f" Detected Spring Cloud version is {spring_cloud_version}."
        if stats["bootstrap_config"] or stats["spring_cloud_bootstrap"]:
            detail += " Bootstrap-era configuration was found, so review migration to Config Data and remove bootstrap-only assumptions."
        elif stats["config_data_import"]:
            detail += " Config Data imports are already present, but compatibility and property loading order still need review."
        add_finding(
            findings,
            "high" if spring_major == 2 or (spring_major is not None and spring_major < 2) else "medium",
            "Spring Cloud compatibility and config loading review required",
            detail,
            evidence["spring_cloud_config"] + evidence["spring_cloud_bootstrap"] + evidence["bootstrap_config"] + evidence["config_data_import"] + build["maven_files"],
        )

    if stats["jakarta_candidates"]:
        add_finding(
            findings,
            "high" if spring_major == 2 else "medium",
            "Jakarta namespace migration likely required",
            "Repository uses Jakarta EE related javax packages. These imports and matching dependencies usually need coordinated migration to jakarta.* during Spring Boot 3 adoption.",
            evidence["jakarta_candidates"],
        )

    if stats["web_security_configurer_adapter"] or stats["authorize_requests"] or stats["ant_matchers"] or stats["mvc_matchers"]:
        add_finding(
            findings,
            "high" if spring_major == 2 else "medium",
            "Legacy Spring Security DSL detected",
            "Security configuration still uses Spring Security 5-era APIs. Expect migration to SecurityFilterChain and requestMatchers.",
            evidence["web_security_configurer_adapter"] + evidence["authorize_requests"] + evidence["ant_matchers"] + evidence["mvc_matchers"],
        )

    if stats["auto_configuration"]:
        add_finding(
            findings,
            "high",
            "Custom auto-configuration or starter patterns detected",
            "Custom starters and spring.factories registration need manual review because Boot 3 changes auto-configuration registration and can affect bean loading order.",
            evidence["auto_configuration"],
        )

    if stats["configuration_properties"]:
        add_finding(
            findings,
            "medium",
            "Configuration properties migration surface detected",
            "Repositories with @ConfigurationProperties often need property rename checks and constructor-binding review during Boot 3 upgrades.",
            evidence["configuration_properties"],
        )

    if stats["constructor_binding"]:
        add_finding(
            findings,
            "medium",
            "@ConstructorBinding migration review required",
            "Type-level @ConstructorBinding is no longer needed in Spring Boot 3. Review constructor-bound configuration classes and remove obsolete annotations where appropriate.",
            evidence["constructor_binding"],
        )

    if stats["hibernate_queries"] or dep_summary["uses_spring_data_jpa"]:
        hibernate_evidence = evidence["hibernate_queries"] or build["maven_files"] + build["gradle_files"]
        add_finding(
            findings,
            "medium",
            "Hibernate and JPA compatibility review required",
            "JPA usage was detected. Review Hibernate 6 query typing, identifier strategies, and dialect assumptions.",
            hibernate_evidence,
        )

    if stats["junit4"]:
        add_finding(
            findings,
            "medium",
            "JUnit 4 tests detected",
            "Legacy JUnit 4 tests can slow or block framework upgrades. Plan migration to JUnit 5 where practical.",
            evidence["junit4"],
        )

    if stats["jaxb"]:
        add_finding(
            findings,
            "medium",
            "JAXB legacy API usage detected",
            "javax.xml.bind usage needs explicit dependency handling on modern JDKs.",
            evidence["jaxb"],
        )

    if stats["yaml_json_parser"]:
        add_finding(
            findings,
            "medium",
            "YamlJsonParser removal affects this repository",
            "Spring Boot 3 removes YamlJsonParser. Replace it with a supported parser or another config-processing approach.",
            evidence["yaml_json_parser"],
        )

    if stats["resttemplate_httpclient"]:
        add_finding(
            findings,
            "medium",
            "RestTemplate Apache HttpClient integration review required",
            "RestTemplate setups backed by Apache HttpClient need review during Boot 3 migration because the supported HTTP client stack changed.",
            evidence["resttemplate_httpclient"],
        )

    if stats["internal_apis"] or stats["security_manager"]:
        add_finding(
            findings,
            "medium",
            "JDK internal or removed APIs detected",
            "Internal JDK APIs or SecurityManager usage were found. These require targeted remediation during Java major-version upgrades.",
            evidence["internal_apis"] + evidence["security_manager"],
        )

    return findings


def build_todo_items(root: Path, build: dict, text_scan: dict, dep_summary: dict) -> list[dict]:
    todos: list[dict] = []
    evidence = text_scan["evidence"]
    spring_version = build["spring_boot_versions"][0] if build["spring_boot_versions"] else None
    spring_major = major_version(spring_version)
    java_values = [java_major_version(value) for value in build["java_versions"]]
    java_major = min([value for value in java_values if value is not None], default=None)
    build_files = build["maven_files"] + build["gradle_files"]

    if build["support_status"] == "blocked_by_external_parent":
        add_todo(
            todos,
            phase="Phase 0",
            path=build["support_evidence"][0] if build["support_evidence"] else (build_files[0] if build_files else "."),
            title="Stop and collect external parent or BOM context",
            action="Do not continue the migration in this checkout. Explain that the effective Spring Boot version is inherited from a parent or BOM outside the repository and ask the user for the parent repository, the effective POM, or a checkout that includes the version-managing build files.",
            verify="Resume only after the effective Spring Boot baseline is visible inside the working repository context.",
            priority="high",
        )
        return todos

    if spring_major == 2:
        for path in build_files:
            add_todo(
                todos,
                phase="Phase 0.5",
                path=path,
                title="Pin latest Spring Boot 2.7.x before Boot 3",
                action="Update the Spring Boot parent, plugin, or BOM to the latest 2.7.x patch and get the repository green before attempting the 3.x cutover. This shrinks the migration jump and exposes the closest Boot 2-era deprecations and config changes before Boot 3 lands.",
                verify="Run compile and tests on the updated 2.7.x baseline.",
                priority="high",
            )
    elif spring_major is not None and spring_major < 2:
        for path in build_files:
            add_todo(
                todos,
                phase="Phase 0.5",
                path=path,
                title="Stage upgrades before Boot 3",
                action="Move this repository to a Spring Boot 2.7.x baseline first. Boot 1.x projects should not jump directly to Spring Boot 3.",
                verify="Confirm the app is stable on Spring Boot 2.7.x before planning the Boot 3 step.",
                priority="high",
            )

    if java_major is not None and java_major < 17:
        for path in build_files:
            add_todo(
                todos,
                phase="Phase 1",
                path=path,
                title="Raise Java baseline to 17+",
                action="Update toolchain, compiler settings, wrapper configuration, container images, and CI runtime to Java 17 or later before the Spring Boot 3 cutover.",
                verify="Run `java -version` and a clean compile on Java 17+.",
                priority="high",
            )

    for path in evidence["spring_cloud_config"] + evidence["spring_cloud_bootstrap"] + evidence["config_data_import"]:
        add_todo(
            todos,
            phase="Phase 1.5",
            path=path,
            title="Review Spring Cloud and config loading compatibility",
            action="Align the Spring Cloud release train with the target Spring Boot version and decide whether this file should stay on Config Data, move away from bootstrap-era behavior, or both.",
            verify="Start config clients and servers after the upgrade and confirm remote properties load in the expected order.",
            priority="high",
        )

    for path in evidence["bootstrap_config"]:
        add_todo(
            todos,
            phase="Phase 1.5",
            path=path,
            title="Migrate bootstrap-era configuration",
            action="Review bootstrap-specific properties and move them to the supported Config Data model where required by the target Spring Cloud line.",
            verify="Start the application and confirm external config still loads without bootstrap-specific assumptions.",
            priority="high",
        )

    for path in evidence["jakarta_candidates"]:
        add_todo(
            todos,
            phase="Phase 3",
            path=path,
            title="Migrate Jakarta imports and dependencies",
            action="Replace Jakarta EE `javax.*` imports with `jakarta.*` where appropriate and align the matching dependencies. Do not touch JDK packages such as `javax.crypto` or `javax.sql`.",
            verify="Recompile this source file and confirm no missing Jakarta types remain.",
            priority="high" if spring_major == 2 else "medium",
        )

    for path in evidence["web_security_configurer_adapter"] + evidence["authorize_requests"] + evidence["ant_matchers"] + evidence["mvc_matchers"]:
        add_todo(
            todos,
            phase="Phase 3",
            path=path,
            title="Migrate Spring Security 5-era DSL",
            action="Replace `WebSecurityConfigurerAdapter` with bean-based `SecurityFilterChain` configuration and migrate matcher APIs to `requestMatchers`. Review authentication manager wiring and method-security parameter names as needed.",
            verify="Run security-related tests and start the app to confirm the filter chain builds cleanly.",
            priority="high",
        )

    for path in evidence["auto_configuration"]:
        add_todo(
            todos,
            phase="Phase 3",
            path=path,
            title="Migrate auto-configuration registration",
            action="Move Boot auto-configuration registration to `META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports` and review starter bean conditions, ordering, and imports.",
            verify="Start the application or starter consumer and confirm expected beans are created.",
            priority="high",
        )

    for path in evidence["configuration_properties"]:
        add_todo(
            todos,
            phase="Phase 3",
            path=path,
            title="Review configuration properties binding",
            action="Check for renamed properties, constructor-binding assumptions, validation issues, and any temporary use of the Spring properties migrator.",
            verify="Start the app and confirm property binding succeeds without warnings or missing values.",
            priority="medium",
        )

    for path in evidence["constructor_binding"]:
        add_todo(
            todos,
            phase="Phase 3",
            path=path,
            title="Remove obsolete type-level @ConstructorBinding",
            action="Review whether this type-level `@ConstructorBinding` annotation can be removed for Spring Boot 3 while preserving the intended binding model.",
            verify="Compile and run property-binding tests or startup checks for this configuration class.",
            priority="medium",
        )

    hibernate_paths = evidence["hibernate_queries"] or ([] if not dep_summary["uses_spring_data_jpa"] else build_files)
    for path in hibernate_paths:
        add_todo(
            todos,
            phase="Phase 3",
            path=path,
            title="Review Hibernate 6 and JPA compatibility",
            action="Check typed query usage, identifier generation, dialect configuration, and any Hibernate 5-specific APIs that need updating.",
            verify="Run persistence tests and start the app against the target database profile.",
            priority="medium",
        )

    for path in evidence["junit4"]:
        add_todo(
            todos,
            phase="Phase 3",
            path=path,
            title="Migrate JUnit 4 usage",
            action="Move remaining JUnit 4 tests and rules to JUnit 5 or isolate legacy tests that block the framework upgrade.",
            verify="Run the targeted test task and confirm the JUnit platform discovers and executes the suite.",
            priority="medium",
        )

    for path in evidence["jaxb"]:
        add_todo(
            todos,
            phase="Phase 3",
            path=path,
            title="Replace legacy JAXB assumptions",
            action="Add the required JAXB dependencies for modern JDKs or refactor the affected code away from `javax.xml.bind`.",
            verify="Compile the affected module on the target JDK.",
            priority="medium",
        )

    for path in evidence["yaml_json_parser"]:
        add_todo(
            todos,
            phase="Phase 3",
            path=path,
            title="Replace YamlJsonParser usage",
            action="Replace `YamlJsonParser` with a supported parser or another config-processing approach compatible with Spring Boot 3.",
            verify="Compile and run the code path that previously depended on YamlJsonParser.",
            priority="medium",
        )

    for path in evidence["resttemplate_httpclient"]:
        add_todo(
            todos,
            phase="Phase 3",
            path=path,
            title="Review RestTemplate HTTP client wiring",
            action="Update any RestTemplate integrations backed by Apache HttpClient to a supported client stack for the target Spring Boot line.",
            verify="Exercise the affected outbound HTTP path after the dependency upgrade.",
            priority="medium",
        )

    for path in evidence["internal_apis"] + evidence["security_manager"]:
        add_todo(
            todos,
            phase="Phase 3",
            path=path,
            title="Remove internal or removed JDK API usage",
            action="Replace unsupported JDK internals or SecurityManager-era code with supported APIs before finalizing the Java 17+ migration.",
            verify="Compile and run the affected module on the target JDK without relying on blanket JVM flags.",
            priority="medium",
        )

    return sorted(todos, key=lambda item: (item["phase"], item["priority"], item["path"], item["title"]))


def build_command_plan(root: Path, build: dict, text_scan: dict) -> list[dict]:
    commands: list[dict] = []
    if build["support_status"] == "blocked_by_external_parent":
        return [
            {
                "phase": "Phase 0",
                "purpose": "Stop and explain the external parent or BOM limitation",
                "command": "Stop migration work. Ask the user for the external parent repository, an effective POM, or a checkout that includes the build file that manages Spring Boot versions.",
            }
        ]
    build_cmd = build_compile_command(root, build)
    test_cmd = build_test_command(root, build)
    search_script = Path(__file__).resolve().parent / "search_repo.py"
    probe_script = Path(__file__).resolve().parent / "probe_versions.py"
    verify_script = Path(__file__).resolve().parent / "verify_repo.py"
    repo_arg = shlex.quote(str(root))
    gitignore_path = shlex.quote(str(root / ".gitignore"))

    def add_command(phase: str, purpose: str, command: str) -> None:
        item = {"phase": phase, "purpose": purpose, "command": command}
        if item not in commands:
            commands.append(item)

    def search_command(pattern: str) -> str:
        escaped = pattern.replace('"', '\\"')
        return f'python3 {shlex.quote(str(search_script))} {repo_arg} --pattern "{escaped}"'

    add_command("Phase 0", "Capture branch and working tree state", "git status --short")
    add_command(
        "Phase 0",
        "Ensure migration workspace is ignored by git",
        f"grep -qxF '.migration-work/' {gitignore_path} 2>/dev/null || printf '\\n.migration-work/\\n' >> {gitignore_path}",
    )
    add_command("Phase 0", "Confirm runtime Java", "java -version")
    if build_cmd:
        add_command("Phase 0", "Capture pre-migration compile baseline", build_cmd)
    if test_cmd:
        add_command("Phase 0", "Capture pre-migration test baseline", test_cmd)

    add_command("Phase 1", "Find Jakarta migration targets", search_command(r"import javax\.(annotation|ejb|el|inject|interceptor|jms|mail|persistence|servlet|transaction|validation|websocket|ws\.rs)\."))
    add_command("Phase 1", "Find legacy Spring Security DSL usage", search_command(r"WebSecurityConfigurerAdapter|authorizeRequests\(|antMatchers\(|mvcMatchers\("))
    add_command("Phase 1", "Find auto-configuration registrations", search_command(r"spring\.factories|EnableAutoConfiguration|AutoConfiguration\.imports"))

    if build["spring_cloud_versions"]:
        add_command("Phase 1.5", "Find Spring Cloud config-loading files", search_command(r"spring\.cloud|spring\.config\.import|configserver:|bootstrap"))

    if build["has_maven"]:
        rewrite_cmd = build_openrewrite_command(root, build)
        if rewrite_cmd:
            add_command("Phase 2", "Optional OpenRewrite run for Boot 3 migration", rewrite_cmd)
        add_command(
            "Phase 2",
            "Probe Maven anchor versions if repository gateway rejects a version",
            (
                f"python3 {shlex.quote(str(probe_script))} {repo_arg} "
                f"--output-dir {shlex.quote(str(root / '.migration-work' / 'spring-boot-2-to-3'))}"
            ),
        )
    elif build["has_gradle"]:
        wrapper = root / "gradlew"
        if wrapper.exists() and os.access(wrapper, os.X_OK):
            add_command("Phase 2", "Review Gradle dependency alignment", f"{shlex.quote(str(wrapper))} dependencies")
        else:
            add_command("Phase 2", "Review Gradle dependency alignment", f"gradle -p {shlex.quote(str(root))} dependencies")

    if text_scan["stats"]["configuration_properties"]:
        add_command("Phase 3", "Inspect configuration-properties migration surface", search_command(r"@ConfigurationProperties|@ConstructorBinding"))
    if text_scan["stats"]["resttemplate_httpclient"]:
        add_command("Phase 3", "Inspect outbound HTTP client wiring", search_command(r"RestTemplate|HttpComponentsClientHttpRequestFactory|CloseableHttpClient|org\.apache\.http\."))
    if text_scan["stats"]["hibernate_queries"]:
        add_command("Phase 3", "Inspect Hibernate query usage", search_command(r"createQuery\("))

    if build_cmd:
        add_command("Phase 4", "Compile on the target stack", build_cmd)
    if test_cmd:
        add_command("Phase 4", "Run the test suite", test_cmd)
    add_command(
        "Phase 4",
        "Run verification with captured logs",
        (
            f"python3 {shlex.quote(str(verify_script))} {repo_arg} --stage all "
            f"--output-dir {shlex.quote(str(root / '.migration-work' / 'spring-boot-2-to-3'))}"
        ),
    )

    return commands


def recommended_references(findings: list[dict], build: dict) -> list[str]:
    refs = ["references/verification.md"]
    if build["support_status"] == "blocked_by_external_parent":
        return refs
    spring_versions = build["spring_boot_versions"]
    if spring_versions and major_version(spring_versions[0]) == 2:
        refs.append("references/spring-boot-2-to-3.md")
    if build["spring_cloud_versions"]:
        refs.append("references/spring-cloud-config-and-bootstrap.md")
    refs.append("references/java-upgrade-paths.md")
    return refs


def phase_plan(findings: list[dict], build: dict) -> list[str]:
    if build["support_status"] == "blocked_by_external_parent":
        return [
            "Phase 0: stop migration work because the effective Spring Boot version is inherited from a parent or BOM outside the current repository.",
            "Phase 1: ask the user for the external parent repository, effective POM, or a checkout that includes the version-managing build files before resuming.",
        ]
    steps = [
        "Phase 0: capture baseline build, tests, runtime entrypoint, and working tree state.",
        "Phase 1: align Java toolchain, wrapper, plugins, and CI runtime.",
        "Phase 2: align framework and library versions before code edits.",
        "Phase 3: apply source and configuration changes driven by scan findings.",
        "Phase 4: compile, test, start the application, and smoke critical flows.",
    ]
    spring_versions = build["spring_boot_versions"]
    if build["spring_cloud_versions"]:
        steps.insert(2, "Phase 1.5: align the Spring Cloud release train and config-loading strategy with the target Spring Boot version.")
    if spring_versions and major_version(spring_versions[0]) == 2:
        steps.insert(1, "Phase 0.5: move the repository to the latest Spring Boot 2.7.x patch before the 3.x upgrade.")
    return steps


def build_report(root: Path, build: dict, dep_summary: dict, findings: list[dict], text_scan: dict) -> dict:
    return {
        "repository": str(root),
        "build": build,
        "dependency_summary": dep_summary,
        "findings": findings,
        "recommended_references": recommended_references(findings, build),
        "phase_plan": phase_plan(findings, build),
        "todo_items": build_todo_items(root, build, text_scan, dep_summary),
        "command_plan": build_command_plan(root, build, text_scan),
    }


def todos_to_markdown(report: dict) -> str:
    lines = [
        "# Spring Boot 2 To 3 Migration TODO",
        "",
        f"- Repository: `{report['repository']}`",
        "",
        "## File TODO",
        "",
    ]
    if not report["todo_items"]:
        lines.extend(["No file-level migration TODO items were generated.", ""])
    else:
        for index, item in enumerate(report["todo_items"], start=1):
            lines.append(f"{index}. [{item['priority'].upper()}] {item['title']}")
            lines.append(f"   - Phase: {item['phase']}")
            lines.append(f"   - File: `{item['path']}`")
            lines.append(f"   - Action: {item['action']}")
            lines.append(f"   - Verify: {item['verify']}")
    lines.extend(
        [
            "",
            "## Suggested Commands",
            "",
        ]
    )
    for command in report["command_plan"]:
        lines.append(f"- {command['phase']}: {command['purpose']}")
        lines.append(f"  `{command['command']}`")
    return "\n".join(lines) + "\n"


def findings_to_markdown(report: dict) -> str:
    build = report["build"]
    findings = report["findings"]
    refs = report["recommended_references"]
    lines = [
        "# Spring Boot 2 To 3 Migration Scan",
        "",
        f"- Repository: `{report['repository']}`",
        f"- Maven detected: `{'yes' if build['has_maven'] else 'no'}`",
        f"- Gradle detected: `{'yes' if build['has_gradle'] else 'no'}`",
        f"- Support status: `{build['support_status']}`",
        f"- Support reason: {build['support_reason']}",
        f"- Java versions: `{', '.join(build['java_versions']) if build['java_versions'] else 'unknown'}`",
        f"- Spring Boot versions: `{', '.join(build['spring_boot_versions']) if build['spring_boot_versions'] else 'none detected'}`",
        f"- Spring Cloud versions: `{', '.join(build['spring_cloud_versions']) if build['spring_cloud_versions'] else 'none detected'}`",
        "",
        "## Findings",
        "",
    ]
    if not findings:
        lines.extend(["No migration blockers were detected by the scanner.", ""])
    else:
        for index, finding in enumerate(findings, start=1):
            lines.append(f"{index}. [{finding['severity'].upper()}] {finding['title']}")
            lines.append(f"   - {finding['detail']}")
            if finding["evidence"]:
                lines.append(f"   - Evidence: {', '.join(finding['evidence'])}")
    lines.extend(
        [
            "",
            "## Recommended References",
            "",
            *[f"- `{item}`" for item in refs],
            "",
            "## Phase Plan",
            "",
            *[f"- {item}" for item in report["phase_plan"]],
            "",
            "## File TODO",
            "",
        ]
    )
    if not report["todo_items"]:
        lines.extend(["No file-level migration TODO items were generated.", ""])
    else:
        for index, item in enumerate(report["todo_items"], start=1):
            lines.append(f"{index}. [{item['priority'].upper()}] {item['title']}")
            lines.append(f"   - Phase: {item['phase']}")
            lines.append(f"   - File: {item['path']}")
            lines.append(f"   - Action: {item['action']}")
            lines.append(f"   - Verify: {item['verify']}")
    lines.extend(
        [
            "",
            "## Suggested Commands",
            "",
        ]
    )
    for command in report["command_plan"]:
        lines.append(f"- {command['phase']}: {command['purpose']}")
        lines.append(f"  `{command['command']}`")
    lines.extend(
        [
            "",
            "## Verification",
            "",
            "- Compile on the target JDK.",
            "- Run the test suite.",
            "- Start the application and verify the Spring context loads cleanly.",
            "- Exercise one representative persistence flow and one secured flow if present.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_outputs(report: dict, markdown: str, output_dir: Path | None, output_format: str) -> None:
    todo_markdown = todos_to_markdown(report)
    todo_json = {
        "repository": report["repository"],
        "todo_items": report["todo_items"],
        "command_plan": report["command_plan"],
    }
    if not output_dir:
        if output_format in {"markdown", "both"}:
            sys.stdout.write(markdown)
        if output_format in {"json", "both"}:
            if output_format == "both":
                sys.stdout.write("\n")
            json.dump(report, sys.stdout, indent=2)
            sys.stdout.write("\n")
        return
    output_dir.mkdir(parents=True, exist_ok=True)
    if output_format in {"markdown", "both"}:
        (output_dir / "scan.md").write_text(markdown, encoding="utf-8")
        (output_dir / "todo.md").write_text(todo_markdown, encoding="utf-8")
    if output_format in {"json", "both"}:
        (output_dir / "scan.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        (output_dir / "todo.json").write_text(json.dumps(todo_json, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan a Java repository and emit migration findings.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """\
            Examples:
              scan_repo.py /repo
              scan_repo.py /repo --format both --output-dir /repo/.migration-work/spring-boot-2-to-3
            """
        ),
    )
    parser.add_argument("repo", help="Path to the target repository")
    parser.add_argument("--format", choices=["markdown", "json", "both"], default="markdown")
    parser.add_argument("--output-dir", help="Optional directory to write scan.md and scan.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.repo).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        print(f"error: repository path does not exist or is not a directory: {root}", file=sys.stderr)
        return 2

    build = detect_build(root)
    dep_summary = summarize_dependencies(build)
    text_scan = scan_text_files(root)
    findings = build_findings(root, build, text_scan, dep_summary)
    report = build_report(root, build, dep_summary, findings, text_scan)
    markdown = findings_to_markdown(report)
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else None
    write_outputs(report, markdown, output_dir, args.format)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
