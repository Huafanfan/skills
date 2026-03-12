#!/usr/bin/env python3
"""Probe Maven dependency or plugin versions until a downloadable candidate is found."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable

import scan_repo


def split_version(version: str) -> tuple[list[int], str]:
    if not version:
        return ([], "")
    numeric = [int(part) for part in re.findall(r"\d+", version)]
    qualifier_match = re.search(r"[A-Za-z].*$", version)
    qualifier = qualifier_match.group(0) if qualifier_match else ""
    return (numeric, qualifier)


def version_sort_key(version: str) -> tuple[list[int], str]:
    numeric, qualifier = split_version(version)
    return (numeric, "" if qualifier == "" else qualifier)


def rank_versions(versions: list[str], current_version: str | None) -> list[str]:
    unique = sorted(set(versions), key=version_sort_key, reverse=True)
    if not current_version:
        return unique
    current_numeric, _ = split_version(current_version)
    current_prefix = tuple(current_numeric[:2]) if current_numeric else ()
    current_major = current_numeric[0] if current_numeric else None

    def bucket(version: str) -> tuple[int, tuple[list[int], str]]:
        numeric, qualifier = split_version(version)
        prefix = tuple(numeric[:2]) if numeric else ()
        major = numeric[0] if numeric else None
        if current_prefix and prefix == current_prefix:
            return (0, version_sort_key(version))
        if current_major is not None and major == current_major + 1:
            return (1, version_sort_key(version))
        if current_major is not None and major == current_major:
            return (2, version_sort_key(version))
        return (3, version_sort_key(version))

    return [item for item in sorted(unique, key=bucket, reverse=False)]


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


def parse_settings_xml(path: Path) -> dict:
    if not path.exists():
        return {"servers": {}, "mirrors": [], "repositories": []}
    try:
        tree = ET.parse(path)
    except ET.ParseError:
        return {"servers": {}, "mirrors": [], "repositories": []}

    root = tree.getroot()
    namespace = xml_namespace(root)

    servers: dict[str, dict[str, str]] = {}
    active_profiles: set[str] = set()
    mirrors: list[dict[str, str]] = []
    repositories: list[dict[str, str]] = []

    for server in root.findall(f".//{{{namespace}}}server" if namespace else ".//server"):
        server_id = child_text(server, "id", namespace)
        if not server_id:
            continue
        servers[server_id] = {
            "username": child_text(server, "username", namespace) or "",
            "password": child_text(server, "password", namespace) or "",
        }

    for profile in root.findall(f".//{{{namespace}}}activeProfile" if namespace else ".//activeProfile"):
        if profile.text and profile.text.strip():
            active_profiles.add(profile.text.strip())

    for mirror in root.findall(f".//{{{namespace}}}mirror" if namespace else ".//mirror"):
        mirror_id = child_text(mirror, "id", namespace)
        mirror_of = child_text(mirror, "mirrorOf", namespace)
        url = child_text(mirror, "url", namespace)
        if mirror_id and url:
            mirrors.append({"id": mirror_id, "mirrorOf": mirror_of or "", "url": url})

    for profile in root.findall(f".//{{{namespace}}}profile" if namespace else ".//profile"):
        profile_id = child_text(profile, "id", namespace)
        if active_profiles and profile_id not in active_profiles:
            continue
        for repo in profile.findall(f".//{{{namespace}}}repository" if namespace else ".//repository"):
            repo_id = child_text(repo, "id", namespace)
            url = child_text(repo, "url", namespace)
            if repo_id and url:
                repositories.append({"id": repo_id, "url": url})
    return {"servers": servers, "mirrors": mirrors, "repositories": repositories}


def parse_pom_repositories(root: Path) -> list[dict[str, str]]:
    repositories: list[dict[str, str]] = []
    for pom in scan_repo.find_files(root, names=["pom.xml"]):
        try:
            tree = ET.parse(pom)
        except ET.ParseError:
            continue
        project = tree.getroot()
        namespace = xml_namespace(project)
        repo_path = f".//{{{namespace}}}repository" if namespace else ".//repository"
        for repo in project.findall(repo_path):
            repo_id = child_text(repo, "id", namespace)
            url = child_text(repo, "url", namespace)
            if repo_id and url:
                repositories.append({"id": repo_id, "url": url})
    return repositories


def build_repository_index(root: Path) -> list[dict[str, str]]:
    settings = parse_settings_xml(Path.home() / ".m2" / "settings.xml")
    repositories: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for mirror in settings["mirrors"]:
        key = (mirror["id"], mirror["url"])
        if key not in seen:
            repositories.append({"id": mirror["id"], "url": mirror["url"], "username": settings["servers"].get(mirror["id"], {}).get("username", ""), "password": settings["servers"].get(mirror["id"], {}).get("password", "")})
            seen.add(key)

    for repo in settings["repositories"] + parse_pom_repositories(root):
        key = (repo["id"], repo["url"])
        if key not in seen:
            repositories.append({"id": repo["id"], "url": repo["url"], "username": settings["servers"].get(repo["id"], {}).get("username", ""), "password": settings["servers"].get(repo["id"], {}).get("password", "")})
            seen.add(key)

    if not repositories:
        repositories.append({"id": "central", "url": "https://repo1.maven.org/maven2", "username": "", "password": ""})
    return repositories


def fetch_url(url: str, repository: dict[str, str], timeout_seconds: int) -> str | None:
    request = urllib.request.Request(url)
    username = repository.get("username") or ""
    password = repository.get("password") or ""
    if username:
        token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        request.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return response.read().decode("utf-8", errors="ignore")
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def metadata_url(repository_url: str, group_id: str, artifact_id: str) -> str:
    base = repository_url.rstrip("/")
    group_path = group_id.replace(".", "/")
    return f"{base}/{group_path}/{artifact_id}/maven-metadata.xml"


def parse_metadata_versions(text: str) -> list[str]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    namespace = xml_namespace(root)
    versions: list[str] = []
    version_path = f".//{{{namespace}}}version" if namespace else ".//version"
    for version in root.findall(version_path):
        if version.text and version.text.strip():
            versions.append(version.text.strip())
    return versions


def parse_artifact_spec(raw: str) -> dict[str, str | None]:
    current_version = None
    body = raw
    if "@" in raw:
        body, current_version = raw.rsplit("@", 1)
    parts = body.split(":")
    if len(parts) < 2:
        raise ValueError(f"invalid artifact spec: {raw}")
    packaging = "jar"
    if len(parts) >= 3 and parts[2]:
        packaging = parts[2]
    return {
        "group_id": parts[0],
        "artifact_id": parts[1],
        "packaging": packaging,
        "current_version": current_version,
        "display": raw,
    }


def default_artifacts(root: Path) -> list[dict[str, str | None]]:
    build = scan_repo.detect_build(root)
    dep_summary = scan_repo.summarize_dependencies(build)
    artifacts: list[dict[str, str | None]] = []
    if build["spring_boot_versions"]:
        current = build["spring_boot_versions"][0]
        artifacts.append(parse_artifact_spec(f"org.springframework.boot:spring-boot-starter-parent:pom@{current}"))
        artifacts.append(parse_artifact_spec(f"org.springframework.boot:spring-boot-dependencies:pom@{current}"))
    if dep_summary["uses_spring_cloud"] and build["spring_cloud_versions"]:
        current_cloud = build["spring_cloud_versions"][0]
        artifacts.append(parse_artifact_spec(f"org.springframework.cloud:spring-cloud-dependencies:pom@{current_cloud}"))
    return artifacts


def classify_probe_output(output: str) -> tuple[str, str]:
    text = output.lower()
    if "build success" in text:
        return ("downloadable", "Artifact downloaded successfully.")
    if "return code is: 403" in text or "forbidden" in text or "blocked" in text or "policy" in text or "quarantine" in text:
        return ("gateway_rejected", "Repository gateway rejected this version, likely due to policy or vulnerability enforcement.")
    if "could not find artifact" in text or "404" in text or "not found" in text:
        return ("unavailable", "Artifact version is visible or requested, but was not downloadable from the configured repositories.")
    if "unknown host" in text or "connection refused" in text or "connect timed out" in text or "unauthorized" in text or "401" in text:
        return ("environment_error", "Repository access failed because of network, authentication, or repository availability issues.")
    return ("error", "Artifact probe failed for a non-downloadability reason; inspect the probe log.")


def preferred_maven_invocation(root: Path) -> list[str]:
    wrapper = root / "mvnw"
    if wrapper.exists() and os.access(wrapper, os.X_OK):
        return [str(wrapper)]
    build = scan_repo.detect_build(root)
    return ["mvn", "-f", str(scan_repo.preferred_pom_path(root, build))]


def probe_artifact_version(root: Path, artifact: dict[str, str | None], version: str, timeout_seconds: int) -> dict:
    command = preferred_maven_invocation(root) + [
        "-q",
        "-U",
        f"-Dmaven.repo.local={tempfile.mkdtemp(prefix='probe-m2-')}",
        "org.apache.maven.plugins:maven-dependency-plugin:3.6.1:get",
        "-Dtransitive=false",
        f"-Dartifact={artifact['group_id']}:{artifact['artifact_id']}:{version}:{artifact['packaging']}",
    ]
    completed = subprocess.run(
        command,
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout_seconds,
    )
    output = completed.stdout or ""
    status, summary = classify_probe_output(output if completed.returncode else "BUILD SUCCESS")
    return {
        "version": version,
        "status": status if completed.returncode else "downloadable",
        "summary": summary if completed.returncode else "Artifact downloaded successfully.",
        "exit_code": completed.returncode,
        "command": " ".join(command),
        "output": output,
    }


def build_report(root: Path, artifacts: list[dict[str, str | None]], repositories: list[dict[str, str]], *, timeout_seconds: int, probe_all_visible: bool, max_probe_count: int) -> dict:
    report_artifacts: list[dict] = []
    for artifact in artifacts:
        visible_versions: list[str] = []
        metadata_sources: list[str] = []
        for repository in repositories:
            text = fetch_url(metadata_url(repository["url"], artifact["group_id"], artifact["artifact_id"]), repository, timeout_seconds)
            if text is None:
                continue
            versions = parse_metadata_versions(text)
            if versions:
                visible_versions.extend(versions)
                metadata_sources.append(repository["url"])
        visible_versions = sorted(set(visible_versions), key=version_sort_key, reverse=True)
        ranked_versions = rank_versions(visible_versions, artifact["current_version"])
        if not probe_all_visible:
            ranked_versions = ranked_versions[:max_probe_count]

        attempts: list[dict] = []
        first_downloadable = None
        for version in ranked_versions:
            attempt = probe_artifact_version(root, artifact, version, timeout_seconds)
            attempts.append({k: v for k, v in attempt.items() if k != "output"})
            if attempt["status"] == "downloadable":
                first_downloadable = version
                if not probe_all_visible:
                    break

        report_artifacts.append(
            {
                "group_id": artifact["group_id"],
                "artifact_id": artifact["artifact_id"],
                "packaging": artifact["packaging"],
                "current_version": artifact["current_version"],
                "metadata_sources": metadata_sources,
                "visible_versions": visible_versions,
                "probed_versions": attempts,
                "first_downloadable_version": first_downloadable,
            }
        )

    return {
        "repository": str(root),
        "artifacts": report_artifacts,
        "probe_all_visible": probe_all_visible,
        "max_probe_count": max_probe_count,
    }


def to_markdown(report: dict) -> str:
    lines = [
        "# Maven Version Probe",
        "",
        f"- Repository: `{report['repository']}`",
        f"- Probe all visible versions: `{str(report['probe_all_visible']).lower()}`",
        f"- Max probe count: `{report['max_probe_count']}`",
        "",
    ]
    for index, artifact in enumerate(report["artifacts"], start=1):
        lines.append(f"## Artifact {index}")
        lines.append("")
        lines.append(f"- Coordinate: `{artifact['group_id']}:{artifact['artifact_id']}:{artifact['packaging']}`")
        lines.append(f"- Current version: `{artifact['current_version'] or 'unknown'}`")
        lines.append(f"- Metadata sources: `{', '.join(artifact['metadata_sources']) if artifact['metadata_sources'] else 'none'}`")
        lines.append(f"- Visible versions: `{', '.join(artifact['visible_versions']) if artifact['visible_versions'] else 'none found'}`")
        lines.append(f"- First downloadable version: `{artifact['first_downloadable_version'] or 'none found'}`")
        lines.append("")
        lines.append("### Probe Attempts")
        lines.append("")
        if not artifact["probed_versions"]:
            lines.append("- No versions were probed.")
        else:
            for attempt in artifact["probed_versions"]:
                lines.append(f"- `{attempt['version']}` -> `{attempt['status']}`: {attempt['summary']}")
        lines.append("")
    return "\n".join(lines) + "\n"


def write_outputs(report: dict, output_dir: Path | None, output_format: str) -> None:
    markdown = to_markdown(report)
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
        (output_dir / "version-probe.md").write_text(markdown, encoding="utf-8")
    if output_format in {"json", "both"}:
        (output_dir / "version-probe.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect visible Maven dependency or plugin versions and probe them until a downloadable candidate is found.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """\
            Examples:
              probe_versions.py /repo --output-dir /repo/.migration-work/spring-boot-2-to-3
              probe_versions.py /repo --artifact org.springframework.boot:spring-boot-dependencies:pom@2.7.12
              probe_versions.py /repo --artifact org.springframework.cloud:spring-cloud-dependencies:pom@2021.0.5 --probe-all-visible
            """
        ),
    )
    parser.add_argument("repo", help="Path to the target repository")
    parser.add_argument("--artifact", action="append", default=[], help="Artifact spec in the form group:artifact[:packaging]@currentVersion")
    parser.add_argument("--probe-all-visible", action="store_true", help="Probe every visible version instead of stopping after the first downloadable candidate.")
    parser.add_argument("--max-probe-count", type=int, default=12, help="Maximum number of ranked versions to probe when not using --probe-all-visible.")
    parser.add_argument("--timeout-seconds", type=int, default=120, help="Timeout per metadata request and probe command.")
    parser.add_argument("--format", choices=["markdown", "json", "both"], default="markdown")
    parser.add_argument("--output-dir", help="Optional directory to write version-probe outputs")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.repo).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        print(f"error: repository path does not exist or is not a directory: {root}", file=sys.stderr)
        return 2

    try:
        artifacts = [parse_artifact_spec(item) for item in args.artifact] if args.artifact else default_artifacts(root)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not artifacts:
        print("error: no Maven artifact anchors were detected to probe", file=sys.stderr)
        return 2

    repositories = build_repository_index(root)
    report = build_report(
        root,
        artifacts,
        repositories,
        timeout_seconds=args.timeout_seconds,
        probe_all_visible=args.probe_all_visible,
        max_probe_count=args.max_probe_count,
    )
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else None
    write_outputs(report, output_dir, args.format)

    if any(item["first_downloadable_version"] for item in report["artifacts"]):
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
