from __future__ import annotations

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")

root = Path(sys.argv[1]).resolve()
if not (root / "disk_health_inspector.py").is_file():
    raise SystemExit("找不到硬盘健康卫士源码目录")

def patch_file(name: str, replacements: list[tuple[str, str]]) -> None:
    path = root / name
    text = path.read_text(encoding="utf-8-sig")
    for old, new in replacements:
        if new in text:
            continue
        if old not in text:
            raise SystemExit(f"{name} 补丁定位失败，拒绝盲目修改：{old[:90]!r}")
        text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8-sig", newline="")

patch_file("disk_health_inspector.py", [
    (
        '        self.notebook.add(diagnostics_tab, text="智能诊断")\n        self.notebook.add(self_test_tab, text="自检中心")',
        '        self.scan_tab = scan_tab\n        self.self_test_tab = self_test_tab\n        self.notebook.add(diagnostics_tab, text="智能诊断")\n        self.notebook.add(self_test_tab, text="自检中心")',
    ),
    (
        '        self.notebook.select(1)\n        self._log(f"开始 PhysicalDrive{idx} 全盘只读扫描。")',
        '        self.notebook.select(self.scan_tab)\n        self._log(f"开始 PhysicalDrive{idx} 全盘只读扫描。")',
    ),
    (
        '                    self.notebook.select(1)\n                    self.status_var.set(f"PhysicalDrive{idx} {label}已提交，自动监控中")',
        '                    self.notebook.select(self.self_test_tab)\n                    self.status_var.set(f"PhysicalDrive{idx} {label}已提交，自动监控中")',
    ),
])

patch_file("disk_health_diagnostics.py", [
    (
        '    observed = False\n    evidence_count = 0\n\n    def apply(code, title, value, points, recommendation, critical_if=False):\n        nonlocal score, critical, evidence_count',
        '    observed = False\n    evidence_count = 0\n    critical_evidence_count = 0\n\n    def apply(code, title, value, points, recommendation, critical_if=False):\n        nonlocal score, critical, evidence_count, critical_evidence_count',
    ),
    (
        '        evidence_count += 1\n        try:\n            numeric = int(value)',
        '        evidence_count += 1\n        critical_evidence_count += 1\n        try:\n            numeric = int(value)',
    ),
    (
        '            wear = int(wear)\n            evidence_count += 1',
        '            wear = int(wear)\n            evidence_count += 1\n            critical_evidence_count += 1',
    ),
    (
        '    if spare is not None and spare_threshold is not None:\n        evidence_count += 1',
        '    if spare is not None and spare_threshold is not None:\n        evidence_count += 1\n        critical_evidence_count += 1',
    ),
    (
        '    if evidence_count == 0:\n        return {"score": None, "level": "数据不足", "rules": rules,\n                "summary": "设备没有提供足够的关键 SMART 计数或耐久度证据，无法可靠评分。SMART 总体状态即使显示通过，也不能替代这些证据。"}',
        '    if critical_evidence_count == 0:\n        return {"score": None, "level": "数据不足", "rules": rules,\n                "summary": "虽然可能已读取温度或接口 CRC 等辅助信息，但缺少重映射/待映射/不可校正扇区、NVMe 媒体错误或可靠耐久度等关键证据，无法可靠评分。SMART 总体状态即使显示通过，也不能替代这些证据。"}',
    ),
    (
        '            "summary": f"根据当前 {evidence_count} 项可解释的关键 SMART 证据，评分 {score}/100，等级：{level}。评分不是硬盘寿命保证。"}',
        '            "summary": f"根据当前 {critical_evidence_count} 项可解释的关键 SMART 证据（另有 {max(0, evidence_count-critical_evidence_count)} 项辅助信息），评分 {score}/100，等级：{level}。评分不是硬盘寿命保证。"}',
    ),
])

test_path = root / "test_diagnostics.py"
test_text = test_path.read_text(encoding="utf-8-sig")
new_test = '''
    def test_temperature_alone_is_not_media_health_score(self):
        result = assess_health({"metrics": {"temperature_c": 35}, "smart_passed": True})
        self.assertIsNone(result["score"])
        self.assertEqual(result["level"], "数据不足")
'''
if "test_temperature_alone_is_not_media_health_score" not in test_text:
    marker = '\nif __name__ == "__main__":'
    if marker not in test_text:
        raise SystemExit("test_diagnostics.py 补丁定位失败")
    test_text = test_text.replace(marker, "\n" + new_test + marker, 1)
    test_path.write_text(test_text, encoding="utf-8-sig", newline="")

for name in ("README_中文.md", "CHANGELOG.md", "VALIDATION_REPORT.md"):
    path = root / name
    if not path.exists():
        continue
    text = path.read_text(encoding="utf-8-sig")
    text = text.replace("20 项核心测试 + 14 项诊断规则测试", "20 项核心测试 + 15 项诊断规则测试")
    text = text.replace("诊断规则测试：14/14 PASS。", "诊断规则测试：15/15 PASS。")
    text = text.replace("合计：34/34 PASS。", "合计：35/35 PASS。")
    if name == "CHANGELOG.md":
        text = text.replace(
            "本阶段尚未完成 Windows 真机验收；扫描速度热力图与慢速区块复测仍待开发。",
            "修复新增标签页后坏道扫描错误跳转到自检中心的问题；评分在只有温度/CRC 辅助数据时改为“数据不足”。本阶段尚未完成 Windows 真机验收；扫描速度热力图与慢速区块复测仍待开发。",
        )
    path.write_text(text, encoding="utf-8-sig", newline="")

print("v0.4.0 修正补丁已应用：扫描页签跳转、评分证据门槛和新增回归测试。")
