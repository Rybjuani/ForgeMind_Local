"""Entry point de ForgeMind Local.

Uso:
    python -m app.main            # arranca la UI
    python -m app.main --check    # solo imprime resumen de entorno y sale
    python -m app.main --mock     # fuerza MOCK_LLM=1 para inspeccionar UI sin modelo
"""

from __future__ import annotations

import argparse
import os
import sys


def _print_env_summary() -> None:
    print("=== ForgeMind Local - check de entorno ===")
    print(f"Python: {sys.version.split()[0]} ({sys.executable})")
    print(f"Plataforma: {sys.platform}")
    print()
    print("-- Backend --")
    from .metrics import find_executable
    cli = find_executable("llama-cli") or find_executable("llama-cli.exe")
    srv = find_executable("llama-server") or find_executable("llama-server.exe")
    print(f"  llama-cli    : {cli or 'NO encontrado en PATH'}")
    print(f"  llama-server : {srv or 'NO encontrado en PATH'}")
    try:
        import llama_cpp  # noqa: F401
        print("  binding llama_cpp: OK")
    except Exception as e:
        print(f"  binding llama_cpp: NO instalado ({e.__class__.__name__})")
    print()
    print("-- RAM / Sistema --")
    from .metrics import get_system_memory
    sm = get_system_memory()
    print(f"  RAM total: {sm['total_human']}")
    print(f"  RAM disp : {sm['available_human']}")
    print()
    print("-- GPU / Vulkan --")
    try:
        from .gpu_detect import system_summary
        s = system_summary()
        gpus = s.get("gpus") or []
        print(f"  GPUs detectadas: {len(gpus)}")
        for g in gpus:
            print(f"    - {g['name']}")
        amd = s.get("amd_gpu")
        print(f"  AMD/Radeon    : {amd['name'] if amd else '(no)'}")
        vk = s.get("vulkan", {})
        print(f"  Vulkan dll    : {vk.get('vulkan_dll_present')}")
        print(f"  vulkaninfo    : {vk.get('vulkaninfo_installed')}")
        print(f"  Vulkan (heur) : {vk.get('available')}")
    except Exception as e:
        print(f"  Error detectando GPU/Vulkan: {e}")


def _run_ui() -> int:
    # Import diferido para que --check funcione sin PyQt6 instalado
    from PyQt6.QtWidgets import QApplication
    from .ui_main import MainWindow

    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    return app.exec()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="forgemind-local")
    p.add_argument("--check", action="store_true",
                   help="Solo imprime resumen de entorno y sale.")
    p.add_argument("--mock", action="store_true",
                   help="Fuerza MOCK_LLM=1 (UI sirve sin modelo cargado).")
    args = p.parse_args(argv)

    if args.mock:
        os.environ["MOCK_LLM"] = "1"

    if args.check:
        _print_env_summary()
        return 0

    try:
        return _run_ui()
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())