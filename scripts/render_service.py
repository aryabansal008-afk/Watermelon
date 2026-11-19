"""Run the API and RQ worker together in a single small Render web instance."""
import os
import signal
import subprocess
import sys
import time


def main() -> int:
    port = os.environ.get("PORT", "10000")
    worker = subprocess.Popen([sys.executable, "-m", "backend.worker"], start_new_session=True)
    api = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.api:app", "--host", "0.0.0.0", "--port", port],
        start_new_session=True,
    )
    processes = (worker, api)

    def stop(_signum, _frame):
        for process in processes:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while all(process.poll() is None for process in processes):
            time.sleep(0.5)
    except KeyboardInterrupt:
        stop(signal.SIGINT, None)
    finally:
        stop(signal.SIGTERM, None)
        for process in processes:
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()

    return next((process.returncode for process in processes if process.returncode), 0)


if __name__ == "__main__":
    raise SystemExit(main())
