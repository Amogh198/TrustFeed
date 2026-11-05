"""Start the API and dashboard from this checkout, and say plainly if the image model can't run.

Run from the repository root: python tools/start_demo.py
"""
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def missing(names: tuple[str, ...]) -> list[str]:
    return [name for name in names if importlib.util.find_spec(name) is None]


def main() -> int:
    # A global Python often lacks the packages, which is how the model silently ends up unavailable.
    if VENV.exists() and Path(sys.prefix).resolve() != VENV.parent.parent.resolve():
        return subprocess.call([str(VENV), __file__])
    if missing(("fastapi", "uvicorn")):
        print("The API's packages are missing. Run: pip install -r backend/api/requirements-dev.txt")
        return 1
    absent = missing(("torch", "transformers"))
    if absent:
        print(f"WARNING: the image model can't run, because {', '.join(absent)} is missing.")
        print("Uploads will have no media score. Fix: pip install -r backend/media/requirements-model.txt")
    else:
        print("Image model packages: ready. The first upload may take longer while the model loads.")
    npm = shutil.which("npm")
    if not npm:
        print("npm is missing. Install Node 18 or later.")
        return 1
    if not (ROOT / "frontend" / "node_modules").exists():
        subprocess.check_call([npm, "install"], cwd=ROOT / "frontend")
    env_file = ["--env-file", ".env"] if (ROOT / ".env").exists() else []
    api = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.api.app.main:app", *env_file], cwd=ROOT)
    try:
        print("Dashboard: http://localhost:5173")
        return subprocess.call([npm, "run", "dev"], cwd=ROOT / "frontend")
    except KeyboardInterrupt:
        return 0
    finally:
        api.terminate()


if __name__ == "__main__":
    sys.exit(main())
