#!/usr/bin/env python3
"""Run Spring Boot migration verification commands and summarize failures."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import textwrap
import time
from pathlib import Path

BLOCKED_CATEGORIES = {
    "build_environment",
    "repository_access",
    "build_wrapper",
}


def preferred_maven_command(root: Path) -> str:
    wrapper = root / "mvnw"
    return "./mvnw" if wrapper.exists() and os.access(wrapper, os.X_OK) else "mvn"


def preferred_gradle_command(root: Path) -> str:
    wrapper = root / "gradlew"
    return "./gradlew" if wrapper.exists() and os.access(wrapper, os.X_OK) else "gradle"


def detect_build_tool(root: Path) -> str | None:
    if (root / "pom.xml").exists():
        return "maven"
    if (root / "build.gradle").exists() or (root / "build.gradle.kts").exists():
        return "gradle"
    return None


def default_commands(root: Path, build_tool: str) -> dict[str, str | None]:
    if build_tool == "maven":
        mvn = preferred_maven_command(root)
        return {
            "compile": f"{mvn} -q -DskipTests compile",
            "test": f"{mvn} test",
            "startup": None,
            "smoke": None,
        }
    gradle = preferred_gradle_command(root)
    return {
        "compile": f"{gradle} compileJava",
        "test": f"{gradle} test",
        "startup": None,
        "smoke": None,
    }


def normalize_output(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def extract_key_lines(output: str, limit: int = 12) -> list[str]:
    patterns = (
        "error:",
        "[ERROR]",
        "FAILURE:",
        "BUILD FAILURE",
        "BUILD FAILED",
        "There were failing tests",
        "Tests run:",
        "APPLICATION FAILED TO START",
        "Description:",
        "Reason:",
        "Caused by:",
        "Exception:",
        "Exception in thread",
        "NoSuchBeanDefinitionException",
        "UnsatisfiedDependencyException",
        "BeanCreationException",
        "ClassNotFoundException",
        "NoClassDefFoundError",
        "Cannot resolve symbol",
        "Could not resolve",
        "Could not find artifact",
        "ConfigData",
        "BindException",
    )
    lines = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if any(pattern in line for pattern in patterns):
            lines.append(line)
        if len(lines) >= limit:
            break
    if lines:
        return lines
    fallback = [line.strip() for line in output.splitlines() if line.strip()]
    return fallback[:limit]


def classify_failure(output: str) -> tuple[str, str]:
    text = output.lower()
    if "timed out" in text:
        return ("timeout", "The verification command timed out before reaching a stable result.")
    if (
        "permission denied" in text and ("mvnw" in text or "gradlew" in text)
        or "not executable" in text and ("mvnw" in text or "gradlew" in text)
    ):
        return ("build_wrapper", "The repository wrapper exists but is not executable in the current checkout.")
    if (
        "operation not permitted" in text and (".m2/" in text or ".gradle/" in text)
        or "accessdeniedexception" in text and (".m2/" in text or ".gradle/" in text)
        or "filesystemexception" in text and (".m2/" in text or ".gradle/" in text)
    ):
        return ("build_environment", "Build cache or local tool state is not writable in the current environment.")
    if (
        "unknown host" in text
        or "connect timed out" in text
        or "connection refused" in text
        or "unauthorized" in text
        or " 401 " in text
        or "certificate" in text and "failed" in text
    ):
        return ("repository_access", "Repository access itself failed because of network, certificate, or authentication issues.")
    if (
        "could not resolve" in text
        or "could not find artifact" in text
        or "failed to read artifact descriptor" in text
        or "pluginresolutionexception" in text
    ):
        return ("dependency_resolution", "Dependency or plugin resolution failed before the code could be fully verified.")
    if (
        "package javax." in text
        or "package jakarta." in text
        or "cannot find symbol" in text and ("javax." in text or "jakarta." in text)
        or "classnotfoundexception: javax." in text
        or "noclassdeffounderror: javax." in text
        or "classnotfoundexception: jakarta." in text
        or "noclassdeffounderror: jakarta." in text
    ):
        return ("jakarta_namespace", "Missing Jakarta or legacy javax types are still blocking the migration.")
    if (
        "websecurityconfigureradapter" in text
        or "antmatchers" in text
        or "mvcmatchers" in text
        or "authorizerequests" in text
        or "securityfilterchain" in text
        or "requestmatchers" in text and "security" in text
    ):
        return ("spring_security", "Spring Security migration issues are blocking verification.")
    if (
        "nosuchbeandefinitionexception" in text
        or "unsatisfieddependencyexception" in text
        or "beancreationexception" in text
        or "application failed to start" in text
        or "failed to configure a datasource" in text
    ):
        return ("bean_loading", "Spring context or bean wiring failed during startup or tests.")
    if (
        "org.hibernate" in text
        or "hibernateexception" in text
        or "persistenceexception" in text
        or "querysyntaxexception" in text
        or "jakarta.persistence" in text
    ):
        return ("hibernate_jpa", "Hibernate or JPA compatibility issues are blocking the target stack.")
    if (
        "configdata" in text
        or "spring.config.import" in text
        or "bootstrap" in text
        or "configurationpropertiesbindexception" in text
        or "bindexception" in text
        or "failed to bind properties" in text
    ):
        return ("config_binding", "Configuration loading or property binding is failing on the migrated stack.")
    if (
        "there were failing tests" in text
        or "tests run:" in text
        or "expected:" in text and "but was:" in text
        or "assertionerror" in text
    ):
        return ("test_failure", "Compile completed, but tests still fail and need targeted fixes.")
    if "compilation failure" in text or "> task" in text and "failed" in text or "error:" in text:
        return ("compilation", "Compilation is still failing on the current migration step.")
    return ("unknown", "Verification failed, but the root cause needs manual inspection from the captured log.")


def suggested_repairs(category: str) -> list[str]:
    suggestions = {
        "dependency_resolution": [
            "Probe Maven anchor artifacts for visible and downloadable versions before declaring the repository blocked.",
            "Update the version-managing build file to the first downloadable candidate and rerun the failed stage.",
        ],
        "build_wrapper": [
            "Restore executable permissions on `mvnw` or `gradlew`, or use the system Maven or Gradle command if that is the repository standard.",
            "Fix the wrapper or build tool invocation before touching source code.",
        ],
        "build_environment": [
            "Fix local Maven or Gradle cache permissions, or rerun in an environment where the build tool can write its local state.",
            "Do not treat this as a source-code regression until the build environment is usable.",
        ],
        "repository_access": [
            "Fix repository reachability, certificate trust, or credentials before retrying dependency resolution.",
            "Do not probe alternate versions until repository access itself is healthy.",
        ],
        "jakarta_namespace": [
            "Fix the first missing `javax` or `jakarta` import and align the matching dependency.",
            "Do not rename JDK packages such as `javax.crypto` or `javax.sql`.",
        ],
        "spring_security": [
            "Migrate the first failing security config to `SecurityFilterChain` and `requestMatchers`.",
            "Rerun only the failing verification stage after the security change.",
        ],
        "bean_loading": [
            "Start from the first bean creation failure and inspect custom auto-configuration, conditions, and constructor injection.",
            "Avoid broad refactors until the first missing bean or invalid condition is fixed.",
        ],
        "hibernate_jpa": [
            "Review the first failing query, dialect, or entity mapping against Hibernate 6 behavior.",
            "Prefer a narrow persistence fix and rerun the same stage.",
        ],
        "config_binding": [
            "Inspect the first failing property name or config import and reconcile it with Boot 3 and Spring Cloud expectations.",
            "Remove bootstrap-era assumptions only after the current config path is understood.",
        ],
        "test_failure": [
            "Fix the first failing test or shared setup issue instead of editing unrelated tests.",
            "Keep compile green and rerun the same test stage before moving forward.",
        ],
        "compilation": [
            "Fix the first compile error only, then rerun compile before touching later stages.",
            "Use the scanner TODO and the first error line together to decide the next code change.",
        ],
        "timeout": [
            "Check whether the command is waiting on infrastructure, interactive input, or a hung startup path.",
            "Rerun with a higher timeout only after confirming the command should complete.",
        ],
        "unknown": [
            "Open the captured log and inspect the first real exception or error block.",
            "Do not apply broad changes until the first root cause is isolated.",
        ],
    }
    return suggestions.get(category, suggestions["unknown"])


def extract_artifact_specs(output: str) -> list[str]:
    specs: list[str] = []
    patterns = [
        r"Could not find artifact\s+([A-Za-z0-9_.\-]+):([A-Za-z0-9_.\-]+):([A-Za-z0-9_.\-]+):([A-Za-z0-9_.\-]+)",
        r"artifact\s+([A-Za-z0-9_.\-]+):([A-Za-z0-9_.\-]+):([A-Za-z0-9_.\-]+):([A-Za-z0-9_.\-]+)",
        r"for artifact\s+([A-Za-z0-9_.\-]+):([A-Za-z0-9_.\-]+):([A-Za-z0-9_.\-]+):([A-Za-z0-9_.\-]+)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, output):
            group_id, artifact_id, packaging, version = match.groups()
            spec = f"{group_id}:{artifact_id}:{packaging}@{version}"
            if spec not in specs:
                specs.append(spec)
    return specs[:6]


def run_dependency_probe(root: Path, output_dir: Path | None, output: str, timeout_seconds: int) -> dict | None:
    script = Path(__file__).resolve().parent / "probe_versions.py"
    command = ["python3", str(script), str(root), "--format", "json", "--max-probe-count", "12"]
    for artifact in extract_artifact_specs(output):
        command.extend(["--artifact", artifact])
    if output_dir:
        command[4] = "both"
        command.extend(["--output-dir", str(output_dir)])
    completed = subprocess.run(
        command,
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=min(timeout_seconds, 300),
    )
    probe_output = completed.stdout or ""
    if output_dir:
        report_path = output_dir / "version-probe.json"
        if report_path.exists():
            try:
                return json.loads(report_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return None
    try:
        return json.loads(probe_output)
    except json.JSONDecodeError:
        return None


def summarize_dependency_probe(probe_report: dict) -> tuple[str, list[str]]:
    downloadable: list[str] = []
    attempted: list[str] = []
    for artifact in probe_report.get("artifacts", []):
        coordinate = f"{artifact['group_id']}:{artifact['artifact_id']}"
        first = artifact.get("first_downloadable_version")
        if first:
            downloadable.append(f"{coordinate}:{first}")
        attempted.extend(
            [
                f"{coordinate}:{attempt['version']}={attempt['status']}"
                for attempt in artifact.get("probed_versions", [])[:5]
            ]
        )
    if downloadable:
        return (
            "Dependency resolution failed, but downloadable replacement versions were found. Update the version-managing build files to one of the probe results and rerun verification.",
            downloadable + attempted,
        )
    return (
        "Dependency resolution failed and no downloadable candidate was found among the visible versions that were probed.",
        attempted,
    )


def run_command(root: Path, command: str, timeout_seconds: int) -> tuple[int, str, float, bool]:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            shell=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout_seconds,
        )
        output = normalize_output(completed.stdout or "")
        return (completed.returncode, output, time.monotonic() - started, False)
    except subprocess.TimeoutExpired as exc:
        output = normalize_output((exc.stdout or "") + (exc.stderr or ""))
        timeout_note = f"\nTimed out after {timeout_seconds} seconds.\n"
        return (124, output + timeout_note, time.monotonic() - started, True)


def stage_sequence(stage: str, commands: dict[str, str | None]) -> list[str]:
    if stage == "all":
        sequence = ["compile", "test"]
        if commands.get("startup"):
            sequence.append("startup")
        if commands.get("smoke"):
            sequence.append("smoke")
        return sequence
    return [stage]


def build_report(
    root: Path,
    *,
    stage: str,
    build_tool: str,
    commands: dict[str, str | None],
    results: list[dict],
    stopped_after_failure: bool,
) -> dict:
    first_non_passed = next((item for item in results if item["status"] != "passed"), None)
    overall_status = "passed" if first_non_passed is None else first_non_passed["status"]
    report = {
        "repository": str(root),
        "build_tool": build_tool,
        "selected_stage": stage,
        "overall_status": overall_status,
        "stopped_after_failure": stopped_after_failure,
        "commands": commands,
        "results": results,
    }
    if first_non_passed and first_non_passed["status"] == "failed":
        report["failure_summary"] = {
            "stage": first_non_passed["stage"],
            "status": first_non_passed["status"],
            "category": first_non_passed["category"],
            "summary": first_non_passed["summary"],
            "key_lines": first_non_passed["key_lines"],
            "rerun_command": first_non_passed["command"],
            "suggested_repairs": suggested_repairs(first_non_passed["category"]),
            "log_path": first_non_passed["log_path"],
            "dependency_probe": first_non_passed.get("dependency_probe"),
        }
    if first_non_passed and first_non_passed["status"] == "blocked":
        report["verification_handoff"] = {
            "stage": first_non_passed["stage"],
            "status": first_non_passed["status"],
            "category": first_non_passed["category"],
            "summary": first_non_passed["summary"],
            "key_lines": first_non_passed["key_lines"],
            "rerun_command": first_non_passed["command"],
            "user_actions": suggested_repairs(first_non_passed["category"]),
            "log_path": first_non_passed["log_path"],
        }
    return report


def report_to_markdown(report: dict) -> str:
    lines = [
        "# Spring Boot 2 To 3 Verification",
        "",
        f"- Repository: `{report['repository']}`",
        f"- Build tool: `{report['build_tool']}`",
        f"- Selected stage: `{report['selected_stage']}`",
        f"- Overall status: `{report['overall_status']}`",
        "",
        "## Stage Results",
        "",
    ]
    for index, result in enumerate(report["results"], start=1):
        lines.append(f"{index}. [{result['status'].upper()}] {result['stage'].title()}")
        lines.append(f"   - Command: `{result['command']}`")
        lines.append(f"   - Exit code: `{result['exit_code']}`")
        lines.append(f"   - Duration: `{result['duration_seconds']:.2f}s`")
        lines.append(f"   - Log: `{result['log_path']}`")
        if result["status"] != "passed":
            lines.append(f"   - Failure category: `{result['category']}`")
            lines.append(f"   - Summary: {result['summary']}")
            if result["key_lines"]:
                lines.append(f"   - Key lines: {' | '.join(result['key_lines'])}")
            if result.get("dependency_probe"):
                downloadable = [
                    f"{item['group_id']}:{item['artifact_id']}:{item['first_downloadable_version']}"
                    for item in result["dependency_probe"].get("artifacts", [])
                    if item.get("first_downloadable_version")
                ]
                if downloadable:
                    lines.append(f"   - Downloadable candidates: {' | '.join(downloadable)}")
    if "verification_handoff" in report:
        handoff = report["verification_handoff"]
        lines.extend(
            [
                "",
                "## Verification Handoff",
                "",
                f"- Verification is blocked at stage: `{handoff['stage']}`",
                f"- Blocker category: `{handoff['category']}`",
                f"- Summary: {handoff['summary']}",
                f"- Rerun when the environment is ready: `{handoff['rerun_command']}`",
                f"- Log: `{handoff['log_path']}`",
                "",
                "## User Action Required",
                "",
            ]
        )
        for item in handoff["user_actions"]:
            lines.append(f"- {item}")
        lines.extend(
            [
                "",
                "## Migration Guidance",
                "",
                "- Continue static migration work that does not depend on this blocked verification step.",
                "- Do not declare the repository fully migrated until the user reruns verification in a permitted environment.",
            ]
        )
    elif "failure_summary" in report:
        failure = report["failure_summary"]
        lines.extend(
            [
                "",
                "## Next Repair Step",
                "",
                f"- Fix only the first failed stage: `{failure['stage']}`",
                f"- Rerun: `{failure['rerun_command']}`",
                f"- Focus: {failure['summary']}",
                f"- Log: `{failure['log_path']}`",
                "",
                "## Suggested Repairs",
                "",
            ]
        )
        for item in failure["suggested_repairs"]:
            lines.append(f"- {item}")
    else:
        lines.extend(
            [
                "",
                "## Result",
                "",
                "- Compile and test verification passed for the selected stages.",
                "- If startup or smoke checks were not configured, run them explicitly before declaring migration success.",
            ]
        )
    return "\n".join(lines) + "\n"


def failure_to_markdown(report: dict) -> str:
    failure = report["failure_summary"]
    lines = [
        "# Spring Boot 2 To 3 Failure Summary",
        "",
        f"- Repository: `{report['repository']}`",
        f"- Stage: `{failure['stage']}`",
        f"- Status: `{failure['status']}`",
        f"- Category: `{failure['category']}`",
        f"- Summary: {failure['summary']}",
        f"- Rerun command: `{failure['rerun_command']}`",
        f"- Log: `{failure['log_path']}`",
        "",
        "## Key Lines",
        "",
    ]
    if failure["key_lines"]:
        for line in failure["key_lines"]:
            lines.append(f"- {line}")
    else:
        lines.append("- No high-signal lines were extracted automatically; inspect the full log.")
    lines.extend(
        [
            "",
            "## Suggested Repairs",
            "",
        ]
    )
    for item in failure["suggested_repairs"]:
        lines.append(f"- {item}")
    if failure.get("dependency_probe"):
        lines.extend(
            [
                "",
                "## Version Probe",
                "",
            ]
        )
        for artifact in failure["dependency_probe"].get("artifacts", []):
            coordinate = f"{artifact['group_id']}:{artifact['artifact_id']}"
            lines.append(f"- `{coordinate}` visible versions: `{', '.join(artifact['visible_versions']) if artifact['visible_versions'] else 'none found'}`")
            lines.append(f"- `{coordinate}` first downloadable: `{artifact['first_downloadable_version'] or 'none found'}`")
    return "\n".join(lines) + "\n"


def handoff_to_markdown(report: dict) -> str:
    handoff = report["verification_handoff"]
    lines = [
        "# Spring Boot 2 To 3 Verification Handoff",
        "",
        f"- Repository: `{report['repository']}`",
        f"- Stage: `{handoff['stage']}`",
        f"- Status: `{handoff['status']}`",
        f"- Category: `{handoff['category']}`",
        f"- Summary: {handoff['summary']}",
        f"- Rerun command: `{handoff['rerun_command']}`",
        f"- Log: `{handoff['log_path']}`",
        "",
        "## Key Lines",
        "",
    ]
    if handoff["key_lines"]:
        for line in handoff["key_lines"]:
            lines.append(f"- {line}")
    else:
        lines.append("- No high-signal lines were extracted automatically; inspect the full log.")
    lines.extend(
        [
            "",
            "## User Action Required",
            "",
        ]
    )
    for item in handoff["user_actions"]:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## What The Agent Should Do Next",
            "",
            "- Continue static migration edits that do not require this blocked verification step.",
            "- Leave final dependency download, compile, test, or startup verification to a user-permitted environment.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_outputs(report: dict, output_dir: Path | None, output_format: str) -> None:
    verification_markdown = report_to_markdown(report)
    failure_markdown = failure_to_markdown(report) if "failure_summary" in report else None
    handoff_markdown = handoff_to_markdown(report) if "verification_handoff" in report else None
    if not output_dir:
        if output_format in {"markdown", "both"}:
            sys.stdout.write(verification_markdown)
            if failure_markdown:
                sys.stdout.write("\n")
                sys.stdout.write(failure_markdown)
            if handoff_markdown:
                sys.stdout.write("\n")
                sys.stdout.write(handoff_markdown)
        if output_format in {"json", "both"}:
            if output_format == "both":
                sys.stdout.write("\n")
            json.dump(report, sys.stdout, indent=2)
            sys.stdout.write("\n")
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    if output_format in {"markdown", "both"}:
        (output_dir / "verification.md").write_text(verification_markdown, encoding="utf-8")
        if failure_markdown:
            (output_dir / "failure-summary.md").write_text(failure_markdown, encoding="utf-8")
        if handoff_markdown:
            (output_dir / "verification-handoff.md").write_text(handoff_markdown, encoding="utf-8")
    if output_format in {"json", "both"}:
        (output_dir / "verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        if "failure_summary" in report:
            (output_dir / "failure-summary.json").write_text(
                json.dumps(report["failure_summary"], indent=2),
                encoding="utf-8",
            )
        if "verification_handoff" in report:
            (output_dir / "verification-handoff.json").write_text(
                json.dumps(report["verification_handoff"], indent=2),
                encoding="utf-8",
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run compile, test, startup, or smoke verification for a Spring Boot migration.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """\
            Examples:
              verify_repo.py /repo --stage all --output-dir /repo/.migration-work/spring-boot-2-to-3
              verify_repo.py /repo --stage startup --startup-command "./mvnw -q spring-boot:run"
              verify_repo.py /repo --stage test --test-command "./gradlew test --tests com.example.SomeTest"
            """
        ),
    )
    parser.add_argument("repo", help="Path to the target repository")
    parser.add_argument("--stage", choices=["compile", "test", "startup", "smoke", "all"], default="all")
    parser.add_argument("--build-tool", choices=["auto", "maven", "gradle"], default="auto")
    parser.add_argument("--compile-command", help="Override the compile command")
    parser.add_argument("--test-command", help="Override the test command")
    parser.add_argument("--startup-command", help="Optional startup verification command")
    parser.add_argument("--smoke-command", help="Optional smoke verification command")
    parser.add_argument("--timeout-seconds", type=int, default=900, help="Timeout per verification stage")
    parser.add_argument("--format", choices=["markdown", "json", "both"], default="markdown")
    parser.add_argument("--output-dir", help="Optional directory to write verification files")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.repo).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        print(f"error: repository path does not exist or is not a directory: {root}", file=sys.stderr)
        return 2

    build_tool = detect_build_tool(root) if args.build_tool == "auto" else args.build_tool
    if not build_tool:
        print("error: could not detect Maven or Gradle build files; pass --build-tool if needed", file=sys.stderr)
        return 2

    commands = default_commands(root, build_tool)
    overrides = {
        "compile": args.compile_command,
        "test": args.test_command,
        "startup": args.startup_command,
        "smoke": args.smoke_command,
    }
    for key, value in overrides.items():
        if value:
            commands[key] = value

    sequence = stage_sequence(args.stage, commands)
    results: list[dict] = []
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else None
    logs_dir = None
    if output_dir:
        logs_dir = output_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

    stopped_after_failure = False
    for stage in sequence:
        command = commands.get(stage)
        if not command:
            results.append(
                {
                    "stage": stage,
                    "status": "skipped",
                    "command": "",
                    "exit_code": None,
                    "duration_seconds": 0.0,
                    "log_path": "",
                    "category": "not_configured",
                    "summary": f"No command was configured for the {stage} stage.",
                    "key_lines": [],
                }
            )
            continue

        exit_code, output, duration_seconds, timed_out = run_command(root, command, args.timeout_seconds)
        status = "passed" if exit_code == 0 else "failed"
        category, summary = ("none", "Verification stage passed.")
        key_lines: list[str] = []
        dependency_probe = None
        if status != "passed":
            category, summary = classify_failure(output)
            if category in BLOCKED_CATEGORIES:
                status = "blocked"
            key_lines = extract_key_lines(output)
            if category == "dependency_resolution" and build_tool == "maven":
                dependency_probe = run_dependency_probe(root, output_dir, output, args.timeout_seconds)
                if dependency_probe:
                    summary, probe_lines = summarize_dependency_probe(dependency_probe)
                    key_lines = probe_lines[:12] or key_lines

        log_path = ""
        if logs_dir:
            log_file = logs_dir / f"{stage}.log"
            log_file.write_text(output, encoding="utf-8")
            log_path = str(log_file)

        results.append(
            {
                "stage": stage,
                "status": status,
                "command": command,
                "exit_code": exit_code,
                "duration_seconds": duration_seconds,
                "log_path": log_path,
                "category": category,
                "summary": summary,
                "key_lines": key_lines,
                "dependency_probe": dependency_probe,
            }
        )
        if status != "passed":
            stopped_after_failure = stage != sequence[-1]
            break

    report = build_report(
        root,
        stage=args.stage,
        build_tool=build_tool,
        commands=commands,
        results=results,
        stopped_after_failure=stopped_after_failure,
    )
    write_outputs(report, output_dir, args.format)
    if report["overall_status"] == "passed":
        return 0
    if report["overall_status"] == "blocked":
        return 3
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
