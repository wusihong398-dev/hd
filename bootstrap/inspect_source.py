from __future__ import annotations
import ast
from pathlib import Path
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")

root = Path(sys.argv[1]).resolve()
targets = {
    "disk_health_inspector.py": {
        "DiskHealthApp.__init__", "DiskHealthApp._build_ui",
        "DiskHealthApp.refresh_disks", "DiskHealthApp._all_smart_worker",
        "DiskHealthApp._render_diagnostics", "DiskHealthApp._render_smart", "DiskHealthApp._poll_events",
        "DiskHealthApp._render_health_overview", "DiskHealthApp._overview_results",
        "DiskHealthApp._render_report_center", "DiskHealthApp.export_all_report",
        "DiskHealthApp.start_all_smart_check", "DiskHealthApp._load_disks_worker", "DiskHealthApp._all_smart_worker",
        "DiskHealthApp.on_disk_selected", "DiskHealthApp.refresh_history_view",
        "DiskHealthApp._metric", "DiskHealthApp.export_report",
        "DiskHealthApp._draw_scan_grid", "DiskHealthApp._update_scan_grid",
        "DiskHealthApp.start_surface_scan", "DiskHealthApp._finish_scan_ui",
        "DiskHealthApp._draw_history_chart", "DiskHealthApp._history_key_for_metric", "DiskHealthApp._scan_worker",
        "DiskHealthApp._on_overview_select", "DiskHealthApp._render_report_center",
        "DiskHealthApp._on_scan_grid_click", "DiskHealthApp._build_settings_tab",
        "DiskHealthApp._build_trend_tab", "DiskHealthApp._build_alert_tab",
        "DiskHealthApp._schedule_auto_check", "DiskHealthApp._auto_check_complete",
        "DiskHealthApp._notify_health_alerts", "DiskHealthApp.export_pdf_report",
        "DiskHealthApp._load_disks_worker", "DiskHealthApp.start_all_smart_check",
        "HealthHistoryStore.__init__", "HealthHistoryStore._connect", "HealthHistoryStore._initialize", "HealthHistoryStore.record_snapshot",
        "HealthHistoryStore.record_scan", "HealthHistoryStore.get_history",
        "HealthHistoryStore.get_self_test_history",
        "history_metrics_from_summary", "compare_health_snapshots",
        "smart_summary", "smart_attribute_rows", "disk_identity",
    },
    "disk_health_diagnostics.py": {
        "classify_drive", "interpret_smart", "assess_health",
    },
}
for filename, wanted in targets.items():
    path = root / filename
    source = path.read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    if filename == "disk_health_inspector.py":
        print("\\n===== MODULE HEADER =====")
        print("\\n".join(source.splitlines()[:95]))
        print("\\n===== MODULE TAIL =====")
        print("\\n".join(source.splitlines()[-35:]))
        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name) and target.id in {"APP_NAME", "APP_VERSION", "HISTORY_METRICS", "SCAN_GRID_CELLS"}:
                        print(f"GLOBAL {target.id} line={node.lineno}: {ast.get_source_segment(source, node)}")
    print(f"\n===== SOURCE DETAILS {filename} =====")
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    key = f"{node.name}.{child.name}"
                    if key in wanted:
                        print(f"\n--- {key} lines {child.lineno}-{child.end_lineno} ---")
                        print(ast.get_source_segment(source, child))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in wanted:
                print(f"\n--- {node.name} lines {node.lineno}-{node.end_lineno} ---")
                print(ast.get_source_segment(source, node))
