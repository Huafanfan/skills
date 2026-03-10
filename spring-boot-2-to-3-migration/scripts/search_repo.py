#!/usr/bin/env python3
"""Search repository text files with a portable Python fallback."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

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


def find_files(root: Path) -> list[Path]:
    matches: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in IGNORE_DIRS]
        current = Path(dirpath)
        for filename in filenames:
            path = current / filename
            if path.suffix in TEXT_SUFFIXES or filename in {
                "spring.factories",
                "org.springframework.boot.autoconfigure.AutoConfiguration.imports",
            }:
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Search a repository for a regular expression.")
    parser.add_argument("repo", help="Path to the target repository")
    parser.add_argument("--pattern", required=True, help="Python regular expression to search for")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.repo).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        print(f"error: repository path does not exist or is not a directory: {root}", file=sys.stderr)
        return 2

    try:
        regex = re.compile(args.pattern)
    except re.error as exc:
        print(f"error: invalid regex: {exc}", file=sys.stderr)
        return 2

    matched = False
    for path in find_files(root):
        lines = read_text(path).splitlines()
        for index, line in enumerate(lines, start=1):
            if regex.search(line):
                matched = True
                print(f"{rel(path, root)}:{index}:{line}")
    return 0 if matched else 1


if __name__ == "__main__":
    raise SystemExit(main())
