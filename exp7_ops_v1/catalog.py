"""Pin the existing live model catalog without changing scientific CLI arguments.

Installation is offline and never activates PATH. The generated codex shim
adds only a startup model_catalog_json override, preserves stdin/environment,
and fails closed on changed binary metadata, catalog, manifest, or this module.
No HTTP errors are filtered. Authentication and generation remain unchanged.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile


VERSION = "2"
EXPECTED_VERSION = "codex-cli 0.159.0-alpha.3"
SOURCE_ROOT = "https://github.com/openai/codex/blob/rust-v0.159.0-alpha.3/codex-rs/"


class CatalogError(RuntimeError):
    pass


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def regular(path):
    path = Path(path).absolute()
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise CatalogError("Linked runtime input is not permitted")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise CatalogError("Runtime input must be a regular file with one link")
    return path


def signature(path):
    info = regular(path).stat()
    return {"device": info.st_dev, "inode": info.st_ino, "size": info.st_size,
            "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns}


def write_new(path, content, mode=0o600):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, "wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def prepare_install(cache_path, install_dir, real_binary, allowed_models):
    """Capture exact cached model objects; no auth reads, network, or inference."""
    cache_path, real_binary = regular(cache_path), regular(real_binary)
    cache_bytes = cache_path.read_bytes()
    cache = json.loads(cache_bytes)
    models = cache.get("models")
    if not isinstance(models, list) or not models or any(not isinstance(m, dict) for m in models):
        raise CatalogError("The existing live cache must contain model objects")
    slugs = [m.get("slug") for m in models]
    if any(not isinstance(s, str) or not s for s in slugs) or len(set(slugs)) != len(slugs):
        raise CatalogError("Live catalog has missing or duplicate model identifiers")
    allowed_models = sorted(set(allowed_models))
    if not allowed_models or not set(allowed_models) <= set(slugs):
        raise CatalogError("Every authorized model must exist in the captured live catalog")
    if cache.get("client_version") != "0.159.0":
        raise CatalogError("Live cache belongs to another CLI version")
    version = subprocess.check_output([str(real_binary), "--version"], text=True, timeout=15).strip()
    if version != EXPECTED_VERSION:
        raise CatalogError("Unexpected Codex CLI version")
    before = signature(real_binary)
    binary_sha = sha(real_binary)
    if signature(real_binary) != before:
        raise CatalogError("CLI binary changed while hashing")
    install = Path(install_dir).absolute()
    if any(p.is_symlink() for p in (install, *install.parents)):
        raise CatalogError("Installation path contains a symlink")
    install.mkdir(parents=True, exist_ok=False, mode=0o700)
    (install / "bin").mkdir(mode=0o700)
    catalog = install / "models.json"
    write_new(catalog, encoded({"models": models}) + b"\n")
    runtime = Path(__file__).absolute()
    manifest = {"schema_version": 1, "kind": "exp7-static-live-catalog", "shim_version": VERSION,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "runtime_path": str(runtime), "runtime_sha256": sha(regular(runtime)),
                "real_binary": str(real_binary), "binary_sha256": binary_sha,
                "binary_signature": before, "cli_version": version,
                "catalog_path": str(catalog), "catalog_sha256": sha(catalog),
                "source_cache_sha256": hashlib.sha256(cache_bytes).hexdigest(),
                "source_cache_fetched_at": cache.get("fetched_at"),
                "model_count": len(models), "allowed_models": allowed_models,
                "invocation_audit": str(install / "invocations.private.jsonl"),
                "policy": "Exact cached models; only startup catalog override; never suppress diagnostics",
                "source_evidence": [SOURCE_ROOT+"core/src/config/mod.rs#L4056",
                                    SOURCE_ROOT+"model-provider/src/provider.rs#L544",
                                    SOURCE_ROOT+"models-manager/src/manager.rs#L647",
                                    SOURCE_ROOT+"models-manager/src/lib.rs#L18",
                                    SOURCE_ROOT+"protocol/src/openai_models.rs#L864",
                                    SOURCE_ROOT+"cli/src/main.rs#L1134",
                                    SOURCE_ROOT+"exec/src/lib.rs#L334"],
                "binary_verification": "Full SHA256 at install/launch; every invocation checks device/inode/size/mtime/ctime"}
    manifest_path = install / "manifest.private.json"
    write_new(manifest_path, encoded(manifest) + b"\n")
    manifest_sha = sha(manifest_path)
    # Absolute interpreter/runtime paths avoid dependence on the worker cwd or
    # PYTHONPATH. The scientific transport still invokes its original 'codex'.
    shim = (f"#!{sys.executable}\n"
            "import hashlib, pathlib, runpy, sys\n"
            f"runtime = pathlib.Path({str(runtime)!r})\n"
            f"if hashlib.sha256(runtime.read_bytes()).hexdigest() != {manifest['runtime_sha256']!r}:\n"
            "    sys.stderr.write('Pinned catalog runtime changed; no CLI request dispatched\\n')\n"
            "    raise SystemExit(78)\n"
            "entry = runpy.run_path(str(runtime), run_name='_pinned_catalog_runtime')\n"
            f"raise SystemExit(entry['shim_main']({str(manifest_path)!r}, {manifest_sha!r}, sys.argv[1:]))\n")
    shim_path = install / "bin" / "codex"
    write_new(shim_path, shim.encode(), 0o700)
    return {"manifest": str(manifest_path), "manifest_sha256": manifest_sha,
            "shim": str(shim_path), "shim_sha256": sha(shim_path),
            "catalog_sha256": manifest["catalog_sha256"], "binary_sha256": binary_sha,
            "model_count": len(models), "allowed_models": allowed_models,
            "path_activated": False, "new_model_calls": 0}


def verify_install(manifest_path, expected_manifest_sha256, *, rehash_binary=False):
    path = regular(manifest_path)
    if sha(path) != expected_manifest_sha256:
        raise CatalogError("Pinned catalog manifest changed")
    manifest = json.loads(path.read_text())
    if manifest.get("schema_version") != 1 or manifest.get("kind") != "exp7-static-live-catalog":
        raise CatalogError("Unknown catalog installation")
    for prefix, field in (("runtime", "runtime_path"), ("catalog", "catalog_path")):
        if sha(regular(manifest[field])) != manifest[prefix+"_sha256"]:
            raise CatalogError("Pinned " + prefix + " changed")
    binary = regular(manifest["real_binary"])
    if signature(binary) != manifest["binary_signature"]:
        raise CatalogError("CLI binary metadata changed; revalidation is required")
    if rehash_binary and sha(binary) != manifest["binary_sha256"]:
        raise CatalogError("Pinned CLI binary hash changed")
    return manifest


def command_for(manifest, argv):
    """Preserve every original argument, adding exactly one top-level config."""
    argv = list(argv)
    binary = manifest["real_binary"]
    if argv in (["--version"], ["-V"]):
        return [binary, *argv], False
    if not argv or argv[0] != "exec" or (len(argv) > 1 and argv[1] in ("fork", "review")):
        raise CatalogError("Shim is restricted to the frozen exec/resume transport and --version")
    if any("model_catalog_json" in item for item in argv):
        raise CatalogError("An additional catalog override is forbidden")
    if not {"--ignore-user-config", "--ignore-rules", "--json"} <= set(argv) or argv[-1] != "-":
        raise CatalogError("Expected the original isolated stdin-based scientific command")
    if argv.count("--model") != 1:
        raise CatalogError("Exactly one explicit model is required")
    index = argv.index("--model")
    if index+1 >= len(argv) or argv[index+1] not in manifest["allowed_models"]:
        raise CatalogError("Model is outside this installation's authorized catalog scope")
    # JSON basic-string escaping is also valid TOML for a filesystem path.
    override = "model_catalog_json=" + json.dumps(manifest["catalog_path"], ensure_ascii=False)
    return [binary, "-c", override, *argv], True


def audit_invocation(manifest, manifest_sha, argv, effective):
    model = argv[argv.index("--model")+1]
    record = {"at": datetime.now(timezone.utc).isoformat(), "pid": os.getpid(),
              "action": "exec_resume" if len(argv) > 1 and argv[1] == "resume" else "exec",
              "model": model, "manifest_sha256": manifest_sha,
              "catalog_sha256": manifest["catalog_sha256"], "binary_sha256": manifest["binary_sha256"],
              "original_argv_sha256": hashlib.sha256(encoded(["codex", *argv])).hexdigest(),
              "effective_argv_sha256": hashlib.sha256(encoded(effective)).hexdigest(),
              "added_config_key": "model_catalog_json",
              "stdin_and_environment_logged": False}
    path = Path(manifest["invocation_audit"])
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise CatalogError("Invocation audit path must not contain links")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "ab", buffering=0) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise CatalogError("Invocation audit must be a regular unlinked file")
        fcntl.flock(stream, fcntl.LOCK_EX)
        stream.write(encoded(record)+b"\n")
        os.fsync(stream.fileno())


def shim_main(manifest_path, manifest_sha, argv):
    try:
        manifest = verify_install(manifest_path, manifest_sha)
        effective, audited = command_for(manifest, argv)
        if audited:
            audit_invocation(manifest, manifest_sha, argv, effective)
        os.execv(manifest["real_binary"], effective)
    except Exception as exc:
        # No external error strings, arguments, stdin, or credentials in logs.
        sys.stderr.write("Pinned catalog wrapper blocked before CLI dispatch: " + type(exc).__name__ + "\n")
        return 78


def validate_rendered_catalog(expected, actual):
    """Allow only the documented duplicate legacy field, verifying its value.

    In this exact CLI version ModelsResponse serializes base_instructions as
    a literal copy of model_messages.instructions_template. The file cache
    serializes ModelInfo directly and therefore omits that duplicate field.
    No original field or instruction is dropped, normalized, or replaced.
    """
    if actual == expected:
        return 0
    if not isinstance(actual, dict) or set(actual) != {"models"} or not isinstance(actual["models"], list):
        raise CatalogError("Rendered catalog structure differs")
    if len(actual["models"]) != len(expected["models"]):
        raise CatalogError("Rendered catalog model count differs")
    rendered = json.loads(json.dumps(actual))
    mirrored = 0
    for original, model in zip(expected["models"], rendered["models"]):
        if "base_instructions" not in original and "base_instructions" in model:
            template = (original.get("model_messages") or {}).get("instructions_template")
            if not isinstance(template, str) or model["base_instructions"] != template:
                raise CatalogError("Derived legacy instruction field differs from the original template")
            del model["base_instructions"]
            mirrored += 1
    if rendered != expected:
        raise CatalogError("Original model catalog metadata differs")
    return mirrored


def validate_debug(manifest_path, manifest_sha):
    """Non-inference validation against the installed CLI with an empty CLI home."""
    manifest = verify_install(manifest_path, manifest_sha, rehash_binary=True)
    expected = json.loads(Path(manifest["catalog_path"]).read_text())
    override = "model_catalog_json=" + json.dumps(manifest["catalog_path"])
    with tempfile.TemporaryDirectory(prefix="exp7-catalog-debug-") as home:
        # A new empty CLI home supplies no credentials or prior conversation.
        # StaticModelsManager has no models endpoint to refresh.
        result = subprocess.run([manifest["real_binary"], "-c", override, "debug", "models"],
                                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                env={**os.environ, "CODEX_HOME": home}, timeout=30)
    if result.returncode:
        raise CatalogError("Installed CLI did not render the exact captured live catalog")
    mirrors = validate_rendered_catalog(expected, json.loads(result.stdout))
    if any(text in result.stderr.lower() for text in ("failed to refresh", "429", "fallback metadata")):
        raise CatalogError("Unexpected catalog refresh/fallback diagnostic during static validation")
    return {"exact_original_model_fields_equal": True, "model_count": len(expected["models"]),
            "verified_derived_legacy_field_count": mirrors,
            "derived_field_rule": "Each added base_instructions must exactly equal the existing instructions_template",
            "cli_version": manifest["cli_version"], "binary_full_hash_verified": True,
            "new_model_calls": 0, "path_activated": False,
            "network_assertion": "Static manager source path; debug output alone is not a packet trace"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    install = sub.add_parser("prepare")
    install.add_argument("--cache", required=True)
    install.add_argument("--install-dir", required=True)
    install.add_argument("--real-binary", default="/opt/codex/bin/codex")
    install.add_argument("--model", action="append", required=True)
    validate = sub.add_parser("validate-debug")
    validate.add_argument("--manifest", required=True)
    validate.add_argument("--manifest-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare_install(args.cache, args.install_dir, args.real_binary, args.model)
        else:
            result = validate_debug(args.manifest, args.manifest_sha256)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "blocked", "error_type": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
