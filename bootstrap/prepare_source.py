from __future__ import annotations

import base64
import hashlib
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")

ROOT = Path(os.environ["GITHUB_WORKSPACE"])
BOOTSTRAP = ROOT / "bootstrap"
RUNNER_TEMP = Path(os.environ["RUNNER_TEMP"])
ARCHIVE = RUNNER_TEMP / "hd-v040-source.zip"
EXTRACT = RUNNER_TEMP / "hd-v040-source"

def fail(message: str) -> None:
    raise SystemExit(message)

parts = sorted(BOOTSTRAP.glob("v040-integrated-source.zip.b64.part-*"))
if not parts:
    fail("缺少 v0.4.0 源码分卷。")
encoded = "".join(part.read_text(encoding="ascii").strip() for part in parts)
try:
    archive_bytes = base64.b64decode(encoded, validate=True)
except Exception as exc:
    fail(f"源码分卷 Base64 解码失败：{exc}")

if len(archive_bytes) < 10_000 or not archive_bytes.startswith(b"PK\x03\x04"):
    fail(f"源码 ZIP 文件头或长度异常：{len(archive_bytes)} bytes")

ARCHIVE.write_bytes(archive_bytes)
if EXTRACT.exists():
    shutil.rmtree(EXTRACT)
EXTRACT.mkdir(parents=True)

try:
    with zipfile.ZipFile(ARCHIVE, "r") as bundle:
        root_resolved = EXTRACT.resolve()
        for info in bundle.infolist():
            target = (EXTRACT / info.filename).resolve()
            if target != root_resolved and root_resolved not in target.parents:
                fail(f"源码 ZIP 包含越界路径：{info.filename}")
        bundle.extractall(EXTRACT)
except Exception as exc:
    fail(f"源码 ZIP 解压失败：{exc}")

matches = list(EXTRACT.rglob("disk_health_inspector.py"))
if not matches:
    fail("源码包中没有 disk_health_inspector.py")
SRC_DIR = matches[0].parent

required = (
    "disk_health_diagnostics.py",
    "test_core.py",
    "test_diagnostics.py",
    "THIRD_PARTY_NOTICES.txt",
    "build_windows.ps1",
    "SHA256SUMS.txt",
)
for name in required:
    if not (SRC_DIR / name).is_file():
        fail(f"源码包缺少必要文件：{name}")

manifest = SRC_DIR / "SHA256SUMS.txt"
checked = 0
for line in manifest.read_text(encoding="utf-8-sig").splitlines():
    if not line.strip():
        continue
    try:
        expected, relative = line.split("  ", 1)
    except ValueError:
        fail(f"SHA256 清单格式错误：{line[:100]}")
    target = (SRC_DIR / relative).resolve()
    if SRC_DIR.resolve() not in target.parents:
        fail(f"SHA256 清单路径越界：{relative}")
    if not target.is_file():
        fail(f"SHA256 清单文件缺失：{relative}")
    actual = hashlib.sha256(target.read_bytes()).hexdigest()
    if actual.lower() != expected.lower():
        fail(f"源码 SHA256 校验失败：{relative}")
    checked += 1

patch_script = BOOTSTRAP / "apply_v040_fixes.py"
if not patch_script.is_file():
    fail("缺少 v0.4.0 修正补丁脚本。")
subprocess.run([sys.executable, str(patch_script), str(SRC_DIR)], check=True)
scan_patch_script = BOOTSTRAP / "apply_scan_visuals.py"
if not scan_patch_script.is_file():
    fail("缺少坏道扫描可视化补丁脚本。")
subprocess.run([sys.executable, str(scan_patch_script), str(SRC_DIR)], check=True)
inspect_script = BOOTSTRAP / "inspect_source.py"
if not inspect_script.is_file():
    fail("缺少源码结构审计脚本。")
subprocess.run([sys.executable, str(inspect_script), str(SRC_DIR)], check=True)

with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8", newline="\n") as env_file:
    env_file.write(f"SRC_DIR={SRC_DIR}\n")

print(f"源码目录：{SRC_DIR}")
print(f"源码 ZIP 大小：{len(archive_bytes)} bytes")
print("已应用坏道扫描网格与完整报告补丁。")
print(f"源码 SHA256 清单校验通过：{checked} 项")
