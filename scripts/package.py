#!/usr/bin/env python3
"""Build a versioned source-and-application archive with a file manifest."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {"private", ".runtime", "build", "dist", ".git", "config.json"}
SOURCE_DIRS = {"src", "scripts", "profiles", "examples", "tests", "docs"}
ROOT_FILES = {".gitignore", "VERSION", "LICENSE", "README.md", "README.zh-CN.md",
              "CHANGELOG.md", "CONTRIBUTING.md", "start.command", "stop.command",
              "status.command", "check.command"}


def release_paths(paths):
    selected = []
    for name in paths:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Invalid repository path: " + name)
        if not path.parts or path.parts[0] in EXCLUDED:
            continue
        if not (name in ROOT_FILES or len(path.parts) > 1 and path.parts[0] in SOURCE_DIRS):
            continue
        if any(p in (".DS_Store", "__pycache__") for p in path.parts) or name.endswith((".pyc", ".pyo")):
            continue
        selected.append(name)
    return sorted(set(selected))


def package(output):
    version = (ROOT / "VERSION").read_text().strip()
    if not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", version):
        raise ValueError("VERSION must contain a numeric release such as 1.0.")
    process = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    candidates = [p for p in process.stdout.decode().split("\0") if p] if process.returncode == 0 else []
    if not candidates:
        candidates = [name for name in ROOT_FILES if (ROOT / name).is_file()]
        for name in SOURCE_DIRS:
            candidates.extend(p.relative_to(ROOT).as_posix() for p in (ROOT / name).rglob("*") if p.is_file())
    names = release_paths(candidates)
    if "README.md" not in names or "src/main.m" not in names:
        raise ValueError("Expected README.md and src/main.m in the project source.")
    build_info = json.loads((ROOT / "build/build-info.json").read_text())
    for name, expected in build_info["sources"].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            raise ValueError("Build is stale; run scripts/build.sh first.")
    app = ROOT / "build/RawBLEAdvertiser.app"
    subprocess.run(["/usr/bin/codesign", "--verify", "--strict", str(app)], check=True)
    output.mkdir(parents=True, exist_ok=True)
    title = "macOS-BLE-Raw-Advertiser-" + version
    destination = output / (title + ".zip")
    with tempfile.TemporaryDirectory(prefix="rawble-release-") as temporary:
        folder = Path(temporary) / title
        folder.mkdir()
        for name in names:
            source = ROOT / name
            if source.is_symlink() or not source.is_file():
                raise ValueError("Expected a regular source file: " + name)
            target = folder / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        shutil.copytree(app, folder / "build/RawBLEAdvertiser.app")
        shutil.copy2(ROOT / "build/build-info.json", folder / "build/build-info.json")
        metadata = {"version": version, "profile": "macos-26.4-25E246-arm64",
                    "contents": "Source and ad-hoc signed arm64 application",
                    "defaultConfig": "examples/ibeacon-service-data.json"}
        (folder / "release.json").write_text(json.dumps(metadata, indent=2) + "\n")
        files = sorted(p for p in folder.rglob("*") if p.is_file())
        manifest = "".join(hashlib.sha256(p.read_bytes()).hexdigest() + "  " +
                           p.relative_to(folder).as_posix() + "\n" for p in files)
        (folder / "SHA256SUMS").write_text(manifest)
        pending = output / (title + ".zip.tmp")
        try:
            with zipfile.ZipFile(pending, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
                for path in sorted(p for p in folder.rglob("*") if p.is_file()):
                    info = zipfile.ZipInfo(title + "/" + path.relative_to(folder).as_posix(), (2026, 1, 1, 0, 0, 0))
                    info.create_system = 3
                    info.compress_type = zipfile.ZIP_DEFLATED
                    mode = 0o755 if path.stat().st_mode & 0o111 else 0o644
                    info.external_attr = (0o100000 | mode) << 16
                    archive.writestr(info, path.read_bytes())
            pending.replace(destination)
        finally:
            pending.unlink(missing_ok=True)
    checksum = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix(".zip.sha256").write_text(checksum + "  " + destination.name + "\n")
    print(destination)
    print("SHA-256: " + checksum)
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    arguments = parser.parse_args()
    package(arguments.output.resolve())
