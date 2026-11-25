#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pydeps.py —— Python 依赖检查与安装（换机器第一件事）。

  python scripts/pydeps.py            # 只检查，缺什么打印安装命令
  python scripts/pydeps.py --install  # 直接 pip 装（numpy / Pillow）

设计：不要求用户先读文档——缺依赖时其它脚本会自己调 `ensure()` 并给出可复制的命令。
"""
import argparse
import importlib
import subprocess
import sys

REQ = [("numpy", "numpy>=1.24"), ("PIL", "Pillow>=10.0")]


def missing():
    out = []
    for mod, pkg in REQ:
        try:
            importlib.import_module(mod)
        except Exception:
            out.append(pkg)
    return out


def install(pkgs, quiet=False):
    if not pkgs:
        return True
    cmd = [sys.executable, "-m", "pip", "install", "--quiet", *pkgs]
    if not quiet:
        print("  安装:", " ".join(pkgs))
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print(r.stdout[-800:], r.stderr[-800:])
        return False
    return True


def ensure(quiet=False):
    """其它脚本入口调用它：缺依赖就装，装不上返回 False。"""
    m = missing()
    if not m:
        return True
    if not quiet:
        print(f"[deps] 缺少 Python 依赖：{', '.join(m)}，正在安装…")
    ok = install(m, quiet=quiet)
    if ok and not quiet:
        print("[deps] 完成")
    return ok and not missing()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--install", action="store_true")
    a = ap.parse_args()
    m = missing()
    if not m:
        print("✓ Python 依赖齐全（numpy / Pillow）")
        return 0
    print("缺少：", ", ".join(m))
    print("安装：python -m pip install " + " ".join(m), "   （或 python scripts/pydeps.py --install）")
    if a.install:
        ok = install(m)
        print("✓ 安装完成" if ok and not missing() else "✗ 安装失败，请手动 pip install")
        return 0 if ok else 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
