"""Add separate operations files to the verified, immutable v2 distribution."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile

BASE_SHA256 = "cab2931dfc0114034b8ab93ea1ba219a7f82328f531d42f46248167d04cdb104"
PREFIX = "exp7-main-v2/"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def package(base, root, output):
    base, root, output = (Path(p).resolve() for p in (base, root, output))
    if digest(base.read_bytes()) != BASE_SHA256:
        raise ValueError("The original frozen distribution checksum differs")
    checksum = output.parent / "BACKUP_SHA256SUMS"
    if output.exists() or checksum.exists():
        raise ValueError("Distribution files are immutable; use a fresh output directory")
    entries = {}
    with tarfile.open(base, "r:gz") as archive:
        for member in archive:
            if (not member.isfile() or not member.name.startswith(PREFIX)
                    or ".." in Path(member.name).parts or member.name in entries):
                raise ValueError("Unsafe original distribution member")
            entries[member.name] = archive.extractfile(member).read()
    addon_files = sorted((root / "exp7_backup_v1").glob("*.py"))
    addon_files += sorted((root / "exp7_backup_v1").glob("*.md"))
    addon_files += [root / "docs/EXP7_MULTI_VM_HANDOFF.ko.md",
                    root / "docs/EXP7_STORAGE_REVIEW.ko.md",
                    root / "exp7_main_v2/README.md"]
    if not (root / "exp7_backup_v1/__main__.py").is_file():
        raise ValueError("Backup package is incomplete")
    addon_hashes = {}
    for path in addon_files:
        if path.is_symlink() or not path.is_file():
            raise ValueError("Unsafe operations source")
        relative = str(path.relative_to(root))
        data = path.read_bytes()
        entries[PREFIX + relative] = data
        addon_hashes[relative] = digest(data)
    entries[PREFIX + "OPERATIONS.json"] = (json.dumps({
        "version": 1, "base_archive_sha256": BASE_SHA256,
        "files": addon_hashes, "scope": "Separate backup and supervision; no experimental source changes"
    }, indent=2, sort_keys=True) + "\n").encode()
    frozen = json.loads(entries[PREFIX + "manifests/equivoque-2026-11-07-exp7-main-v2/freeze.json"])
    for relative, sha in frozen["files"].items():
        if digest(entries[PREFIX + relative]) != sha:
            raise ValueError("Frozen source changed: " + relative)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as target:
        with gzip.GzipFile(fileobj=target, mode="wb", filename="", mtime=0, compresslevel=6) as zipped:
            with tarfile.open(fileobj=zipped, mode="w|", format=tarfile.PAX_FORMAT) as archive:
                for name, data in sorted(entries.items()):
                    member = tarfile.TarInfo(name)
                    member.size, member.mode, member.mtime = len(data), 0o644, 0
                    archive.addfile(member, io.BytesIO(data))
    seen = set()
    with tarfile.open(output, "r:gz") as archive:
        for member in archive:
            if not member.isfile() or member.name in seen or member.name not in entries:
                raise ValueError("Output membership mismatch")
            if archive.extractfile(member).read() != entries[member.name]:
                raise ValueError("Output byte mismatch")
            seen.add(member.name)
    if seen != set(entries):
        raise ValueError("Missing output members")
    sha = digest(output.read_bytes())
    checksum.write_text(sha + "  " + output.name + "\n")
    return {"files": len(entries), "bytes": output.stat().st_size,
            "sha256": sha, "frozen_bytes_verified": True,
            "every_output_member_verified": True, "addon_files": addon_hashes}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps(package(args.base, args.root, args.output), indent=2))
