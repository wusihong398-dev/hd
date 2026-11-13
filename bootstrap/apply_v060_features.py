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
source = main_path.read_text(encoding="utf-8-sig")

def patch_once(old: str, new: str, label: str) -> None:
    global source
    if new in source:
        return
    if old not in source:
        raise SystemExit(f"v0.6.0 补丁定位失败：{label}")
    source = source.replace(old, new, 1)

# Release version.
source, n = re.subn(r'(?m)^APP_VERSION\s*=\s*["\'][^"\']+["\']',
                    'APP_VERSION = "0.6.0"', source, count=1)
if n != 1:
    raise SystemExit("无法安全更新 APP_VERSION。")

# Extend existing trend metrics without replacing or migrating the v0.5.0 history schema.
helpers = r'''
AUTO_CHECK_TASK_NAME = "DiskHealthGuard-AutoCheck"
AUTO_CHECK_HELPER_NAME = "硬盘健康卫士自动检测.exe"
ALERT_COOLDOWN_HOURS = 6

HISTORY_METRICS.update({
    "nvme_critical_warning": "NVMe 严重警告标志",
})

def scan_cell_byte_range(cell_index, total_bytes, cell_count=SCAN_GRID_CELLS):
    """将热力图单元映射为物理盘字节区间；范围是显示区间，不冒充扇区级精确地址。"""
    try:
        index = int(cell_index)
        total = int(total_bytes)
        count = int(cell_count)
    except (TypeError, ValueError):
        raise ValueError("扫描区块索引或容量不是有效数字。")
    if count <= 0 or total < 0 or index < 0 or index >= count:
        raise ValueError("扫描区块索引或容量超出有效范围。")
    return (index * total // count, (index + 1) * total // count)

def alert_cooldown_due(last_notified_at, now=None, cooldown_hours=ALERT_COOLDOWN_HOURS):
    """同一硬盘同一证据指纹在冷却期内不重复通知。"""
    if not last_notified_at:
        return True
    current = now or datetime.now()
    try:
        previous = datetime.fromisoformat(str(last_notified_at))
        if previous.tzinfo is not None and current.tzinfo is None:
            previous = previous.replace(tzinfo=None)
        elif previous.tzinfo is None and current.tzinfo is not None:
            current = current.replace(tzinfo=None)
        return (current - previous).total_seconds() >= float(cooldown_hours) * 3600
    except (TypeError, ValueError, OverflowError):
        return True

def actionable_health_alerts(item):
    """只返回有明确风险证据的提醒；透传失败、数据不足和首次非零 CRC 不当作介质故障。"""
    if not isinstance(item, dict) or item.get("error"):
        return []
    messages = []
    level = str(item.get("risk_level") or "")
    health = str(item.get("health") or "")
    if level in ("警告", "严重"):
        summary = str(item.get("diagnostic_summary") or "").strip()
        messages.append(f"{level}风险：{summary or '请查看逐项 SMART 诊断证据。'}")
    if health == "异常":
        messages.append("SMART 自检报告异常，请优先备份重要数据并复核。")
    for alert in item.get("history_alerts", []) or []:
        text = str(alert).strip()
        if not text or "无历史" in text:
            continue
        if any(word in text for word in ("增加", "变为", "严重警告", "达到通用高温提醒线", "已用寿命指标")):
            messages.append(text)
    # Keep order but remove duplicate messages.
    return list(dict.fromkeys(messages))

def build_auto_check_task_args(task_command, task_name=AUTO_CHECK_TASK_NAME):
    if not isinstance(task_command, str) or not task_command.strip():
        raise ValueError("自动检测任务命令不能为空。")
    if not isinstance(task_name, str) or not task_name.strip() or '"' in task_name:
        raise ValueError("计划任务名称无效。")
    return [
        "schtasks.exe", "/Create", "/SC", "ONLOGON", "/TN", task_name,
        "/TR", task_command, "/F", "/RL", "LIMITED", "/IT",
    ]

def auto_check_task_command():
    """优先使用无管理员清单的辅助 EXE，避免登录自动检测触发 UAC。"""
    if getattr(sys, "frozen", False):
        helper = os.path.join(app_dir(), AUTO_CHECK_HELPER_NAME)
        executable = helper if os.path.isfile(helper) else sys.executable
        return f'"{executable}" --auto-check'
    script = os.path.abspath(sys.argv[0])
    return f'"{sys.executable}" "{script}" --auto-check'

def auto_check_task_exists():
    if os.name != "nt":
        return False
    try:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        result = subprocess.run(
            ["schtasks.exe", "/Query", "/TN", AUTO_CHECK_TASK_NAME],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=12, creationflags=creationflags,
        )
        return result.returncode == 0
    except Exception:
        return False

def set_auto_check_task(enabled):
    if os.name != "nt":
        return False, "开机自动检测仅支持 Windows。"
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        if enabled:
            args = build_auto_check_task_args(auto_check_task_command())
        else:
            args = ["schtasks.exe", "/Delete", "/TN", AUTO_CHECK_TASK_NAME, "/F"]
        result = subprocess.run(
            args, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=20, creationflags=creationflags,
        )
        output = (result.stdout or result.stderr or "").strip()
        return result.returncode == 0, output or ("已启用" if enabled else "已关闭")
    except Exception as exc:
        return False, str(exc)

def show_windows_balloon(root, title, message, warning=True):
    """通过 Windows 通知区域气泡提醒；失败时由调用方回退到应用内对话框。"""
    if os.name != "nt":
        return False
    try:
        class NOTIFYICONDATAW(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("hWnd", wintypes.HWND),
                ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT),
                ("uCallbackMessage", wintypes.UINT),
                ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128),
                ("dwState", wintypes.DWORD),
                ("dwStateMask", wintypes.DWORD),
                ("szInfo", wintypes.WCHAR * 256),
                ("uTimeoutOrVersion", wintypes.UINT),
                ("szInfoTitle", wintypes.WCHAR * 64),
                ("dwInfoFlags", wintypes.DWORD),
            ]
        data = NOTIFYICONDATAW()
        data.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        data.hWnd = root.winfo_id()
        data.uID = 1
        data.uFlags = 0x00000002 | 0x00000004  # NIF_ICON | NIF_TIP
        data.hIcon = ctypes.windll.user32.LoadIconW(None, ctypes.c_void_p(32512))
        data.szTip = "硬盘健康卫士"
        shell = ctypes.windll.shell32
        if not shell.Shell_NotifyIconW(0, ctypes.byref(data)):  # NIM_ADD
            return False
        data.uFlags = 0x00000010  # NIF_INFO
        data.szInfoTitle = str(title)[:63]
        data.szInfo = str(message)[:255]
        data.dwInfoFlags = 0x00000002 if warning else 0x00000001
        shell.Shell_NotifyIconW(1, ctypes.byref(data))  # NIM_MODIFY
        root.after(12000, lambda d=data: shell.Shell_NotifyIconW(2, ctypes.byref(d)))  # NIM_DELETE
        return True
    except Exception:
        return False

def format_trend_delta(metric_key, points):
    if len(points) < 2:
        return "历史记录不足：至少需要两次有效采集才能比较变化。"
    before = _as_number(points[-2][1])
    after = _as_number(points[-1][1])
    if before is None or after is None:
        return "本次指标缺失，无法计算变化量。"
    delta = after - before
    counters = {
        "reallocated_sectors", "pending_sectors", "offline_uncorrectable",
        "reported_uncorrectable", "crc_errors", "nvme_media_errors",
        "nvme_critical_warning", "surface_read_error_blocks",
    }
    if metric_key in counters and delta < 0:
        return f"累计计数器从 {before:g} 回退到 {after:g}；可能是设备重置或数据来源变化，请核对设备身份，不按负增长判定健康。"
    if delta > 0:
        change = f"增加 {delta:g}"
    elif delta < 0:
        change = f"减少 {abs(delta):g}"
    else:
        change = "无变化"
    return f"上次 {before:g} → 本次 {after:g}；{change}。仅表示采集值变化，不单独构成故障结论。"

def generate_pdf_report(path, payload):
    """生成简体中文 PDF；使用 ReportLab CID 字体，不依赖机器上的字体文件。"""
    from xml.sax.saxutils import escape
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
    )

    font_name = "STSong-Light"
    if font_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont(font_name))
    title_style = ParagraphStyle(
        "HDGTitleCN", fontName=font_name, fontSize=18, leading=25,
        alignment=TA_CENTER, spaceAfter=12,
    )
    heading_style = ParagraphStyle(
        "HDGHeadingCN", fontName=font_name, fontSize=13, leading=19,
        spaceBefore=8, spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "HDGBodyCN", fontName=font_name, fontSize=8.5, leading=13,
        wordWrap="CJK", spaceAfter=3,
    )
    small_style = ParagraphStyle(
        "HDGSmallCN", fontName=font_name, fontSize=7.5, leading=11,
        wordWrap="CJK",
    )
    def para(value, style=body_style):
        text = escape(str(value if value is not None else "未提供")).replace("\n", "<br/>")
        return Paragraph(text, style)

    doc = SimpleDocTemplate(
        str(path), pagesize=A4, rightMargin=34, leftMargin=34,
        topMargin=42, bottomMargin=42, title="硬盘健康卫士诊断报告",
        author="硬盘健康卫士",
    )
    story = [
        Paragraph("硬盘健康卫士 · 硬盘诊断报告", title_style),
        para(f"生成时间：{payload.get('generated_at', '未知')}　软件版本：{payload.get('version', APP_VERSION)}"),
        para(f"物理硬盘数量：{payload.get('disk_count', len(payload.get('disks', [])))}"),
        para("安全说明：本报告仅反映采集时设备提供的数据。SMART 读取失败不等于物理坏道；慢速区块不等于确认坏道。软件不会自动修复、写零、格式化、擦除或重映射。"),
        Spacer(1, 8),
    ]
    disks = payload.get("disks", []) or []
    for index, disk in enumerate(disks):
        diagnosis = disk.get("smart_diagnosis") or {}
        score = diagnosis.get("score")
        story.append(Paragraph(
            f"PhysicalDrive{disk.get('disk_index')} · {escape(str(disk.get('model') or '未知型号'))}",
            heading_style,
        ))
        summary_rows = [
            [para("项目"), para("采集结果")],
            [para("容量 / 盘符"), para(f"{disk.get('capacity', '未知')} / {disk.get('drive_letter', '未知')}")],
            [para("介质类型"), para(diagnosis.get("drive_type", "未知"))],
            [para("健康 / 风险等级"), para(f"{diagnosis.get('health', '未知')} / {diagnosis.get('risk_level', diagnosis.get('health', '未知'))}")],
            [para("健康评分"), para(f"{score}/100" if score is not None else "数据不足")],
            [para("温度 / 通电小时"), para(f"{diagnosis.get('temperature', '未知')} °C / {diagnosis.get('hours', '未知')}")],
            [para("SSD 剩余耐久度"), para(diagnosis.get("wear_remaining_percent", "设备未提供/无法可靠计算"))],
            [para("序列号（脱敏）"), para(disk.get("serial_number_masked", "未提供"))],
        ]
        table = Table(summary_rows, colWidths=[125, 390], repeatRows=1)
        table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), font_name),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8F0FA")),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#C8D2DF")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.extend([table, Spacer(1, 7), Paragraph("诊断结论与风险提示", heading_style)])
        story.append(para(diagnosis.get("diagnostic_summary") or diagnosis.get("error") or "尚无诊断结论"))
        for warning in diagnosis.get("warnings", []) or []:
            story.append(para("SMART 提示：" + str(warning)))
        for alert in diagnosis.get("history_alerts", []) or []:
            story.append(para("历史变化：" + str(alert)))
        if diagnosis.get("diagnostic_rules"):
            story.append(Paragraph("逐项诊断依据", heading_style))
            for rule in diagnosis.get("diagnostic_rules", []):
                story.append(para(
                    f"{rule.get('title', '诊断项目')}｜{rule.get('level', '未知')}｜"
                    f"{rule.get('evidence', '无证据说明')}｜建议：{rule.get('recommendation', '无')}"
                ))
        metrics = diagnosis.get("smart_metrics") or {}
        if metrics:
            story.append(Paragraph("SMART 指标", heading_style))
            for key, value in metrics.items():
                story.append(para(f"{key}：{value}"))
        attributes = diagnosis.get("smart_attributes") or []
        if attributes:
            story.append(Paragraph(f"SMART 属性（{len(attributes)} 项）", heading_style))
            for attr in attributes[:80]:
                story.append(para(
                    f"ID {attr.get('id', '—')}｜{attr.get('name', '未知')}｜"
                    f"当前值 {attr.get('value', '—')}｜原始值 {attr.get('raw', '—')}",
                    small_style,
                ))
        history = disk.get("health_history") or []
        if history:
            story.append(Paragraph(f"历史趋势记录（最近 {min(len(history), 30)} 条）", heading_style))
            for row in history[-30:]:
                if row.get("record_type") == "surface_scan":
                    story.append(para(
                        f"{row.get('captured_at', '')}｜只读扫描｜覆盖 "
                        f"{row.get('scanned_bytes', 0)}/{row.get('total_bytes', 0)} 字节｜"
                        f"读取错误 {row.get('error_blocks', 0)}｜{'已停止' if row.get('stopped') else '完成'}",
                        small_style,
                    ))
                else:
                    m = row.get("metrics") or {}
                    story.append(para(
                        f"{row.get('captured_at', '')}｜{row.get('health', '未知')}｜"
                        f"温度 {m.get('temperature', '—')}°C｜通电 {m.get('power_on_hours', '—')} 小时｜"
                        f"重映射 {m.get('reallocated_sectors', '—')}｜待映射 {m.get('pending_sectors', '—')}",
                        small_style,
                    ))
        tests = disk.get("self_test_history") or []
        if tests:
            story.append(Paragraph("SMART 自检历史", heading_style))
            for row in tests[:30]:
                story.append(para(
                    f"{row.get('started_at', '')}｜{row.get('test_type', '未知')}｜"
                    f"{row.get('status', '未知')}｜{row.get('result_text', '')}",
                    small_style,
                ))
        scans = [row for row in history if row.get("record_type") == "surface_scan"]
        if scans:
            story.append(Paragraph("只读扫描限制", heading_style))
            story.append(para("扫描记录仅说明本次实际读取范围。已停止扫描的未覆盖区段不能视为正常；读取错误需结合复测、SMART 和连接状态复核。"))
        if index < len(disks) - 1:
            story.append(PageBreak())

    def footer(canvas, _doc):
        canvas.saveState()
        canvas.setFont(font_name, 8)
        canvas.drawString(34, 22, f"硬盘健康卫士 v{payload.get('version', APP_VERSION)} · 本地诊断报告")
        canvas.drawRightString(A4[0] - 34, 22, f"第 {canvas.getPageNumber()} 页")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return str(path)
'''
patch_once(
    "class DiskHealthApp:\n",
    helpers + "\nclass DiskHealthApp:\n",
    "新增趋势、通知、任务和 PDF 通用函数"
)

# Extend the history database additively; existing tables and records are untouched.
store_methods = r'''    def ensure_alert_table(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS health_alerts (
                    identity_key TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    last_notified_at TEXT NOT NULL,
                    occurrences INTEGER NOT NULL DEFAULT 1,
                    acknowledged INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(identity_key, fingerprint)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_health_alerts_seen ON health_alerts(last_seen_at)")

    def record_alert_if_due(self, disk, level, message, now=None, cooldown_hours=ALERT_COOLDOWN_HOURS):
        identity_key, _quality = disk_identity(disk)
        stamp = (now or datetime.now()).isoformat(timespec="seconds")
        fingerprint = hashlib.sha256((str(level) + "\\0" + str(message)).encode("utf-8")).hexdigest()
        self.ensure_alert_table()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT last_notified_at FROM health_alerts WHERE identity_key=? AND fingerprint=?",
                (identity_key, fingerprint),
            ).fetchone()
            due = alert_cooldown_due(row["last_notified_at"] if row else None, now=now, cooldown_hours=cooldown_hours)
            if row:
                conn.execute("""
                    UPDATE health_alerts
                    SET last_seen_at=?, occurrences=occurrences+1,
                        last_notified_at=CASE WHEN ? THEN ? ELSE last_notified_at END,
                        acknowledged=CASE WHEN ? THEN 0 ELSE acknowledged END
                    WHERE identity_key=? AND fingerprint=?
                """, (stamp, int(due), stamp, int(due), identity_key, fingerprint))
            else:
                conn.execute("""
                    INSERT INTO health_alerts(
                        identity_key,fingerprint,level,message,first_seen_at,last_seen_at,
                        last_notified_at,occurrences,acknowledged
                    ) VALUES(?,?,?,?,?,?,?,1,0)
                """, (identity_key, fingerprint, str(level), str(message), stamp, stamp, stamp))
                due = True
        return due

    def get_alert_history(self, limit=200):
        self.ensure_alert_table()
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT identity_key,fingerprint,level,message,first_seen_at,last_seen_at,
                       last_notified_at,occurrences,acknowledged
                FROM health_alerts ORDER BY last_seen_at DESC LIMIT ?
            """, (int(limit),)).fetchall()
        return [dict(row) for row in rows]

    def acknowledge_alert(self, identity_key, fingerprint):
        self.ensure_alert_table()
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE health_alerts SET acknowledged=1 WHERE identity_key=? AND fingerprint=?",
                (str(identity_key), str(fingerprint)),
            )
        return cursor.rowcount > 0

'''
patch_once(
    "    def get_self_test_history(self, disk, limit=50):\n",
    store_methods + "    def get_self_test_history(self, disk, limit=50):\n",
    "为现有健康数据库增加独立提醒表"
)

# Initialize opt-in auto-check state and alert storage.
patch_once(
    "    def __init__(self, root):\n        self.root = root\n",
    "    def __init__(self, root, auto_check=False):\n"
    "        self.root = root\n"
    "        self.auto_check_mode = bool(auto_check)\n"
    "        self.auto_check_started = False\n"
    "        self.scan_grid_total_bytes = 0\n"
    "        self.scan_grid_scanned_bytes = 0\n"
    "        self.alert_rows = []\n",
    "应用初始化参数和自动检测状态"
)
patch_once(
    "        self.history_store = HealthHistoryStore()\n        self.history_records = []\n",
    "        self.history_store = HealthHistoryStore()\n"
    "        self.alert_store_error = None\n"
    "        try:\n"
    "            self.history_store.ensure_alert_table()\n"
    "        except Exception as exc:\n"
    "            self.alert_store_error = str(exc)\n"
    "        self.history_records = []\n",
    "初始化风险提醒表"
)
patch_once(
    "        self._build_ui()\n        self.root.after(150, self._poll_events)\n",
    "        self._build_ui()\n"
    "        self.refresh_alert_history()\n"
    "        if self.auto_check_mode:\n"
    "            self.root.after(600, self.root.iconify)\n"
    "        self.root.after(150, self._poll_events)\n",
    "初始化提醒列表和自动检测窗口状态"
)

# Add two focused tabs while preserving all existing tabs.
patch_once(
    '        report_tab = ttk.Frame(self.notebook, padding=8)\n',
    '        report_tab = ttk.Frame(self.notebook, padding=8)\n'
    '        alert_tab = ttk.Frame(self.notebook, padding=8)\n'
    '        settings_tab = ttk.Frame(self.notebook, padding=8)\n',
    "新增风险提醒与自动检测设置页面"
)
patch_once(
    '        self.report_tab = report_tab\n',
    '        self.report_tab = report_tab\n'
    '        self.alert_tab = alert_tab\n'
    '        self.settings_tab = settings_tab\n',
    "保存新增页面引用"
)
patch_once(
    '        self.notebook.add(report_tab, text="报告中心")\n',
    '        self.notebook.add(report_tab, text="报告中心")\n'
    '        self.notebook.add(alert_tab, text="风险提醒")\n'
    '        self.notebook.add(settings_tab, text="自动检测设置")\n',
    "注册新增页面"
)

# Risk distribution cards in the overview.
patch_once(
    '        ttk.Label(overview_head, textvariable=self.overview_summary_var,\n'
    '                  font=("Microsoft YaHei UI", 10, "bold"), wraplength=900).pack(anchor="w")\n',
    '        ttk.Label(overview_head, textvariable=self.overview_summary_var,\n'
    '                  font=("Microsoft YaHei UI", 10, "bold"), wraplength=900).pack(anchor="w")\n'
    '        risk_cards = ttk.Frame(overview_tab)\n'
    '        risk_cards.pack(fill="x", pady=(0, 8))\n'
    '        self.risk_count_vars = {}\n'
    '        for label, color in (("严重", "#b42318"), ("警告", "#c2410c"), ("关注", "#a36a00"),\n'
    '                              ("良好", "#16804a"), ("数据不足", "#68788a"), ("无法读取", "#68788a")):\n'
    '            card = ttk.LabelFrame(risk_cards, text=label, padding=(8, 4))\n'
    '            card.pack(side="left", fill="x", expand=True, padx=(0, 5))\n'
    '            value = tk.StringVar(value="0")\n'
    '            self.risk_count_vars[label] = value\n'
    '            ttk.Label(card, textvariable=value, font=("Microsoft YaHei UI", 15, "bold"), foreground=color).pack(anchor="center")\n',
    "增加健康风险分布卡片"
)

# Add PDF action beside existing HTML/JSON report action.
patch_once(
    '        ttk.Button(report_head, text="生成全部硬盘 HTML / JSON 报告",\n'
    '                   command=self.export_all_report).pack(anchor="w", pady=(9, 0))\n',
    '        report_actions = ttk.Frame(report_head)\n'
    '        report_actions.pack(anchor="w", pady=(9, 0))\n'
    '        ttk.Button(report_actions, text="生成全部硬盘 HTML / JSON 报告",\n'
    '                   command=self.export_all_report).pack(side="left")\n'
    '        ttk.Button(report_actions, text="导出全部硬盘 PDF",\n'
    '                   command=self.export_pdf_report).pack(side="left", padx=7)\n'
    '        ttk.Button(report_actions, text="导出当前硬盘 PDF",\n'
    '                   command=lambda: self.export_pdf_report(single_only=True)).pack(side="left", padx=7)\n',
    "报告中心增加 PDF 导出"
)

# Scan grid interaction and detail text.
patch_once(
    '        self.scan_grid = tk.Canvas(scan_tab, height=190, bg="#f7f9fc",\n',
    '        self.scan_grid = tk.Canvas(scan_tab, height=235, bg="#f7f9fc",\n',
    "热力图完整显示 800 个单元格"
)
patch_once(
    '        self.scan_grid.pack(fill="x", pady=(2, 8))\n',
    '        self.scan_grid.pack(fill="x", pady=(2, 4))\n'
    '        self.scan_grid.bind("<Button-1>", self._on_scan_grid_click)\n'
    '        self.scan_grid_detail_var = tk.StringVar(value="点击扫描网格中的任意区块，可查看对应字节范围和已记录的异常位置。")\n'
    '        ttk.Label(scan_tab, textvariable=self.scan_grid_detail_var, foreground="#52657c",\n'
    '                  wraplength=900).pack(anchor="w", pady=(0, 6))\n',
    "扫描热力图增加点击定位"
)

# Trend delta summary beneath the existing historical chart.
patch_once(
    '        self.history_canvas.bind("<Configure>", lambda _e: self._draw_history_chart())\n',
    '        self.history_canvas.bind("<Configure>", lambda _e: self._draw_history_chart())\n'
    '        self.history_delta_var = tk.StringVar(value="选择指标后显示最近两次有效采集的变化量。")\n'
    '        ttk.Label(history_tab, textvariable=self.history_delta_var, foreground="#52657c",\n'
    '                  wraplength=900).pack(anchor="w", pady=(0, 7))\n',
    "趋势图增加最近两次变化摘要"
)

# Risk alert history UI.
alert_ui = r'''        alert_toolbar = ttk.Frame(alert_tab)
        alert_toolbar.pack(fill="x", pady=(0, 8))
        ttk.Label(alert_toolbar, text="只记录有明确证据的风险提醒；相同设备和相同证据在 6 小时冷却期内不重复通知。",
                  foreground="#52657c", wraplength=760).pack(side="left", fill="x", expand=True)
        ttk.Button(alert_toolbar, text="刷新提醒", command=self.refresh_alert_history).pack(side="right", padx=4)
        ttk.Button(alert_toolbar, text="标记已查看", command=self._acknowledge_selected_alert).pack(side="right", padx=4)
        self.alert_notice_var = tk.StringVar(value="暂无风险提醒。")
        ttk.Label(alert_tab, textvariable=self.alert_notice_var, foreground="#68788a").pack(anchor="w", pady=(0, 6))
        alert_cols = ("time", "level", "message", "count", "ack")
        self.alert_tree = ttk.Treeview(alert_tab, columns=alert_cols, show="headings", height=18)
        for col, title, width in (
            ("time", "最近出现时间", 150), ("level", "等级", 75),
            ("message", "风险证据 / 提醒内容", 560), ("count", "出现次数", 75),
            ("ack", "查看状态", 85),
        ):
            self.alert_tree.heading(col, text=title)
            self.alert_tree.column(col, width=width, anchor="w")
        self.alert_tree.tag_configure("danger", foreground="#b42318")
        self.alert_tree.tag_configure("attention", foreground="#a36a00")
        self.alert_tree.pack(fill="both", expand=True)

        settings_head = ttk.LabelFrame(settings_tab, text="登录 Windows 后自动检测", padding=12)
        settings_head.pack(fill="x", pady=(0, 10))
        ttk.Label(settings_head,
                  text="默认关闭。启用后，仅在当前 Windows 用户登录时运行无管理员权限的自动检测辅助程序；不会执行全盘坏道扫描、修复或写入操作。",
                  wraplength=900, foreground="#52657c").pack(anchor="w")
        self.auto_check_var = tk.BooleanVar(value=auto_check_task_exists())
        ttk.Checkbutton(settings_head, text="启用登录后自动读取全部硬盘 SMART",
                        variable=self.auto_check_var, command=self._toggle_auto_check).pack(anchor="w", pady=(10, 4))
        ttk.Label(settings_head, text="自动检测辅助程序与主程序放在同一目录。个别硬盘若需要管理员权限，自动检测会如实显示读取受限，不会把它判为硬盘损坏。",
                  foreground="#8a5a00", wraplength=900).pack(anchor="w", pady=(3, 8))
        settings_actions = ttk.Frame(settings_head)
        settings_actions.pack(anchor="w")
        ttk.Button(settings_actions, text="测试 Windows 通知", command=self._test_notification).pack(side="left")
        ttk.Button(settings_actions, text="立即检测全部硬盘", command=self.start_all_smart_check).pack(side="left", padx=7)
'''
patch_once(
    '        self.report_preview.configure(state="disabled")\n\n        diag_head = ttk.LabelFrame(diagnostics_tab, text="本盘智能诊断结论", padding=10)\n',
    '        self.report_preview.configure(state="disabled")\n\n' + alert_ui + '\n'
    '        diag_head = ttk.LabelFrame(diagnostics_tab, text="本盘智能诊断结论", padding=10)\n',
    "构建风险提醒和自动检测设置界面"
)

# Update risk counts after every overview render.
patch_once(
    '            c = summary["counts"]\n',
    '            c = summary["counts"]\n'
    '            for risk_name, variable in getattr(self, "risk_count_vars", {}).items():\n'
    '                variable.set(str(c.get(risk_name, 0)))\n',
    "刷新风险分布数字"
)

# Show the current trend delta without extrapolating missing values.
patch_once(
    '        if not points:\n'
    '            canvas.create_text(width / 2, height / 2, text="暂无该指标的历史数据。完成一次或多次 SMART 检测后将显示趋势。",\n'
    '                               fill="#7b8794", font=("Microsoft YaHei UI", 10))\n'
    '            return\n',
    '        if not points:\n'
    '            if hasattr(self, "history_delta_var"):\n'
    '                self.history_delta_var.set("暂无该指标的有效历史值；不会用 0 填补缺失数据。")\n'
    '            canvas.create_text(width / 2, height / 2, text="暂无该指标的历史数据。完成一次或多次 SMART 检测后将显示趋势。",\n'
    '                               fill="#7b8794", font=("Microsoft YaHei UI", 10))\n'
    '            return\n'
    '        if hasattr(self, "history_delta_var"):\n'
    '            self.history_delta_var.set(format_trend_delta(key, points))\n',
    "趋势图计算最近两次采集变化"
)

# Add click-to-offset mapping for all 800 scan cells.
methods = r'''    def _on_scan_grid_click(self, event):
        cols, cell_w, cell_h, gap = 40, 13, 8, 3
        x, y = int(event.x), int(event.y)
        if x < 8 or y < 8:
            return
        col = (x - 8) // (cell_w + gap)
        row = (y - 8) // (cell_h + gap)
        if col < 0 or col >= cols:
            return
        index = int(row * cols + col)
        if index < 0 or index >= SCAN_GRID_CELLS:
            return
        total = int(getattr(self, "scan_grid_total_bytes", 0) or 0)
        if total <= 0:
            disk = self.selected_disk()
            total = int((disk or {}).get("Size") or 0)
        if total <= 0:
            self.scan_grid_detail_var.set(f"区块 {index + 1}：尚未取得硬盘容量，无法计算偏移。")
            return
        start, end = scan_cell_byte_range(index, total, SCAN_GRID_CELLS)
        state = self.scan_grid_states[index] if index < len(self.scan_grid_states) else "gray"
        scanned = int(getattr(self, "scan_grid_scanned_bytes", 0) or 0)
        coverage = "未扫描"
        if scanned >= end:
            coverage = "已扫描"
        elif scanned > start:
            coverage = "部分扫描"
        elif not self.scan_running and self.last_report and self.last_report.get("disk_index") == int((self.selected_disk() or {}).get("Index", -1)):
            result = self.last_report.get("result") or {}
            coverage = "已扫描" if int(result.get("scanned", 0)) >= end else "未覆盖"
        details = [f"区块 {index + 1}/{SCAN_GRID_CELLS}", f"状态：{state}", f"覆盖：{coverage}",
                   f"显示范围：字节 {start:,} – {max(start, end - 1):,}", f"范围长度：{max(0, end - start):,} 字节"]
        report = self.last_report or {}
        result = report.get("result") or {}
        if report.get("disk_index") == int((self.selected_disk() or {}).get("Index", -1)):
            cell_end = max(start + 1, end)
            for label, key in (("读取错误", "bad_ranges"), ("复测慢速", "slow_ranges")):
                matches = []
                for item in result.get(key, []) or []:
                    try:
                        r_start = int(item.get("start", 0))
                        r_end = r_start + int(item.get("length", 0))
                    except (TypeError, ValueError):
                        continue
                    if r_start < cell_end and r_end > start:
                        matches.append(item)
                for item in matches[:12]:
                    if key == "bad_ranges":
                        details.append(f"{label}位置：偏移 {item.get('start')}，长度 {item.get('length')}，Windows 错误码 {item.get('win_error')}，4KB 复查错误 {item.get('confirmed_4k_errors', 0)}")
                    else:
                        details.append(f"{label}位置：偏移 {item.get('start')}，长度 {item.get('length')}，首次 {item.get('read_seconds')}s，复测 {item.get('retry_seconds')}s")
        if state == "yellow":
            details.append("说明：黄色表示复测仍慢，不等同于确认坏道。")
        elif state == "red":
            details.append("说明：红色表示扫描读取错误，需结合复测和 SMART 结果判断。")
        elif state == "gray":
            details.append("说明：灰色表示未扫描或没有足够数据，不代表正常。")
        self.scan_grid_detail_var.set("；".join(details))

    def _toggle_auto_check(self):
        enabled = bool(self.auto_check_var.get())
        ok, message = set_auto_check_task(enabled)
        if not ok:
            self.auto_check_var.set(not enabled)
            messagebox.showerror("自动检测设置失败", message)
            return
        self._log("登录自动检测已启用。" if enabled else "登录自动检测已关闭。")
        self.status_var.set("登录自动检测已启用" if enabled else "登录自动检测已关闭")
        messagebox.showinfo("设置已更新", message or ("已启用登录自动检测。" if enabled else "已关闭登录自动检测。"))

    def _test_notification(self):
        title = "硬盘健康卫士通知测试"
        message = "通知功能正常。真实风险提醒只会在检测到明确风险证据时触发。"
        if not show_windows_balloon(self.root, title, message, warning=False):
            messagebox.showinfo(title, message)

    def refresh_alert_history(self):
        if not hasattr(self, "alert_tree"):
            return
        for iid in self.alert_tree.get_children():
            self.alert_tree.delete(iid)
        try:
            self.alert_rows = self.history_store.get_alert_history(limit=300)
            for index, row in enumerate(self.alert_rows):
                level = row.get("level", "关注")
                tag = "danger" if level == "严重" else "attention" if level in ("警告", "关注") else ""
                self.alert_tree.insert(
                    "", "end", iid=str(index),
                    values=(row.get("last_seen_at", ""), level, row.get("message", ""),
                            row.get("occurrences", 1), "已查看" if row.get("acknowledged") else "未查看"),
                    tags=(tag,) if tag else (),
                )
            self.alert_notice_var.set(f"本机保存 {len(self.alert_rows)} 条风险提醒；历史记录不会上传。")
        except Exception as exc:
            self.alert_notice_var.set(f"读取风险提醒历史失败：{exc}")

    def _acknowledge_selected_alert(self):
        selection = self.alert_tree.selection() if hasattr(self, "alert_tree") else ()
        if not selection:
            messagebox.showinfo("请选择提醒", "请先选择一条风险提醒。")
            return
        try:
            row = self.alert_rows[int(selection[0])]
            self.history_store.acknowledge_alert(row["identity_key"], row["fingerprint"])
            self.refresh_alert_history()
        except Exception as exc:
            messagebox.showerror("更新提醒状态失败", str(exc))

    def _notify_health_alerts(self, results, auto_mode=False):
        notifications = []
        for item in results or []:
            messages = actionable_health_alerts(item)
            if not messages:
                continue
            disk = next((d for d in self.disks
                         if int(d.get("Index", -1)) == int(item.get("disk_index", -2))
                         and str(d.get("Model", "")).strip() == str(item.get("model", "")).strip()), None)
            if disk is None:
                continue
            level = item.get("risk_level") or item.get("health") or "关注"
            for message in messages:
                try:
                    if self.history_store.record_alert_if_due(disk, level, message, cooldown_hours=ALERT_COOLDOWN_HOURS):
                        notifications.append(f"PhysicalDrive{item.get('disk_index')} · {item.get('model')}：{message}")
                except Exception as exc:
                    self._log(f"风险提醒保存失败：{exc}")
        self.refresh_alert_history()
        if notifications:
            body = "\n".join(notifications[:4])
            if len(notifications) > 4:
                body += f"\n另有 {len(notifications) - 4} 条提醒，请打开“风险提醒”页面查看。"
            if not show_windows_balloon(self.root, "检测到硬盘健康风险", body, warning=True):
                messagebox.showwarning("检测到硬盘健康风险", body)
        elif auto_mode:
            if not show_windows_balloon(self.root, "硬盘健康卫士自动检测", "本次 SMART 检查未发现需要立即提醒的严重风险。未知或读取受限的硬盘仍需人工复核。", warning=False):
                messagebox.showinfo("自动检测完成", "本次未发现需要立即提醒的严重风险。未知或读取受限的硬盘仍需人工复核。")
        return notifications

    def export_pdf_report(self, single_only=False):
        report = self.last_all_smart_report or {}
        results = report.get("results", []) if isinstance(report, dict) else []
        if not results:
            messagebox.showwarning("暂无报告数据", "请先点击“全部硬盘 SMART 检测”，取得每块硬盘的检测结果。")
            return
        path = filedialog.asksaveasfilename(
            title="保存中文 PDF 诊断报告", defaultextension=".pdf",
            filetypes=[("PDF 报告", "*.pdf")],
            initialfile=f"硬盘健康诊断报告_{datetime.now():%Y%m%d_%H%M%S}.pdf",
        )
        if not path:
            return
        disks_payload = []
        target_disks = list(self.disks)
        if single_only:
            selected = self.selected_disk()
            if not selected:
                messagebox.showwarning("尚未选择硬盘", "请先选择要导出的物理硬盘。")
                return
            target_disks = [selected]
        for disk in target_disks:
            identity_key, _ = disk_identity(disk)
            item = next((x for x in results if x.get("identity_key") == identity_key), {})
            try:
                history = self.history_store.get_history(disk, limit=100)
                self_tests = self.history_store.get_self_test_history(disk, limit=50)
            except Exception as exc:
                history, self_tests = [], []
                item = dict(item)
                item["history_error"] = str(exc)
            serial = str(disk.get("SerialNumber") or "")
            masked = ("*" * max(0, len(serial) - 4) + serial[-4:]) if serial else "未提供"
            disks_payload.append({
                "disk_index": int(disk.get("Index", 0)),
                "model": disk.get("Model", "未知型号"),
                "capacity": human_size(disk.get("Size")),
                "drive_letter": disk_volume_labels(disk),
                "serial_number_masked": masked,
                "smart_diagnosis": item,
                "health_history": history,
                "self_test_history": self_tests,
            })
        payload = {
            "version": APP_VERSION,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "smart_check_created_at": report.get("created_at"),
            "disk_count": len(disks_payload),
            "disks": disks_payload,
        }
        try:
            generate_pdf_report(path, payload)
            self.report_status_var.set(f"中文 PDF 报告已保存：{path}")
            self._log(f"中文 PDF 报告已导出：{path}")
            messagebox.showinfo("PDF 导出成功", f"报告已保存：\n{path}")
        except Exception as exc:
            self._log(f"PDF 报告导出失败：{exc}")
            messagebox.showerror("PDF 导出失败", str(exc))

'''
patch_once(
    "    def _poll_events(self):\n",
    methods + "    def _poll_events(self):\n",
    "新增扫描定位、提醒历史、设置和 PDF 方法"
)

# Allow the explicitly scheduled read-only SMART check to skip the manual confirmation prompt.
patch_once(
    "    def start_all_smart_check(self):\n",
    "    def start_all_smart_check(self, auto_confirm=False):\n",
    "自动检测调用参数"
)
patch_once(
    '        if not messagebox.askyesno(\n            "全部硬盘 SMART 检测",',
    '        if not auto_confirm and not messagebox.askyesno(\n            "全部硬盘 SMART 检测",',
    "自动检测只跳过手动确认，不改变检测方式"
)

# Trigger the opted-in automatic SMART pass only after the disk list has loaded.
patch_once(
    '                        self._resume_self_tests_for_disks()\n',
    '                        self._resume_self_tests_for_disks()\n'
    '                        if self.auto_check_mode and not self.auto_check_started:\n'
    '                            self.auto_check_started = True\n'
    '                            self.root.after(1500, lambda: self.start_all_smart_check(auto_confirm=True))\n',
    "登录自动检测在设备列表加载后启动"
)

# Capture the scan size and progress for the click-to-range mapping.
patch_once(
    '        idx = int(disk.get("Index", 0))\n        size = human_size(disk.get("Size"))\n',
    '        idx = int(disk.get("Index", 0))\n'
    '        self.scan_grid_total_bytes = int(disk.get("Size") or 0)\n'
    '        self.scan_grid_scanned_bytes = 0\n'
    '        size = human_size(disk.get("Size"))\n',
    "扫描启动时记录容量"
)
patch_once(
    '                elif kind == "scan_progress":\n'
    '                    p = payload\n',
    '                elif kind == "scan_progress":\n'
    '                    p = payload\n'
    '                    self.scan_grid_total_bytes = int(p.get("total", self.scan_grid_total_bytes) or 0)\n'
    '                    self.scan_grid_scanned_bytes = int(p.get("scanned", self.scan_grid_scanned_bytes) or 0)\n',
    "扫描进度同步热力图定位范围"
)
patch_once(
    '                    self.last_report = {"type": "surface_scan", "disk_index": idx, "result": result,\n'
    '                                        "created_at": datetime.now().isoformat(timespec="seconds")}\n',
    '                    self.last_report = {"type": "surface_scan", "disk_index": idx, "result": result,\n'
    '                                        "created_at": datetime.now().isoformat(timespec="seconds")}\n'
    '                    self.scan_grid_total_bytes = int(result.get("total", self.scan_grid_total_bytes) or 0)\n'
    '                    self.scan_grid_scanned_bytes = int(result.get("scanned", 0) or 0)\n',
    "扫描结束保存实际覆盖范围"
)

# Notify on explicit evidence, but avoid the generic completion modal during a login-triggered run.
patch_once(
    '                    self.status_var.set("全部硬盘 SMART 检测完成")\n',
    '                    self.status_var.set("全部硬盘 SMART 检测完成")\n'
    '                    was_auto_check = self.auto_check_mode\n'
    '                    self._notify_health_alerts(payload, auto_mode=was_auto_check)\n'
    '                    self.auto_check_mode = False\n',
    "自动检测完成后生成去重提醒"
)
patch_once(
    '                    messagebox.showinfo("检测完成",',
    '                    if not was_auto_check:\n                        messagebox.showinfo("检测完成",',
    "自动检测时隐藏通用完成弹窗"
)

# Switch main entrypoint to accept the scheduler's explicit flag.
patch_once(
    '    app = DiskHealthApp(root)\n',
    '    app = DiskHealthApp(root, auto_check=("--auto-check" in sys.argv[1:]))\n',
    "支持 --auto-check 启动参数"
)

# Create focused regression tests for mapping, alert cooldown, task arguments, database persistence and Chinese PDF output.
test_content = r'''import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from disk_health_inspector import (
    HealthHistoryStore,
    actionable_health_alerts,
    alert_cooldown_due,
    build_auto_check_task_args,
    generate_pdf_report,
    scan_cell_byte_range,
)


class V060MonitoringTests(unittest.TestCase):
    def test_scan_cell_range_maps_exact_proportional_byte_bounds(self):
        self.assertEqual(scan_cell_byte_range(0, 1000, 10), (0, 100))
        self.assertEqual(scan_cell_byte_range(9, 1000, 10), (900, 1000))
        self.assertEqual(scan_cell_byte_range(4, 1001, 10), (400, 500))

    def test_scan_cell_range_rejects_invalid_index(self):
        with self.assertRaises(ValueError):
            scan_cell_byte_range(10, 1000, 10)

    def test_alert_cooldown_is_deterministic(self):
        now = datetime(2026, 1, 1, 12, 0, 0)
        self.assertTrue(alert_cooldown_due(None, now=now))
        self.assertFalse(alert_cooldown_due((now - timedelta(hours=2)).isoformat(), now=now))
        self.assertTrue(alert_cooldown_due((now - timedelta(hours=7)).isoformat(), now=now))

    def test_unknown_or_failed_smart_data_does_not_create_media_alert(self):
        self.assertEqual(actionable_health_alerts({
            "risk_level": "数据不足", "error": "SMART passthrough unsupported",
            "history_alerts": ["NVMe 媒体错误增加：0 → 2"],
        }), [])
        self.assertEqual(actionable_health_alerts({
            "risk_level": "良好",
            "history_alerts": ["接口 CRC 错误计数增加/非零：无历史 → 8"],
        }), [])

    def test_new_evidence_and_serious_risk_are_actionable(self):
        self.assertTrue(actionable_health_alerts({
            "risk_level": "警告", "diagnostic_summary": "待映射扇区数增加"
        }))
        self.assertTrue(actionable_health_alerts({
            "risk_level": "良好",
            "history_alerts": ["待映射扇区数增加：0 → 3"],
        }))

    def test_auto_task_runs_limited_current_user_at_logon(self):
        args = build_auto_check_task_args('"C:\\Program Files\\DiskHealth\\硬盘健康卫士自动检测.exe" --auto-check')
        self.assertIn("/SC", args)
        self.assertEqual(args[args.index("/SC") + 1], "ONLOGON")
        self.assertEqual(args[args.index("/RL") + 1], "LIMITED")
        self.assertIn("/IT", args)
        self.assertIn('"C:\\Program Files\\DiskHealth\\硬盘健康卫士自动检测.exe" --auto-check',
                      args[args.index("/TR") + 1])

    def test_alert_history_is_persistent_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as folder:
            store = HealthHistoryStore(str(Path(folder) / "history.sqlite3"))
            disk = {
                "Index": 0, "Model": "Test SSD", "SerialNumber": "SERIAL-123456",
                "Size": 1024 * 1024 * 1024, "PNPDeviceID": "TEST\\\\DISK0",
            }
            first = datetime(2026, 1, 1, 12, 0, 0)
            self.assertTrue(store.record_alert_if_due(disk, "严重", "待映射扇区增长", now=first))
            self.assertFalse(store.record_alert_if_due(
                disk, "严重", "待映射扇区增长", now=first + timedelta(hours=1)
            ))
            self.assertTrue(store.record_alert_if_due(
                disk, "严重", "待映射扇区增长", now=first + timedelta(hours=7)
            ))
            rows = store.get_alert_history()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["occurrences"], 3)
            self.assertTrue(store.acknowledge_alert(rows[0]["identity_key"], rows[0]["fingerprint"]))
            self.assertEqual(store.get_alert_history()[0]["acknowledged"], 1)

    def test_chinese_pdf_report_has_valid_pdf_header(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "硬盘诊断报告.pdf"
            generate_pdf_report(str(path), {
                "version": "0.6.0",
                "generated_at": "2026-11-14T00:00:00",
                "disk_count": 1,
                "disks": [{
                    "disk_index": 0,
                    "model": "测试 NVMe 固态硬盘",
                    "capacity": "1.00 TB",
                    "drive_letter": "C:",
                    "serial_number_masked": "******1234",
                    "smart_diagnosis": {
                        "health": "正常", "risk_level": "关注", "score": 88,
                        "temperature": 42, "hours": 1000,
                        "diagnostic_summary": "测试报告中文内容。",
                        "smart_metrics": {"nvme_media_errors": 0},
                    },
                    "health_history": [],
                    "self_test_history": [],
                }],
            })
            data = path.read_bytes()
            self.assertTrue(data.startswith(b"%PDF-"))
            self.assertGreater(len(data), 500)


if __name__ == "__main__":
    unittest.main()
'''
test_path = root / "test_v060_monitoring.py"
test_path.write_text(test_content, encoding="utf-8")

main_path.write_text(source, encoding="utf-8-sig", newline="")
print("v0.6.0 风险分布、扫描定位、趋势摘要、去重提醒、登录自动检测和中文 PDF 补丁已应用。")
