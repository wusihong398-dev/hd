from __future__ import annotations

import base64
import hashlib
import os
import shutil
import tarfile
from pathlib import Path

ROOT = Path(os.environ["GITHUB_WORKSPACE"])
BOOTSTRAP = ROOT / "bootstrap"
RUNNER_TEMP = Path(os.environ["RUNNER_TEMP"])
ARCHIVE = RUNNER_TEMP / "hd-source.tar.xz"
EXTRACT = RUNNER_TEMP / "hd-source"

def fail(message: str) -> None:
    raise SystemExit(message)

part_files = sorted(BOOTSTRAP.glob("source-bundle.tar.xz.b64.part-*"))
if not part_files:
    fail("源码分卷缺失：bootstrap/source-bundle.tar.xz.b64.part-*")
chunks = []
for part in part_files:
    if not part.is_file():
        fail(f"源码分卷缺失：{part.name}")
    chunks.append(part.read_text(encoding="ascii").strip())

try:
    archive_bytes = base64.b64decode("".join(chunks), validate=True)
except Exception as exc:
    fail(f"源码分卷 Base64 解码失败：{exc}")

if len(archive_bytes) < 10_000 or not archive_bytes.startswith(bytes.fromhex("fd377a585a00")):
    fail(f"源码归档长度或 XZ 文件头异常：{len(archive_bytes)} bytes")

ARCHIVE.write_bytes(archive_bytes)
if EXTRACT.exists():
    shutil.rmtree(EXTRACT)
EXTRACT.mkdir(parents=True)

try:
    with tarfile.open(ARCHIVE, mode="r:xz") as bundle:
        root_resolved = EXTRACT.resolve()
        for member in bundle.getmembers():
            target = (EXTRACT / member.name).resolve()
            if target != root_resolved and root_resolved not in target.parents:
                fail(f"源码归档包含越界路径：{member.name}")
        bundle.extractall(path=EXTRACT)
except Exception as exc:
    fail(f"Python tarfile 解压源码归档失败：{exc}")

matches = list(EXTRACT.rglob("disk_health_inspector.py"))
if not matches:
    fail("源码包中没有 disk_health_inspector.py")
SRC_DIR = matches[0].parent
for required in ("health_diagnostics.py", "test_core.py", "THIRD_PARTY_NOTICES.txt", "build_windows.ps1", "SHA256SUMS.txt"):
    if not (SRC_DIR / required).is_file():
        fail(f"源码包缺少必要文件：{required}")

# Verify the packaged source manifest before building.
manifest = SRC_DIR / "SHA256SUMS.txt"
for line in manifest.read_text(encoding="utf-8-sig").splitlines():
    if not line.strip():
        continue
    try:
        expected, relative = line.split("  ", 1)
    except ValueError:
        fail(f"SHA256 清单行格式错误：{line[:100]}")
    target = (SRC_DIR / relative).resolve()
    if SRC_DIR.resolve() not in target.parents:
        fail(f"SHA256 清单包含越界路径：{relative}")
    if not target.is_file():
        fail(f"SHA256 清单对应文件缺失：{relative}")
    actual = hashlib.sha256(target.read_bytes()).hexdigest()
    if actual.lower() != expected.lower():
        fail(f"源码 SHA256 校验失败：{relative}")

# sqlite3.Connection's context manager commits/rolls back but does not close.
source = SRC_DIR / "disk_health_inspector.py"
source_text = source.read_text(encoding="utf-8")
if "from contextlib import contextmanager" not in source_text:
    if "import sqlite3\n" not in source_text:
        fail("找不到 sqlite3 导入，无法应用 Windows SQLite 句柄修复")
    source_text = source_text.replace("import sqlite3\n", "import sqlite3\nfrom contextlib import contextmanager\n", 1)

old = """    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn
"""
new = '''    @contextmanager
    def _connect(self):
        """提交或回滚事务，并始终关闭 SQLite 文件句柄。"""
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
'''
if old in source_text:
    source_text = source_text.replace(old, new, 1)
elif "finally:\n            conn.close()" not in source_text:
    fail("未找到预期的 HealthHistoryStore._connect 方法，拒绝盲目修改")

source.write_text(source_text, encoding="utf-8")
with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8", newline="\n") as env_file:
    env_file.write(f"SRC_DIR={SRC_DIR}\n")

print(f"源码准备完成：{SRC_DIR}")
print(f"归档大小：{len(archive_bytes)} bytes")
print(f"SHA256 清单校验通过：{len(manifest.read_text(encoding='utf-8-sig').splitlines())} 项")
print("Windows SQLite 连接关闭补丁已验证")
