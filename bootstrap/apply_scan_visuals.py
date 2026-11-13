from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
p = root / "disk_health_inspector.py"
s = p.read_text(encoding="utf-8-sig")

def patch(old, new, name):
    global s
    if new in s:
        return
    if old not in s:
        raise SystemExit("扫描可视化补丁定位失败：" + name)
    s = s.replace(old, new, 1)

patch("CHUNK_SIZE = 1024 * 1024\nREFINE_SIZE = 4096\n",
      "CHUNK_SIZE = 1024 * 1024\nREFINE_SIZE = 4096\nSLOW_READ_THRESHOLD_SECONDS = 0.35\nSCAN_GRID_CELLS = 800\n", "常量")
patch("        self.bad_ranges = []\n        self.error_count = 0\n",
      "        self.bad_ranges = []\n        self.slow_ranges = []\n        self.error_count = 0\n        self.slow_count = 0\n", "统计字段")
patch("        start = time.time()\n        try:\n            while scanned < total and not self.stop_event.is_set():",
      "        start = time.time()\n        last_grid_cell = 0\n        last_ui_update = 0.0\n        try:\n            while scanned < total and not self.stop_event.is_set():", "UI节流")
patch("                size = min(CHUNK_SIZE, total - scanned)\n                ok, read_count, err = self._read_at(k32, handle, scanned, size)\n                if not ok:\n",
      "                size = min(CHUNK_SIZE, total - scanned)\n                chunk_started = time.perf_counter()\n                ok, read_count, err = self._read_at(k32, handle, scanned, size)\n                read_seconds = time.perf_counter() - chunk_started\n                block_status = \"green\"\n                if not ok:\n                    block_status = \"red\"\n", "读取计时")
old = '''                        if primary_record is not None:
                            primary_record["confirmed_4k_errors"] = confirmed
                scanned += size
                elapsed = max(time.time() - start, 0.001)
                speed = scanned / elapsed
                self.progress_callback({
                    "scanned": scanned,
                    "total": total,
                    "percent": scanned * 100 / total,
                    "speed": speed,
                    "errors": self.error_count,
                })
            return {
                "scanned": scanned,
                "total": total,
                "errors": self.error_count,
                "bad_ranges": self.bad_ranges,
                "stopped": self.stop_event.is_set(),
                "elapsed": time.time() - start,
            }
'''
new = '''                        if primary_record is not None:
                            primary_record["confirmed_4k_errors"] = confirmed
                if ok and read_seconds >= SLOW_READ_THRESHOLD_SECONDS:
                    retry_started = time.perf_counter()
                    retry_ok, _, retry_err = self._read_at(k32, handle, scanned, size)
                    retry_seconds = time.perf_counter() - retry_started
                    if not retry_ok:
                        block_status = "red"
                        self.error_count += 1
                        if len(self.bad_ranges) < 1000:
                            self.bad_ranges.append({"start": scanned, "length": size, "win_error": retry_err,
                                                    "confirmed_4k_errors": 0, "reason": "慢速区块复读失败"})
                    elif retry_seconds >= SLOW_READ_THRESHOLD_SECONDS:
                        block_status = "yellow"
                        self.slow_count += 1
                        if len(self.slow_ranges) < 1000:
                            self.slow_ranges.append({"start": scanned, "length": size,
                                "read_seconds": read_seconds, "retry_seconds": retry_seconds,
                                "reason": "连续两次读取偏慢；不等同于确认坏道"})
                scanned += size
                elapsed = max(time.time() - start, 0.001)
                speed = scanned / elapsed
                cell_end = min(SCAN_GRID_CELLS, int(scanned * SCAN_GRID_CELLS / total))
                now = time.monotonic()
                if cell_end > last_grid_cell or block_status != "green" or now - last_ui_update >= 0.5:
                    self.progress_callback({
                        "scanned": scanned, "total": total, "percent": scanned * 100 / total,
                        "speed": speed, "errors": self.error_count, "slow_count": self.slow_count,
                        "cell_start": last_grid_cell, "cell_end": cell_end,
                        "cell_status": block_status, "block_offset": scanned - size,
                    })
                    last_grid_cell = max(last_grid_cell, cell_end)
                    last_ui_update = now
            return {
                "scanned": scanned, "total": total, "errors": self.error_count,
                "slow_count": self.slow_count, "slow_ranges": self.slow_ranges,
                "bad_ranges": self.bad_ranges, "stopped": self.stop_event.is_set(),
                "elapsed": time.time() - start,
            }
'''
patch(old, new, "扫描状态与结果")
patch('''        ttk.Label(scan_tab, textvariable=self.progress_var).pack(anchor="w")
        self.scan_result = tk.Text(scan_tab, height=14, wrap="word", font=("Microsoft YaHei UI", 9))
''', '''        ttk.Label(scan_tab, textvariable=self.progress_var).pack(anchor="w")
        legend = ttk.Frame(scan_tab)
        legend.pack(fill="x", pady=(8, 3))
        for color, label in (("#16A34A", "正常"), ("#EAB308", "慢速/需关注"),
                             ("#DC2626", "读取错误"), ("#9CA3AF", "未扫描")):
            swatch = tk.Frame(legend, bg=color, width=12, height=12)
            swatch.pack(side="left", padx=(8, 3))
            swatch.pack_propagate(False)
            ttk.Label(legend, text=label).pack(side="left")
        self.scan_grid = tk.Canvas(scan_tab, height=190, bg="#f7f9fc",
                                   highlightthickness=1, highlightbackground="#d6dee8")
        self.scan_grid.pack(fill="x", pady=(2, 8))
        self.scan_grid_states = ["gray"] * SCAN_GRID_CELLS
        self.scan_grid_items = []
        self._draw_scan_grid()
        self.scan_result = tk.Text(scan_tab, height=14, wrap="word", font=("Microsoft YaHei UI", 9))
''', "图例和网格")
patch("    def start_surface_scan(self):\n", '''    def _draw_scan_grid(self):
        self.scan_grid.delete("all")
        self.scan_grid_items = []
        cols, cell_w, cell_h, gap = 40, 13, 8, 3
        colors = {"green": "#16A34A", "yellow": "#EAB308", "red": "#DC2626", "gray": "#9CA3AF"}
        for i, state in enumerate(self.scan_grid_states):
            row, col = divmod(i, cols)
            x, y = 8 + col * (cell_w + gap), 8 + row * (cell_h + gap)
            c = colors.get(state, "#9CA3AF")
            self.scan_grid_items.append(self.scan_grid.create_rectangle(x, y, x+cell_w, y+cell_h, fill=c, outline=c))

    def _update_scan_grid(self, update):
        start, end = int(update.get("cell_start", 0)), int(update.get("cell_end", 0))
        status = update.get("cell_status", "green")
        priority = {"gray": 0, "green": 1, "yellow": 2, "red": 3}
        for i in range(max(0, start), min(SCAN_GRID_CELLS, end)):
            if priority.get(status, 0) > priority.get(self.scan_grid_states[i], 0):
                self.scan_grid_states[i] = status
        if status in ("yellow", "red"):
            idx = min(SCAN_GRID_CELLS-1, int(update.get("block_offset", 0) * SCAN_GRID_CELLS / max(1, update.get("total", 1))))
            if priority.get(status, 0) > priority.get(self.scan_grid_states[idx], 0):
                self.scan_grid_states[idx] = status
        colors = {"green": "#16A34A", "yellow": "#EAB308", "red": "#DC2626", "gray": "#9CA3AF"}
        for i, item in enumerate(self.scan_grid_items):
            c = colors.get(self.scan_grid_states[i], "#9CA3AF")
            self.scan_grid.itemconfigure(item, fill=c, outline=c)

    def start_surface_scan(self):
''', "网格绘制函数")
patch('        self.progress.configure(value=0)\n        self.progress_var.set("正在准备扫描……")\n',
      '        self.progress.configure(value=0)\n        self.scan_grid_states = ["gray"] * SCAN_GRID_CELLS\n        self._draw_scan_grid()\n        self.progress_var.set("正在准备扫描……")\n', "重置网格")
patch('                    self.progress.configure(value=p["percent"])\n                    prefix = "已暂停 | " if self.scan_paused else ""\n',
      '                    self.progress.configure(value=p["percent"])\n                    self._update_scan_grid(p)\n                    prefix = "已暂停 | " if self.scan_paused else ""\n', "更新网格")
patch('''                        f"速度：{human_size(p['speed'])}/秒    读取错误区块：{p['errors']}"
''', '''                        f"速度：{human_size(p['speed'])}/秒    慢速区块：{p.get('slow_count', 0)}    读取错误区块：{p['errors']}"
''', "进度统计")
patch('''                    self._set_scan_text(f"{state}。耗时：{result['elapsed']:.1f} 秒；读取错误区块：{result['errors']}。")
                    if result["bad_ranges"]:
''', '''                    coverage = result["scanned"] * 100 / result["total"] if result["total"] else 0
                    avg_speed = result["scanned"] / max(result["elapsed"], 0.001)
                    self._set_scan_text(f"{state}。耗时：{result['elapsed']:.1f} 秒；扫描覆盖率：{coverage:.2f}%；平均速度：{human_size(avg_speed)}/秒。")
                    self._set_scan_text(f"慢速区块：{result.get('slow_count', 0)}；读取错误区块：{result['errors']}。黄色为复测仍慢的风险提示，不等同于已确认坏道。")
                    counts = {name: self.scan_grid_states.count(name) for name in ("green", "yellow", "red", "gray")}
                    self._set_scan_text(f"区块分布：绿色 {counts['green']} 格；黄色 {counts['yellow']} 格；红色 {counts['red']} 格；灰色 {counts['gray']} 格。")
                    if result.get("slow_ranges"):
                        self._set_scan_text("慢速区段（复测仍慢）：")
                        for r in result["slow_ranges"]:
                            self._set_scan_text(f"偏移 {r['start']} 字节（{human_size(r['start'])}），长度 {r['length']} 字节；首次 {r['read_seconds']:.3f}s，复测 {r['retry_seconds']:.3f}s。")
                    if result["bad_ranges"]:
''', "完成报告")

p.write_text(s, encoding="utf-8-sig", newline="")
print("v0.4.1 坏道扫描可视化补丁已应用。")
