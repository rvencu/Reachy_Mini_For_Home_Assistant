"""Install a reviewed fork wheel on Reachy, keeping an offline rollback copy."""

import argparse
import hashlib
import importlib.metadata
import json
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from datetime import UTC, datetime
from email.parser import BytesParser
from pathlib import Path

APP = "reachy_mini_home_assistant"
SDK = "1.11.0"
VERSION = "1.0.7+smarty.1"
VENV = Path("/venvs/apps_venv")


def api(path, *, post=False):
    request = urllib.request.Request(
        "http://127.0.0.1:8000/api/apps/" + path,
        data=b"" if post else None,
        method="POST" if post else "GET",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def stop_voice_app():
    current = api("current-app-status")
    if current and current.get("name") not in (None, APP):
        raise RuntimeError("Another app is active; leave it untouched and stop it explicitly first")
    if current and current.get("name") == APP and current.get("state") != "stopped":
        api("stop-current-app", post=True)


def start_voice_app():
    api("start-app/" + APP, post=True)


def installed_paths():
    dist = importlib.metadata.distribution(APP)
    site = Path(dist.locate_file("")).resolve()
    metadata = [p for p in site.glob(APP + "-*.dist-info") if p.is_dir()]
    if len(metadata) != 1:
        raise RuntimeError("Expected exactly one installed app distribution")
    return site, site / APP, metadata[0]


def restore(backup):
    manifest = json.loads((backup / "manifest.json").read_text())
    site = Path(manifest["site"])
    if site != VENV / "lib/python3.12/site-packages":
        raise RuntimeError("Backup belongs to a different environment")
    package = backup / APP
    metadata = backup / manifest["metadata"]
    if not package.is_dir() or not metadata.is_dir() or not metadata.name.startswith(APP + "-"):
        raise RuntimeError("Incomplete backup")
    stop_voice_app()
    targets = [site / APP, *site.glob(APP + "-*.dist-info")]
    for target in targets:
        if target.is_symlink():
            raise RuntimeError("Refusing to replace a symlink")
    for target in targets:
        if target.exists():
            shutil.rmtree(target)
    shutil.copytree(package, site / APP)
    shutil.copytree(metadata, site / metadata.name)
    for name in manifest.get("extra_files", []):
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError("Invalid backup file path")
        target = site / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup / "extra" / relative, target)
    start_voice_app()
    release = {"restored_version": manifest["version"], "backup": str(backup)}
    (backup.parent.parent / "current.json").write_text(json.dumps(release, indent=2) + "\n")
    print(json.dumps(release))


def install(wheel, revision):
    if importlib.metadata.version("reachy-mini") != SDK:
        raise RuntimeError("This deployment is validated for Reachy SDK " + SDK + " only")
    with zipfile.ZipFile(wheel) as archive:
        metadata_paths = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(metadata_paths) != 1:
            raise RuntimeError("Invalid wheel metadata")
        metadata = BytesParser().parsebytes(archive.read(metadata_paths[0]))
        if metadata["Name"].replace("-", "_") != APP or metadata["Version"] != VERSION:
            raise RuntimeError("Wheel is not the reviewed Smarty fork version")
        hashes = {
            name: hashlib.sha256(archive.read(name)).hexdigest()
            for name in archive.namelist()
            if name.startswith(APP + "/") and name.endswith(".py")
        }
    if not hashes:
        raise RuntimeError("Wheel has no application source")
    site, package, metadata_path = installed_paths()
    previous = importlib.metadata.version(APP)
    if previous not in ("1.0.7", VERSION):
        raise RuntimeError("Unexpected installed app version: " + previous)
    backup = Path.home() / ".local/share/reachy-smarty/backups" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    backup.mkdir(parents=True, mode=0o700)
    shutil.copytree(package, backup / APP)
    shutil.copytree(metadata_path, backup / metadata_path.name)
    extra_files = []
    for name in importlib.metadata.files(APP) or []:
        relative = Path(name)
        if relative.parts[0] in (APP, metadata_path.name):
            continue
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError("App owns files outside site-packages; inspect before deployment")
        if (site / relative).is_file():
            destination = backup / "extra" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(site / relative, destination)
            extra_files.append(str(relative))
    manifest = {
        "site": str(site), "metadata": metadata_path.name, "version": previous,
        "revision": revision, "extra_files": extra_files,
    }
    (backup / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    shutil.copy2(__file__, backup / "install_wheel.py")
    print("Rollback copy: " + str(backup), flush=True)
    stop_voice_app()
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--no-index", "--no-deps", "--force-reinstall", str(wheel)],
            check=True,
        )
        for name, expected in hashes.items():
            if hashlib.sha256((site / name).read_bytes()).hexdigest() != expected:
                raise RuntimeError("Installed source differs from wheel: " + name)
        start_voice_app()
    except Exception:
        restore(backup)
        raise
    release = {
        "version": VERSION,
        "revision": revision,
        "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        "backup": str(backup),
        "source_files_verified": len(hashes),
    }
    (backup.parent.parent / "current.json").write_text(json.dumps(release, indent=2) + "\n")
    print(json.dumps(release))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--wheel", type=Path)
    modes.add_argument("--restore", type=Path)
    parser.add_argument("--revision")
    args = parser.parse_args()
    if Path(sys.prefix) != VENV:
        parser.error("Run with /venvs/apps_venv/bin/python on the robot")
    if args.restore:
        restore(args.restore.resolve())
    else:
        if not args.revision or len(args.revision) != 40 or any(c not in "0123456789abcdef" for c in args.revision):
            parser.error("--revision must be the full reviewed Git commit")
        install(args.wheel.resolve(), args.revision)


if __name__ == "__main__":
    main()
