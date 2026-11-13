from __future__ import annotations
import ast
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
for filename in ("disk_health_inspector.py", "disk_health_diagnostics.py", "test_core.py", "test_diagnostics.py"):
    path = root / filename
    if not path.exists():
        print(f"[MISSING] {filename}")
        continue
    source = path.read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    print(f"\n===== {filename} ({len(source.splitlines())} lines) =====")
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            print(f"CLASS {node.name} line={node.lineno}")
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    print(f"  METHOD {child.name} line={child.lineno}")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            print(f"FUNCTION {node.name} line={node.lineno}")
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            names = []
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    names.append(target.id)
            if names:
                print(f"GLOBAL {','.join(names)} line={node.lineno}")
