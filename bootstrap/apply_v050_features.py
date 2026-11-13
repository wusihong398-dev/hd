from __future__ import annotations

import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")

root = Path(sys.argv[1]).resolve()
main_path = root / "disk_health_inspector.py"
diag_path = root / "disk_health_diagnostics.py"
source = main_path.read_text(encoding="utf-8-sig")

def patch_once(old: str, new: str, label: str) -> None:
    global source
    if new in source:
        return
    if old not in source:
        raise SystemExit(f"v0.5.0 主程序补丁定位失败：{label}")
    source = source.replace(old, new, 1)

# Set release version without changing unrelated metadata.
source, n = re.subn(r'(?m)^APP_VERSION\s*=\s*["\'][^"\']+["\']',
                    'APP_VERSION = "0.5.0"', source, count=1)
if n != 1:
    raise SystemExit("无法安全更新 APP_VERSION。")

patch_once(
    "        self.current_smart = None\n        self.current_summary = None\n",
    "        self.current_smart = None\n        self.current_smart_index = None\n        self.current_summary = None\n",
    "当前 SMART 设备索引"
)

patch_once(
    '        self.notebook.add(diagnostics_tab, text="智能诊断")\n',
    '        overview_tab = ttk.Frame(self.notebook, padding=8)\n'
    '        report_tab = ttk.Frame(self.notebook, padding=8)\n'
    '        self.overview_tab = overview_tab\n'
    '        self.report_tab = report_tab\n'
    '        self.notebook.add(overview_tab, text="健康总览")\n'
    '        self.notebook.add(diagnostics_tab, text="智能诊断")\n'
    '        self.notebook.add(report_tab, text="报告中心")\n',
    "新增健康总览和报告中心标签"
)

patch_once(
    '        diag_head = ttk.LabelFrame(diagnostics_tab, text="本盘智能诊断结论", padding=10)\n',
    '''        overview_head = ttk.LabelFrame(overview_tab, text="全部物理硬盘健康总览", padding=10)
        overview_head.pack(fill="x", pady=(0, 8))
        self.overview_summary_var = tk.StringVar(value="请先执行“全部硬盘 SMART 检测”以生成健康总览。")
        ttk.Label(overview_head, textvariable=self.overview_summary_var,
                  font=("Microsoft YaHei UI", 10, "bold"), wraplength=900).pack(anchor="w")
        overview_actions = ttk.Frame(overview_tab)
        overview_actions.pack(fill="x", pady=(0, 7))
        ttk.Button(overview_actions, text="刷新总览", command=self._render_health_overview).pack(side="left")
        ttk.Button(overview_actions, text="检测全部硬盘", command=self.start_all_smart_check).pack(side="left", padx=7)
        ttk.Button(overview_actions, text="导出全部硬盘报告", command=self.export_all_report).pack(side="left", padx=7)
        overview_cols = ("index", "model", "kind", "size", "health", "score", "temperature", "wear", "smart")
        self.overview_tree = ttk.Treeview(overview_tab, columns=overview_cols, show="headings", height=9)
        for col, title, width in (
            ("index", "编号", 55), ("model", "硬盘型号", 180), ("kind", "介质类型", 95),
            ("size", "容量", 90), ("health", "健康状态", 85), ("score", "评分", 65),
            ("temperature", "温度", 65), ("wear", "剩余耐久度", 85), ("smart", "SMART", 85),
        ):
            self.overview_tree.heading(col, text=title)
            self.overview_tree.column(col, width=width, anchor="w")
        self.overview_tree.tag_configure("good", foreground="#16804a")
        self.overview_tree.tag_configure("attention", foreground="#a36a00")
        self.overview_tree.tag_configure("danger", foreground="#b42318")
        self.overview_tree.tag_configure("unknown", foreground="#68788a")
        self.overview_tree.pack(fill="both", expand=True)
        self.overview_tree.bind("<<TreeviewSelect>>", self._on_overview_select)
        self.overview_detail = tk.Text(overview_tab, height=7, wrap="word", font=("Microsoft YaHei UI", 9))
        self.overview_detail.pack(fill="x", pady=(8, 0))
        self.overview_detail.insert("end", "选择一块硬盘查看诊断依据、风险提示和建议。评分只在关键 SMART 证据充分时显示。")
        self.overview_detail.configure(state="disabled")

        report_head = ttk.LabelFrame(report_tab, text="中文诊断报告中心", padding=12)
        report_head.pack(fill="x", pady=(0, 8))
        ttk.Label(report_head, text="报告将汇总硬盘信息、SMART 证据、风险评分、自检历史、坏道扫描记录和健康趋势。未检测或设备不支持的项目会明确标注，不会推测为正常。",
                  wraplength=900).pack(anchor="w")
        ttk.Button(report_head, text="生成全部硬盘 HTML / JSON 报告",
                   command=self.export_all_report).pack(anchor="w", pady=(9, 0))
        self.report_status_var = tk.StringVar(value="尚未生成报告。请先执行全部硬盘 SMART 检测。")
        ttk.Label(report_tab, textvariable=self.report_status_var,
                  foreground="#52657c", wraplength=900).pack(anchor="w", pady=(5, 8))
        self.report_preview = tk.Text(report_tab, height=18, wrap="word", font=("Microsoft YaHei UI", 9))
        self.report_preview.pack(fill="both", expand=True)
        self.report_preview.insert("end", "报告预览会在全部硬盘检测完成后显示摘要。点击上方按钮可保存完整 HTML 或 JSON 文件。")
        self.report_preview.configure(state="disabled")

        diag_head = ttk.LabelFrame(diagnostics_tab, text="本盘智能诊断结论", padding=10)
''',
    "总览与报告中心 UI"
)

# Add a small, testable aggregate helper to the diagnostic module.
diag = diag_path.read_text(encoding="utf-8-sig")
if "def summarize_health_overview(" not in diag:
    diag += '''

def summarize_health_overview(results: list[dict[str, Any]]) -> dict[str, Any]:
    """汇总全部硬盘结果；数据不足/SMART 读取失败不会计入健康通过数。"""
    counts = {"良好": 0, "关注": 0, "警告": 0, "严重": 0, "数据不足": 0, "无法读取": 0, "待检测": 0}
    scores: list[int] = []
    for item in results:
        level = str(item.get("risk_level") or item.get("health") or "待检测")
        if item.get("error") or level == "无法读取":
            level = "无法读取"
        elif item.get("score") is None and level not in {"严重", "无法读取"}:
            level = "数据不足"
        elif level not in counts:
            level = "数据不足"
        counts[level] += 1
        score = item.get("score")
        if isinstance(score, (int, float)) and not isinstance(score, bool):
            scores.append(int(score))
    return {
        "total": len(results),
        "counts": counts,
        "scored": len(scores),
        "average_score": round(sum(scores) / len(scores), 1) if scores else None,
    }
'''
diag_path.write_text(diag, encoding="utf-8-sig", newline="")

test_path = root / "test_v050_dashboard.py"
test_content = """import unittest

from disk_health_diagnostics import summarize_health_overview


class HealthOverviewSummaryTests(unittest.TestCase):
    def test_summary_counts_risk_levels_and_only_averages_real_scores(self):
        results = [
            {"risk_level": "良好", "score": 96},
            {"risk_level": "关注", "score": 82},
            {"risk_level": "严重", "score": None},
            {"risk_level": "无法读取", "error": "SMART unsupported", "score": None},
            {"risk_level": "数据不足", "score": None},
        ]
        summary = summarize_health_overview(results)
        self.assertEqual(summary["total"], 5)
        self.assertEqual(summary["counts"]["良好"], 1)
        self.assertEqual(summary["counts"]["关注"], 1)
        self.assertEqual(summary["counts"]["严重"], 1)
        self.assertEqual(summary["counts"]["无法读取"], 1)
        self.assertEqual(summary["counts"]["数据不足"], 1)
        self.assertEqual(summary["scored"], 2)
        self.assertEqual(summary["average_score"], 89.0)

    def test_failed_smart_read_is_not_counted_as_healthy(self):
        summary = summarize_health_overview([{"health": "正常", "error": "access denied"}])
        self.assertEqual(summary["counts"]["无法读取"], 1)
        self.assertEqual(summary["counts"]["良好"], 0)

    def test_zero_score_is_a_real_score(self):
        summary = summarize_health_overview([{"risk_level": "严重", "score": 0}])
        self.assertEqual(summary["scored"], 1)
        self.assertEqual(summary["average_score"], 0.0)


if __name__ == "__main__":
    unittest.main()
"""
test_path.write_text(test_content, encoding="utf-8")

# Bind dashboard results to stable disk identity as well as the transient PhysicalDrive number.
patch_once(
    '                idx = int(disk.get("Index", 0))\n                try:\n',
    '                idx = int(disk.get("Index", 0))\n                identity_key, identity_quality = disk_identity(disk)\n                try:\n',
    "全部硬盘结果稳定身份"
)

# Compute diagnostics for every drive during the existing all-disk SMART worker.
patch_once(
    '                    summary = smart_summary(data)\n                    history_result = None\n',
    '                    summary = smart_summary(data)\n'
    '                    drive_class = classify_drive(disk, data)\n'
    '                    parsed_smart = interpret_smart(data)\n'
    '                    history_result = None\n',
    "全部硬盘 SMART 诊断准备"
)
patch_once(
    '                idx = int(disk.get("Index", 0))\n                try:\n',
    '                idx = int(disk.get("Index", 0))\n                identity_key, identity_quality = disk_identity(disk)\n                try:\n',
    "全部硬盘结果稳定身份"
)
patch_once(
    '                    results.append({\n                        "disk_index": idx, "model": disk.get("Model", "未知型号"),\n',
    '                    results.append({\n                        "disk_index": idx, "model": disk.get("Model", "未知型号"),\n                        "identity_key": identity_key, "identity_quality": identity_quality,\n',
    "成功结果绑定硬盘身份"
)
patch_once(
    '                    results.append({\n                        "disk_index": idx, "model": disk.get("Model", "未知型号"),\n                        "size": disk.get("Size"), "health": "无法读取",\n',
    '                    results.append({\n                        "disk_index": idx, "model": disk.get("Model", "未知型号"),\n                        "size": disk.get("Size"), "health": "无法读取",\n                        "identity_key": identity_key, "identity_quality": identity_quality,\n',
    "读取失败结果绑定硬盘身份"
)

# Keep the selected drive's most recent SMART result available to the dashboard.
patch_once(
    '        self.current_smart = data\n        self.current_summary = summary\n',
    '        self.current_smart = data\n        self.current_smart_index = idx\n        self.current_summary = summary\n',
    "当前盘 SMART 结果索引"
)
patch_once(
    '        self.status_var.set("SMART 数据读取完成")\n',
    '        self.status_var.set("SMART 数据读取完成")\n'
    '        self._render_health_overview()\n',
    "单盘 SMART 完成后刷新总览"
)

# Insert dashboard/report methods before the existing event polling loop.
methods = r'''    def _overview_results(self):
        report = self.last_all_smart_report or {}
        results = report.get("results", []) if isinstance(report, dict) else []
        by_index = {int(item.get("disk_index")): item for item in results
                    if item.get("disk_index") is not None}
        by_identity = {item.get("identity_key"): item for item in results if item.get("identity_key")}
        if self.current_smart_index is not None and self.current_summary is not None:
            idx = int(self.current_smart_index)
            selected_disk = next((d for d in self.disks if int(d.get("Index", -1)) == idx), {})
            selected_key, _ = disk_identity(selected_disk) if selected_disk else (None, None)
            if idx not in by_index or (selected_key and by_index[idx].get("identity_key") not in (None, selected_key)):
                parsed = self.current_interpreted_smart or {}
                diagnostic = self.current_diagnostic or {}
                drive_class = self.current_drive_class or {}
                metrics = parsed.get("metrics") or {}
                by_index[idx] = {
                    "disk_index": idx, "identity_key": selected_key,
                    "model": next((d.get("Model") for d in self.disks if int(d.get("Index", -1)) == idx), "未知型号"),
                    "health": self.current_summary.get("health", "未知"),
                    "temperature": self.current_summary.get("temperature"),
                    "hours": self.current_summary.get("hours"),
                    "wear": self.current_summary.get("wear"),
                    "wear_remaining_percent": metrics.get("wear_remaining_percent"),
                    "drive_type": drive_class.get("type", "未知"),
                    "score": diagnostic.get("score"),
                    "risk_level": diagnostic.get("level", "数据不足"),
                    "diagnostic_summary": diagnostic.get("summary", ""),
                    "diagnostic_rules": diagnostic.get("rules", []),
                    "warnings": self.current_summary.get("warnings", []),
                    "error": None,
                }
        self._overview_results_by_identity = by_identity
        return by_index

    def _render_health_overview(self):
        if not hasattr(self, "overview_tree"):
            return
        by_index = self._overview_results()
        rows = []
        for disk in self.disks:
            idx = int(disk.get("Index", 0))
            identity_key, _ = disk_identity(disk)
            item = getattr(self, "_overview_results_by_identity", {}).get(identity_key) or by_index.get(idx, {})
            if item.get("model") and disk.get("Model") and str(item.get("model")).strip() != str(disk.get("Model")).strip():
                item = {}
            risk = item.get("risk_level") or ("无法读取" if item.get("error") else "待检测")
            score = item.get("score")
            score_text = f"{score}/100" if score is not None else "数据不足"
            temp = item.get("temperature")
            temp_text = f"{temp}℃" if temp is not None else "未知"
            wear = item.get("wear_remaining_percent")
            wear_text = f"{wear}%（估算）" if wear is not None else "未提供"
            health = item.get("health", "待检测")
            smart = "不可用" if item.get("error") else "已读取" if item else "待检测"
            kind = item.get("drive_type", "待识别")
            size = human_size(disk.get("Size"))
            tag = "good" if risk == "良好" else "attention" if risk == "关注" else "danger" if risk in ("警告", "严重", "无法读取") else "unknown"
            values = (idx, disk.get("Model", "未知型号"), kind, size, risk, score_text, temp_text, wear_text, smart)
            rows.append((disk, item, values, tag))
        for tree in (self.overview_tree, getattr(self, "report_tree", None)):
            if tree is None:
                continue
            for iid in tree.get_children():
                tree.delete(iid)
            for disk, item, values, tag in rows:
                tree.insert("", "end", iid=str(disk.get("Index")), values=values, tags=(tag,))
        try:
            overview_module = __import__("disk_health_diagnostics", fromlist=["summarize_health_overview"])
            summary = overview_module.summarize_health_overview(list(by_index.values()))
            c = summary["counts"]
            avg = f"{summary['average_score']}/100" if summary["average_score"] is not None else "暂无可评分硬盘"
            self.overview_summary_var.set(
                f"共识别 {len(self.disks)} 块物理硬盘；已取得 SMART 结果 {summary['total']} 块；"
                f"良好 {c['良好']} · 关注 {c['关注']} · 警告 {c['警告']} · 严重 {c['严重']} · "
                f"数据不足 {c['数据不足']} · 无法读取 {c['无法读取']}；可评分硬盘平均分：{avg}。"
            )
        except Exception as exc:
            self.overview_summary_var.set(f"总览汇总暂不可用：{exc}")
        self._render_report_center()

    def _on_overview_select(self, _event=None):
        if not hasattr(self, "overview_tree"):
            return
        selection = self.overview_tree.selection()
        if not selection:
            return
        try:
            idx = int(selection[0])
        except (TypeError, ValueError):
            return
        item = self._overview_results().get(idx, {})
        disk = next((d for d in self.disks if int(d.get("Index", -1)) == idx), {})
        lines = [
            f"PhysicalDrive{idx} | {disk.get('Model', '未知型号')} | {human_size(disk.get('Size'))}",
            f"介质类型：{item.get('drive_type', '待识别')}；健康状态：{item.get('health', '待检测')}",
            f"健康评分：{item.get('score') if item.get('score') is not None else '数据不足'}；风险等级：{item.get('risk_level', '待检测')}",
            f"温度：{item.get('temperature') if item.get('temperature') is not None else '未知'}℃；厂商报告已用寿命：{item.get('wear') if item.get('wear') is not None else '未知'}%",
            f"SSD 剩余耐久度：{item.get('wear_remaining_percent') if item.get('wear_remaining_percent') is not None else '设备未提供/无法可靠计算'}",
            "",
            "诊断结论：",
            item.get("diagnostic_summary") or item.get("error") or "尚未取得 SMART 诊断数据。",
            "",
            "风险提示：",
        ]
        lines.extend("• " + str(x) for x in item.get("warnings", []))
        lines.extend("• " + str(x) for x in item.get("history_alerts", []))
        if item.get("error"):
            lines.append("SMART 读取原因：" + str(item["error"])[:1200])
        lines.extend(["", "逐项判断与建议："])
        for rule in item.get("diagnostic_rules", []):
            lines.append(f"• {rule.get('title')}：{rule.get('level')}；{rule.get('evidence')}；建议：{rule.get('recommendation')}")
        self.overview_detail.configure(state="normal")
        self.overview_detail.delete("1.0", "end")
        self.overview_detail.insert("end", "\n".join(lines))
        self.overview_detail.configure(state="disabled")
        if hasattr(self, "report_preview"):
            self.report_preview.configure(state="normal")
            self.report_preview.delete("1.0", "end")
            self.report_preview.insert("end", "\n".join(lines))
            self.report_preview.configure(state="disabled")

    def _render_report_center(self):
        if not hasattr(self, "report_preview"):
            return
        report = self.last_all_smart_report or {}
        results = report.get("results", []) if isinstance(report, dict) else []
        if not results:
            self.report_status_var.set("尚无全部硬盘检测结果。先点击“检测全部硬盘”，再生成报告。")
            return
        self.report_status_var.set(f"最近一次全部硬盘 SMART 检测：{report.get('created_at', '时间未知')}；共 {len(results)} 块。")
        lines = ["最近一次全部硬盘诊断摘要：", ""]
        for item in results:
            score = f"{item.get('score')}/100" if item.get("score") is not None else "数据不足"
            lines.append(f"PhysicalDrive{item.get('disk_index')} | {item.get('model')} | {item.get('drive_type', '未知')} | {item.get('risk_level', item.get('health', '未知'))} | {score}")
            if item.get("diagnostic_summary"):
                lines.append("  " + item["diagnostic_summary"])
            for warning in item.get("warnings", []):
                lines.append("  风险提示：" + str(warning))
            for alert in item.get("history_alerts", []):
                lines.append("  趋势变化：" + str(alert))
            if item.get("error"):
                lines.append("  SMART 读取失败：" + str(item["error"])[:500])
        self.report_preview.configure(state="normal")
        self.report_preview.delete("1.0", "end")
        self.report_preview.insert("end", "\n".join(lines))
        self.report_preview.configure(state="disabled")

    def export_all_report(self):
        report = self.last_all_smart_report or {}
        results = report.get("results", []) if isinstance(report, dict) else []
        if not results:
            messagebox.showwarning("暂无报告数据", "请先点击“全部硬盘 SMART 检测”，取得每块硬盘的检测结果。")
            return
        disks_payload = []
        for disk in self.disks:
            idx = int(disk.get("Index", 0))
            identity_key, _ = disk_identity(disk)
            item = next((x for x in results if x.get("identity_key") == identity_key), {})
            try:
                history = self.history_store.get_history(disk, limit=20)
                self_tests = self.history_store.get_self_test_history(disk, limit=50)
            except Exception as exc:
                history, self_tests = [], []
                item = dict(item)
                item["history_error"] = str(exc)
            serial = str(disk.get("SerialNumber") or "")
            serial_masked = ("*" * max(0, len(serial) - 4) + serial[-4:]) if serial else "未提供"
            disks_payload.append({
                "disk_index": idx, "model": disk.get("Model"), "capacity": human_size(disk.get("Size")),
                "drive_letter": disk_volume_labels(disk), "serial_number_masked": serial_masked,
                "interface": disk.get("InterfaceType"), "status": disk.get("Status"),
                "smart_diagnosis": item, "health_history": history, "self_test_history": self_tests,
            })
        payload = {
            "software": APP_NAME, "version": APP_VERSION,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "smart_check_created_at": report.get("created_at"),
            "disk_count": len(self.disks), "disks": disks_payload,
            "safety_note": "报告中的 SMART 与扫描信息仅代表采集时设备提供的数据；读取失败不等于物理坏道，慢速区块不等于确认坏道。软件不会自动修复或写入测试数据。",
        }
        path = filedialog.asksaveasfilename(
            title="保存全部硬盘诊断报告", defaultextension=".html",
            filetypes=[("HTML 报告", "*.html"), ("JSON 数据", "*.json")],
            initialfile=f"硬盘健康总报告_{datetime.now():%Y%m%d_%H%M%S}.html")
        if not path:
            return
        try:
            ext = os.path.splitext(path)[1].lower()
            body = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
            if ext == ".json":
                with open(path, "w", encoding="utf-8") as f:
                    f.write(body)
            else:
                escaped = body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                cards = []
                esc = lambda value: str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                for item in disks_payload:
                    d = item["smart_diagnosis"]
                    score = f"{d.get('score')}/100" if d.get("score") is not None else "数据不足"
                    cards.append(
                        f"<section><h2>PhysicalDrive{item['disk_index']} · {esc(item.get('model') or '未知型号')}</h2>"
                        f"<p>容量：{esc(item['capacity'])}　介质：{esc(d.get('drive_type', '未知'))}　"
                        f"风险：{esc(d.get('risk_level', d.get('health', '未知')))}　评分：{score}</p>"
                        f"<p>{esc(d.get('diagnostic_summary', d.get('error', '尚无诊断结论')))}</p></section>")
                html_doc = (
                    "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
                    "<title>硬盘健康卫士 - 全部硬盘诊断报告</title>"
                    "<style>body{font-family:'Microsoft YaHei',sans-serif;margin:32px;color:#243447;background:#f5f7fa}"
                    "h1{color:#17365d}section{background:#fff;padding:18px;margin:14px 0;border-radius:8px}"
                    "pre{white-space:pre-wrap;word-break:break-word;background:#fff;padding:18px;border-radius:8px}"
                    ".note{color:#8a5a00}</style></head><body>"
                    "<h1>硬盘健康卫士 - 全部硬盘诊断报告</h1>"
                    f"<p>生成时间：{payload['generated_at']}；版本：{APP_VERSION}</p>"
                    "<p class='note'>风险评分仅依据已取得的关键 SMART 证据；数据不足不会伪造评分。读取错误不一定等于物理坏道。</p>"
                    + "".join(cards) + "<h2>完整数据与证据</h2><pre>" + escaped + "</pre></body></html>")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(html_doc)
            self.report_status_var.set(f"报告已保存：{path}")
            self._log(f"全部硬盘诊断报告已导出：{path}")
            messagebox.showinfo("导出成功", f"全部硬盘诊断报告已保存：\n{path}")
        except Exception as exc:
            messagebox.showerror("报告导出失败", str(exc))

'''
patch_once(
    "    def _poll_events(self):\n",
    methods + "    def _poll_events(self):\n",
    "新增总览渲染与报告导出方法"
)

# Refresh overview when disks are enumerated and when the all-drive SMART pass finishes.
patch_once(
    '                    if self.disks:\n                        first = str(self.disks[0].get("Index", 0))\n',
    '                    self._render_health_overview()\n'
    '                    if self.disks:\n                        first = str(self.disks[0].get("Index", 0))\n',
    "硬盘列表更新总览"
)
patch_once(
    '                    self.last_all_smart_report = {\n                        "created_at": datetime.now().isoformat(timespec="seconds"),\n                        "results": payload,\n                    }\n',
    '                    self.last_all_smart_report = {\n                        "created_at": datetime.now().isoformat(timespec="seconds"),\n                        "results": payload,\n                    }\n'
    '                    self._render_health_overview()\n',
    "全部 SMART 完成后刷新总览与报告中心"
)

main_path.write_text(source, encoding="utf-8-sig", newline="")
print("v0.5.0 健康总览、逐盘风险摘要和全部硬盘 HTML/JSON 报告补丁已应用。")
