#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shlex
import shutil
import tarfile
import tempfile
import tomllib
import zipfile
from pathlib import Path


FORBIDDEN_RUNTIME_NAMES = {
    ".env",
    "browser.json",
    "checkout.json",
    "config.json",
    "heartbeat.json",
    "request-budget.json",
}
FORBIDDEN_RUNTIME_DIRECTORIES = {"browser-profile", "logs", "state"}
FORBIDDEN_SECRET_SUFFIXES = {".cookie", ".secret", ".token"}
REQUIRED_AUTHORIZATION_FIELDS = {
    "approved_at",
    "scope",
    "request_limit_scope",
    "max_requests_per_ip_per_second",
}
OPTIONAL_AUTHORIZATION_FIELDS = {"authorization_reference", "document_sha256"}
REQUIRED_AUTHORIZATION_SCOPES = {
    "automated_availability_query",
    "automated_seat_selection",
    "voucher_submission",
    "private_beta_distribution",
}


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_stage(stage: Path) -> None:
    """Reject local runtime state and developer-specific paths before archiving."""

    problems: list[str] = []
    for item in stage.rglob("*"):
        relative = item.relative_to(stage)
        if item.is_dir():
            if item.name in FORBIDDEN_RUNTIME_DIRECTORIES:
                problems.append(f"forbidden runtime directory: {relative}")
            continue
        if item.name in FORBIDDEN_RUNTIME_NAMES or item.suffix.lower() in FORBIDDEN_SECRET_SUFFIXES:
            problems.append(f"forbidden runtime file: {relative}")
            continue
        if item.stat().st_size > 2 * 1024 * 1024:
            continue
        try:
            text = item.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        mac_user_prefix = "/" + "Users" + "/"
        if mac_user_prefix in text or re.search(r"[A-Za-z]:\\Users\\[^\\\r\n]+", text):
            problems.append(f"developer-specific absolute path: {relative}")
    if problems:
        raise SystemExit("release stage privacy check failed: " + "; ".join(problems))


def _literal_python_string(expression: ast.expr) -> str | None:
    if isinstance(expression, ast.Constant) and isinstance(expression.value, str):
        return expression.value
    return None


def _python_version_assignments(source: str) -> list[str | None]:
    """Accept only a docstring and one literal __version__ assignment without importing it."""

    try:
        module = ast.parse(source)
    except SyntaxError:
        return [None]
    if len(module.body) != 2:
        return [None]
    docstring, assignment = module.body
    if not (
        isinstance(docstring, ast.Expr)
        and isinstance(docstring.value, ast.Constant)
        and isinstance(docstring.value.value, str)
        and isinstance(assignment, ast.Assign)
        and len(assignment.targets) == 1
        and isinstance(assignment.targets[0], ast.Name)
        and assignment.targets[0].id == "__version__"
    ):
        return [None]
    return [_literal_python_string(assignment.value)]


def _shell_statements(source: str) -> list[str]:
    """Split shell source on executable command boundaries without executing it."""

    statements: list[str] = []
    current: list[str] = []
    quote: str | None = None
    escaped = False
    comment = False
    for character in source:
        if comment:
            if character == "\n":
                comment = False
                statements.append("".join(current))
                current = []
            continue
        if escaped:
            current.append(character)
            escaped = False
            continue
        if quote:
            current.append(character)
            if character == "\\" and quote == '"':
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in ("'", '"'):
            quote = character
            current.append(character)
        elif character == "#":
            comment = True
        elif character in (";", "\n"):
            statements.append("".join(current))
            current = []
        else:
            current.append(character)
    if current:
        statements.append("".join(current))
    return statements


def _shell_version_assignments(source: str) -> list[str | None]:
    """Collect literal executable APP_VERSION assignments using shell tokenization only."""

    assignments: list[str | None] = []
    declaration_builtins = {"export", "readonly", "typeset", "declare", "local"}
    dynamic_commands = {".", "builtin", "command", "eval", "read", "source", "vared"}
    command_boundaries = {"&&", "||", "|", "&", "if", "then", "elif", "while", "until", "do"}
    target_write = re.compile(r"^APP_VERSION(?:=|\+=|-=|\*=|/=|%=|\?=|:=|\[[^]]*\][+\-*/%]?=|$)")
    for statement in _shell_statements(source):
        try:
            tokens = shlex.split(statement, posix=True, comments=True)
        except ValueError:
            if re.search(r"(?<![A-Za-z0-9_])APP_VERSION=", statement):
                assignments.append(None)
            continue
        if not tokens:
            continue
        candidates: list[str | None] = []
        index = 0
        while index < len(tokens) and target_write.match(tokens[index]):
            candidates.append(tokens[index] if tokens[index].startswith("APP_VERSION=") else None)
            index += 1
        command_indexes = {index} if index < len(tokens) else set()
        command_indexes.update(
            token_index + 1
            for token_index, token in enumerate(tokens[:-1])
            if token in command_boundaries
        )
        if any(tokens[token_index] in dynamic_commands for token_index in command_indexes):
            assignments.append(None)
        if tokens[0] in declaration_builtins:
            for token in tokens[1:]:
                if target_write.match(token):
                    candidates.append(token if token.startswith("APP_VERSION=") else None)
        for candidate in candidates:
            if candidate is None:
                assignments.append(None)
                continue
            value = candidate.removeprefix("APP_VERSION=")
            assignments.append(value if value and not any(marker in value for marker in ("$", "`", "$((")) else None)
    return assignments


def _powershell_statement_tokens(source: str, start: int) -> list[str]:
    """Tokenize one PowerShell pipeline segment without evaluating it."""

    tokens: list[str] = []
    current: list[str] = []
    quote: str | None = None
    index = start
    while index < len(source):
        character = source[index]
        if quote:
            if quote == "'" and character == "'" and index + 1 < len(source) and source[index + 1] == "'":
                current.append("'")
                index += 2
                continue
            if quote == '"' and character == "`" and index + 1 < len(source):
                current.append(source[index + 1])
                index += 2
                continue
            if character == quote:
                quote = None
            else:
                current.append(character)
            index += 1
            continue
        if character in ("'", '"'):
            quote = character
        elif character == "#" or character in (";", "\n", "|"):
            break
        elif character.isspace() or character == ",":
            if current:
                tokens.append("".join(current))
                current = []
        else:
            current.append(character)
        index += 1
    if current:
        tokens.append("".join(current))
    return tokens


def _powershell_mutates_version_provider(source: str, start: int) -> bool:
    """Return whether a provider mutation command targets the AppVersion variable."""

    tokens = _powershell_statement_tokens(source, start)
    if len(tokens) < 2:
        return False
    arguments = tokens[1:]
    path_arguments: list[str] = []
    for index, argument in enumerate(arguments[:-1]):
        if argument.casefold() in {"-path", "-literalpath"}:
            path_arguments.append(arguments[index + 1])
    if not path_arguments:
        index = 0
        while index < len(arguments):
            argument = arguments[index]
            if argument.casefold() == "-value":
                index += 2
                continue
            if not argument.startswith("-"):
                path_arguments.append(argument)
                break
            index += 1
    provider_target = re.compile(
        r"^variable:[\\/]?\$?\{?(?:(?:global|local|script|private|using|\d+):)?appversion\}?$",
        re.IGNORECASE,
    )
    return any(provider_target.fullmatch(path) for path in path_arguments)


def _powershell_version_assignments(source: str) -> list[str | None]:
    """Collect literal $AppVersion assignments outside comments and string literals."""

    assignments: list[str | None] = []
    dynamic_command = re.compile(
        r"(?:"
        r"Invoke-Expression|Invoke-Command|Set-Variable|New-Variable|Clear-Variable|Remove-Variable|"
        r"Set-Alias|New-Alias|Import-Alias|iex|icm|sv|nv|clv|rv"
        r")(?![A-Za-z0-9_-])",
        re.IGNORECASE,
    )
    dynamic_scriptblock = re.compile(
        r"\[(?:System\.Management\.Automation\.)?ScriptBlock\]\s*::\s*Create\s*\(",
        re.IGNORECASE,
    )
    provider_mutation_command = re.compile(
        r"(?:Set-Item|Set-Content|si|sc)(?![A-Za-z0-9_-])",
        re.IGNORECASE,
    )
    target_write = re.compile(
        r"(?P<target>\$(?:"
        r"\{(?:(?:global|local|script|private|using|\d+):)?AppVersion\}|"
        r"(?:(?:global|local|script|private|using|\d+):)?AppVersion(?![A-Za-z0-9_])"
        r"))\s*(?P<operator>\+\+|--|\?\?=|\+=|-=|\*=|/=|%=|=)\s*",
        re.IGNORECASE,
    )
    index = 0
    quote: str | None = None
    while index < len(source):
        character = source[index]
        if quote:
            if quote == "'" and character == "'" and index + 1 < len(source) and source[index + 1] == "'":
                index += 2
                continue
            if quote == '"' and character == "`" and index + 1 < len(source):
                index += 2
                continue
            if character == quote:
                quote = None
            index += 1
            continue
        if character in ("'", '"'):
            quote = character
            index += 1
            continue
        if source.startswith("<#", index):
            block_comment_end = source.find("#>", index + 2)
            index = len(source) if block_comment_end == -1 else block_comment_end + 2
            continue
        if character == "#":
            newline = source.find("\n", index)
            index = len(source) if newline == -1 else newline + 1
            continue
        dynamic_match = dynamic_command.match(source, index) or dynamic_scriptblock.match(source, index)
        if dynamic_match and not (
            index and (source[index - 1].isalnum() or source[index - 1] in "_-$")
        ):
            assignments.append(None)
            index = dynamic_match.end()
            continue
        provider_match = provider_mutation_command.match(source, index)
        if (
            provider_match
            and not (index and (source[index - 1].isalnum() or source[index - 1] in "_-$"))
            and _powershell_mutates_version_provider(source, index)
        ):
            assignments.append(None)
            index = provider_match.end()
            continue
        match = target_write.match(source, index)
        if not match or (index and (source[index - 1].isalnum() or source[index - 1] in "_$")):
            index += 1
            continue
        target = match.group("target")
        operator = match.group("operator")
        value_start = match.end()
        if target.casefold() != "$appversion" or operator != "=":
            assignments.append(None)
            index = value_start
            continue
        if value_start >= len(source) or source[value_start] not in ("'", '"'):
            assignments.append(None)
            index = value_start
            continue
        value_quote = source[value_start]
        cursor = value_start + 1
        value: list[str] = []
        literal = True
        while cursor < len(source):
            current = source[cursor]
            if value_quote == "'" and current == "'" and cursor + 1 < len(source) and source[cursor + 1] == "'":
                value.append("'")
                cursor += 2
                continue
            if value_quote == '"' and current == "`" and cursor + 1 < len(source):
                literal = False
                cursor += 2
                continue
            if current == value_quote:
                break
            if value_quote == '"' and current == "$":
                literal = False
            value.append(current)
            cursor += 1
        if cursor >= len(source):
            assignments.append(None)
            index = len(source)
            continue
        boundary_candidates = [
            position
            for position in (source.find(";", cursor + 1), source.find("\n", cursor + 1))
            if position != -1
        ]
        statement_end = min(boundary_candidates) if boundary_candidates else len(source)
        trailing_expression = source[cursor + 1 : statement_end].split("#", 1)[0].strip()
        assignments.append("".join(value) if literal and not trailing_expression else None)
        index = cursor + 1
    return assignments


def validate_version_alignment(root: Path, version: str) -> None:
    """Require every release-facing version source to match the requested version."""

    project_version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    runtime = (root / "runtime" / "prickly_imax_helper" / "__init__.py").read_text(encoding="utf-8")
    runtime_versions = _python_version_assignments(runtime)
    mac_installer = (root / "scripts" / "Install.command").read_text(encoding="utf-8")
    mac_versions = _shell_version_assignments(mac_installer)
    windows_installer = (root / "scripts" / "Install.ps1").read_text(encoding="utf-8-sig")
    windows_versions = _powershell_version_assignments(windows_installer)
    lock_packages = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8")).get("package", [])
    lock_project_entries = [
        package for package in lock_packages if package.get("name") == "prickly-imax-helper"
    ]
    lock_versions = [package.get("version") for package in lock_project_entries]

    sources = {
        "pyproject.toml": [project_version],
        "runtime __version__": runtime_versions,
        "Install.command APP_VERSION": mac_versions,
        "Install.ps1 AppVersion": windows_versions,
        "uv.lock project version": lock_versions,
    }
    mismatches = [f"{source}={actual!r}" for source, actual in sources.items() if actual != [version]]
    if len(lock_project_entries) == 1 and lock_project_entries[0].get("source", {}).get("editable") != ".":
        mismatches.append(f"uv.lock project source={lock_project_entries[0].get('source')!r}")
    if mismatches:
        raise SystemExit(
            f"release version alignment failed for {version}: " + "; ".join(mismatches)
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("dist"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    validate_version_alignment(root, args.version)
    authorization = json.loads(args.authorization.read_text(encoding="utf-8"))
    if not isinstance(authorization, dict):
        raise SystemExit("authorization metadata must be a JSON object")
    allowed_fields = REQUIRED_AUTHORIZATION_FIELDS | OPTIONAL_AUTHORIZATION_FIELDS
    unknown = sorted(set(authorization) - allowed_fields)
    if unknown:
        raise SystemExit("authorization metadata contains non-public or unknown fields: " + ", ".join(unknown))
    missing = sorted(REQUIRED_AUTHORIZATION_FIELDS - authorization.keys())
    if missing:
        raise SystemExit("authorization metadata missing: " + ", ".join(missing))
    if authorization["request_limit_scope"] != "public_ip":
        raise SystemExit("request_limit_scope must be public_ip")
    if isinstance(authorization["max_requests_per_ip_per_second"], bool):
        raise SystemExit("max_requests_per_ip_per_second must be numeric")
    try:
        request_rate = float(authorization["max_requests_per_ip_per_second"])
    except (TypeError, ValueError) as exc:
        raise SystemExit("max_requests_per_ip_per_second must be numeric") from exc
    if not 0 < request_rate <= 1.0:
        raise SystemExit("release metadata exceeds the approved request rate")
    scopes = authorization["scope"]
    if not isinstance(scopes, list) or not all(isinstance(scope, str) for scope in scopes):
        raise SystemExit("authorization scope must be a JSON string list")
    scope_set = set(scopes)
    missing_scopes = sorted(REQUIRED_AUTHORIZATION_SCOPES - scope_set)
    if missing_scopes:
        raise SystemExit("authorization scope missing: " + ", ".join(missing_scopes))
    extra_scopes = sorted(scope_set - REQUIRED_AUTHORIZATION_SCOPES)
    if extra_scopes:
        raise SystemExit("authorization scope contains unsupported capabilities: " + ", ".join(extra_scopes))
    document_sha256 = authorization.get("document_sha256")
    authorization_reference = authorization.get("authorization_reference")
    if not document_sha256 and not authorization_reference:
        raise SystemExit("authorization_reference or document_sha256 is required")
    if document_sha256 and (not isinstance(document_sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", document_sha256)):
        raise SystemExit("document_sha256 must be a 64-character hexadecimal SHA-256 digest")
    if authorization_reference:
        if not isinstance(authorization_reference, str):
            raise SystemExit("authorization_reference must be text")
        reference = authorization_reference.strip()
        if not 3 <= len(reference) <= 200 or any(ord(character) < 32 or ord(character) == 127 for character in reference):
            raise SystemExit("authorization_reference must be a single public-safe line of 3-200 characters")
        placeholder_tokens = ("OPTIONAL", "REPLACE", "PLACEHOLDER", "CHANGEME", "TODO")
        if any(token in reference.upper() for token in placeholder_tokens):
            raise SystemExit("authorization_reference is still a placeholder")
    approved_at = authorization["approved_at"]
    if not isinstance(approved_at, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", approved_at):
        raise SystemExit("approved_at must be an ISO date (YYYY-MM-DD)")
    try:
        from datetime import date

        date.fromisoformat(approved_at)
    except ValueError as exc:
        raise SystemExit("approved_at must be an ISO date (YYYY-MM-DD)") from exc

    public_authorization = {
        "approved_at": approved_at,
        "scope": sorted(REQUIRED_AUTHORIZATION_SCOPES),
        "request_limit_scope": "public_ip",
        "max_requests_per_ip_per_second": request_rate,
    }
    if document_sha256:
        public_authorization["document_sha256"] = str(document_sha256).lower()
    if authorization_reference:
        public_authorization["authorization_reference"] = reference

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"prickly-imax-helper-{args.version}.tar.gz"
    windows_archive = output / f"prickly-imax-helper-{args.version}.zip"
    with tempfile.TemporaryDirectory() as temporary:
        stage = Path(temporary) / f"prickly-imax-helper-{args.version}"
        stage.mkdir()
        for name in ("runtime", "scripts", "pyproject.toml", "uv.lock", "README.md", "LICENSE"):
            source = root / name
            destination = stage / name
            if source.is_dir():
                shutil.copytree(
                    source,
                    destination,
                    ignore=shutil.ignore_patterns(
                        "__pycache__",
                        "*.pyc",
                        "*.egg-info",
                        "cgv_checkout_no_submit_probe.py",
                    ),
                )
            else:
                shutil.copy2(source, destination)
        (stage / "AUTHORIZATION.json").write_text(
            json.dumps(public_authorization, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        validate_stage(stage)
        for command in (stage / "scripts" / "Install.command", stage / "scripts" / "Update.command", stage / "scripts" / "Uninstall.command"):
            os.chmod(command, 0o755)
        with tarfile.open(archive, "w:gz") as bundle:
            bundle.add(stage, arcname=stage.name)
        with zipfile.ZipFile(windows_archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for item in stage.rglob("*"):
                if item.is_file():
                    bundle.write(item, arcname=str(Path(stage.name) / item.relative_to(stage)))
    artifacts = []
    for operating_system, artifact in (("macos", archive), ("windows", windows_archive)):
        digest = hash_file(artifact)
        checksum = artifact.with_suffix(artifact.suffix + ".sha256")
        checksum.write_text(f"{digest}  {artifact.name}\n", encoding="utf-8")
        artifacts.append(
            {
                "operating_system": operating_system,
                "archive": str(artifact),
                "sha256": digest,
                "checksum": str(checksum),
            }
        )
    mac = artifacts[0]
    print(json.dumps({**mac, "artifacts": artifacts}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
