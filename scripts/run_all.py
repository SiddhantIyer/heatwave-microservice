"""Start all five backend services locally (cross-platform).  Ctrl+C stops everything.
Usage: python scripts/run_all.py
"""
import os, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICES = [("data_service", 8001), ("analytics_service", 8002), ("geo_service", 8003), ("advisory_service", 8004), ("gateway", 8000)]


def main():
    env = os.environ.copy()
    procs = []
    try:
        for name, port in SERVICES:
            p = subprocess.Popen([sys.executable, "-m", "uvicorn", "main:app", "--port", str(port), "--host", "0.0.0.0"],
                                 cwd=ROOT / "services" / name, env=env)
            procs.append(p)
            print(f"started {name:18s} http://localhost:{port}/docs")
        print("\nGateway docs: http://localhost:8000/docs   |   Frontend: cd frontend && npm run dev  (http://localhost:5173)\nCtrl+C to stop.")
        reported = set()
        while any(p.poll() is None for p in procs):
            for (name, port), p in zip(SERVICES, procs):
                if p.poll() is not None and name not in reported:
                    reported.add(name)
                    print(f"WARNING: {name} exited (code {p.returncode}); other services keep running.")
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            p.terminate()


if __name__ == "__main__":
    main()
