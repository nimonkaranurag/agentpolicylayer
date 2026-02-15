import os
import signal
import subprocess
import sys


def kill_process_on_port(port: int) -> bool:
    try:
        if (
            sys.platform == "darwin"
            or sys.platform.startswith("linux")
        ):
            return _kill_port_unix(port)
        elif sys.platform == "win32":
            return _kill_port_windows(port)
    except Exception:
        pass
    return False


def _kill_port_unix(port: int) -> bool:
    result = subprocess.run(
        ["lsof", "-ti", f":{port}"],
        capture_output=True,
        text=True,
    )

    if not result.stdout.strip():
        return False

    pids = result.stdout.strip().split("\n")
    killed = False

    for pid in pids:
        try:
            os.kill(int(pid), signal.SIGKILL)
            killed = True
        except (ProcessLookupError, ValueError):
            pass

    return killed


def _kill_port_windows(port: int) -> bool:
    result = subprocess.run(
        f"netstat -ano | findstr :{port}",
        capture_output=True,
        text=True,
        shell=True,
    )

    if not result.stdout.strip():
        return False

    killed = False
    for line in result.stdout.strip().split("\n"):
        if f":{port}" in line:
            parts = line.split()
            if parts:
                try:
                    pid = int(parts[-1])
                    subprocess.run(
                        [
                            "taskkill",
                            "/F",
                            "/PID",
                            str(pid),
                        ],
                        capture_output=True,
                    )
                    killed = True
                except (ValueError, IndexError):
                    pass

    return killed
