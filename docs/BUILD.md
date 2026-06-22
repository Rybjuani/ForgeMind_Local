# Empaquetado a .exe (PyInstaller)

## TL;DR

```powershell
cd C:\Users\nosom\Desktop\ForgeMind_Local
python -m pip install pyinstaller
.\scripts\build.ps1
```

Resultado: `dist\ForgeMind.exe` (~70-90 MB, single-file, standalone).

## Estructura

```
ForgeMind_Local/
  run.py                  # entry shim (NO app/main.py directo)
  forgemind.spec          # spec de PyInstaller
  scripts/build.ps1       # wrapper PowerShell
```

## Por que `run.py` y no `app/main.py` directo?

PyInstaller's bootloader ejecuta el entry como script (`__main__` del bootloader, no de un paquete). Los imports relativos internos (`from .x import ...`) fallan con:

> `ImportError: attempted relative import with no known parent package`

`run.py` es un script top-level sin imports relativos, que hace `from app.main import main`. Esa importacion setea `__package__="app"` y todo lo de adentro funciona igual en dev y en el `.exe` empaquetado.

## Build options

| Flag | Efecto |
|---|---|
| `-Clean` | Borra `build/` y `dist/` antes de compilar |
| `-NoUpx` | No usar UPX (compresor). .exe mas grande pero arranca mas rapido |

## Verificar el .exe

```powershell
.\dist\ForgeMind.exe -Check    # resumen de entorno
.\dist\ForgeMind.exe -Mock     # UI sin modelo
```

## NSIS installer (opcional, mas adelante)

Si queres un `.exe` instalador tipo setup con Start Menu + Agregar/Quitar programas, ver skill `desktop-app-pyinstaller` -> `references/freezip-nsi.md`. **NO incluido en MVP**, queda como extension futura.

## Tamano esperado

- PyQt6 + psutil + stdlib ~= 70-90 MB single-file en Windows x64
- UPX activado por defecto (ahorra ~20-30 MB)
- Sin GPU/CUDA: ya excluido del spec
- Excluidos: tkinter, matplotlib, numpy, pandas, QtNetwork, QtWebEngine, Qt3D, QtBluetooth, etc.

## Pitfalls PyQt6 >= 6.7 (ya manejados en este proyecto)

- `QAction` vive en `QtGui`, no `QtWidgets` -> ya esta en `app/ui_main.py`
- `QFileSystemModel` en `QtGui` -> no se usa en esta app
- `AA_EnableHighDpiScaling` removido -> no se llama en ningun lado

## Pendiente

- Icono `.ico` (cuando exista) -> descomentar linea en `forgemind.spec`
- Modo `--onedir` (`.exe` + carpeta de DLLs) -> descomentar bloque COLLECT al final del spec
- Code signing -> requiere certificado; no aplica a uso personal