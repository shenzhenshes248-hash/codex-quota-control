"""Package source and binaries, excluding credentials, local transport state and caches."""
import os
from pathlib import Path
import shutil
import tarfile
import zipfile

root = Path(__file__).resolve().parent.parent
dist = root / "dist"
dist.mkdir(exist_ok=True)
apk = root / "android/app/build/outputs/apk/debug/app-debug.apk"
assert apk.is_file()
shutil.copy2(apk, dist / "Codex额度控制-0.1.0-debug.apk")
skip = {".git", ".tools", ".gradle", ".pytest_cache", "__pycache__", "build", "dist", ".idea"}
files = []
for folder, dirs, names in os.walk(root):
    dirs[:] = [d for d in dirs if d not in skip]
    for name in names:
        if name == "local.properties" or name.endswith((".pyc", ".jks", ".keystore", ".stackdump")):
            continue
        path = Path(folder) / name
        relative = path.relative_to(root)
        if relative.parts[0] == "tools" and name not in {"package_delivery.py", "build_installer.py"}:
            continue
        files.append(path)
with zipfile.ZipFile(dist / "codex-quota-control-source.zip", "w", zipfile.ZIP_DEFLATED) as archive:
    for path in files:
        archive.write(path, "codex-quota-control/" + path.relative_to(root).as_posix())
with tarfile.open(dist / "codex-quota-control-server.tar.gz", "w:gz") as archive:
    for path in files:
        relative = path.relative_to(root)
        if relative.parts[0] in ("server", "deploy", "docs") or relative.name == "README.md":
            archive.add(path, "codex-quota-control/" + relative.as_posix(), recursive=False)
for path in sorted(dist.iterdir()):
    print(path.name, path.stat().st_size)
