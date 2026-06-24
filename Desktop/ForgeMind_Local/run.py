"""Entry shim para PyInstaller.

PyInstaller's bootloader ejecuta este archivo como script (__main__), no
como modulo de un paquete, asi que los imports relativos internos de `app.*`
fallarian con `ImportError: attempted relative import with no known parent
package`. Este shim agrega el project root a sys.path y hace import ABSOLUTO
de `app.main`, lo cual setea __package__="app" correctamente.

En desarrollo se sigue usando:  python -m app.main
Empaquetado:                      pyinstaller forgemind.spec  (entry = run.py)
"""

import os
import sys


def _bootstrap() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)


def main() -> int:
    _bootstrap()
    from app.main import main as app_main
    return app_main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())