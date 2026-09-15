#!/usr/bin/env python3
# Copyright 2026 Thallium Solutions di Busconi Alessandro.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path


LIB_ROOT = Path(__file__).resolve().parents[1]
SSH_LIB_ROOT = LIB_ROOT.parent / "lam-ssh"
COMPILER = "lamc"
MIN_COMPILER_VERSION = (1, 16, 0)
PACKAGE_PATH = Path("@lam") / "sftp"
SSH_PACKAGE_PATH = Path("@lam") / "ssh"


def _check_compiler() -> bool:
    try:
        proc = subprocess.run(
            [COMPILER, "version"], capture_output=True, text=True, timeout=10
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        print(f"Error: unable to run {COMPILER}: {exc}", file=sys.stderr)
        return False
    if proc.returncode != 0:
        print(f"Error: unable to check {COMPILER} version: {proc.stderr.strip()}", file=sys.stderr)
        return False
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", proc.stdout.strip())
    if not match:
        print(f"Error: invalid {COMPILER} version: {proc.stdout.strip()!r}", file=sys.stderr)
        return False
    version = tuple(int(part) for part in match.groups())
    if version < MIN_COMPILER_VERSION:
        required = ".".join(str(part) for part in MIN_COMPILER_VERSION)
        print(f"Error: {COMPILER} {proc.stdout.strip()} is incompatible; >= {required} is required.", file=sys.stderr)
        return False
    return True


def _expectations(source: str) -> list[str]:
    return [
        match.group(1).strip()
        for line in source.splitlines()
        if (match := re.match(r"^\s*#\s*expect:\s*(.*)$", line))
    ]


def _stage_packages(extlibs: Path) -> None:
    for source, package_path in (
        (LIB_ROOT, PACKAGE_PATH),
        (SSH_LIB_ROOT, SSH_PACKAGE_PATH),
    ):
        package = extlibs / package_path
        package.parent.mkdir(parents=True, exist_ok=True)
        package.symlink_to(source, target_is_directory=True)


def _run_case(path: Path, race: bool) -> tuple[bool, str]:
    expected = _expectations(path.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="lamsftp_test_") as tmp:
        root = Path(tmp)
        extlibs = root / "extlibs"
        _stage_packages(extlibs)
        binary = root / "test_binary"
        command = [
            COMPILER,
            str(path),
            "--extlibs",
            str(extlibs),
            "--no-cache",
            "-o",
            str(binary),
        ]
        if race:
            command.append("--go-race")
        compile_proc = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=240,
        )
        if compile_proc.returncode != 0:
            return False, "COMPILE FAIL:\n" + compile_proc.stderr
        run_proc = subprocess.run(
            [str(binary)], cwd=root, capture_output=True, text=True, timeout=60
        )
        if run_proc.returncode != 0:
            return False, f"RUN FAIL ({run_proc.returncode}):\n{run_proc.stderr}"
        actual = run_proc.stdout.rstrip("\n")
        expected_text = "\n".join(expected).strip()
        if expected and actual != expected_text:
            return False, f"OUTPUT MISMATCH:\n  expected: {expected_text!r}\n  actual:   {actual!r}"
        return True, "ok"


def main() -> None:
    parser = argparse.ArgumentParser(description="@lam/sftp package tests")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--race", action="store_true", help="build tests with Go's race detector")
    args = parser.parse_args()
    if not _check_compiler():
        raise SystemExit(1)
    if not (SSH_LIB_ROOT / "lamlib.toml").is_file():
        print(
            f"Error: local @lam/ssh checkout is required at {SSH_LIB_ROOT}",
            file=sys.stderr,
        )
        raise SystemExit(1)

    cases = sorted((LIB_ROOT / "tests").glob("offline_*.lam"))
    failures: list[tuple[Path, str]] = []
    print(f"Running {len(cases)} @lam/sftp test(s)...\n")
    for case in cases:
        ok, message = _run_case(case, args.race)
        relative = case.relative_to(LIB_ROOT)
        print(f"  {'PASS' if ok else 'FAIL'}  {relative}")
        if not ok:
            failures.append((relative, message))
            if args.verbose:
                for line in message.splitlines():
                    print(f"        {line}")

    print(f"\n@lam/sftp results: {len(cases) - len(failures)} passed, {len(failures)} failed, {len(cases)} total")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
