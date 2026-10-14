"""What the machine is doing: processors, memory, disks, the process.

psutil (the ``status`` extra) measures everything on every system.
Without it the same figures are read where the standard library or
Linux's ``/proc`` give them, and a figure nothing can give is ``None`` -
drawn as "not measured", never as a zero that would look healthy.
"""

from __future__ import annotations

import os
import platform
import shutil
import socket
import sys
import time
from pathlib import Path
from typing import Any

from django.conf import settings
from django.utils.translation import gettext

from generic.conf import generic_settings

try:  # pragma: no cover - a property of the environment
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

#: When this process started answering, for its uptime.
STARTED = time.time()

#: psutil's processor figure is the use since the previous call: the
#: very first one has nothing to compare with and says 0.0. Primed at
#: import, so the first page already reads a real figure.
if psutil is not None:  # pragma: no cover - a property of the environment
    psutil.cpu_percent(interval=None)


def percent(part: float | None, whole: float | None) -> float | None:
    if part is None or not whole:
        return None

    return round(100.0 * part / whole, 1)


def level_of(name: str, value: float | None) -> str:
    """``ok``, ``warning`` or ``error`` for a gauge, by the thresholds."""
    thresholds = dict(generic_settings.STATUS_THRESHOLDS or {}).get(name)

    if value is None or not thresholds:
        return "ok"

    warning, error = thresholds

    if value >= error:
        return "error"

    if value >= warning:
        return "warning"

    return "ok"


# -- processors -----------------------------------------------------------


def load_average() -> list[float] | None:
    try:
        return [round(value, 2) for value in os.getloadavg()]
    except (AttributeError, OSError):  # Windows
        return None


def cpu() -> dict[str, Any]:
    count = os.cpu_count() or 1
    load = load_average()

    if psutil is not None:
        used = psutil.cpu_percent(interval=None)
        cores = psutil.cpu_percent(interval=None, percpu=True)
        frequency = None

        try:
            current = psutil.cpu_freq()
            frequency = round(current.current) if current else None
        except (AttributeError, NotImplementedError, OSError):
            pass  # pragma: no cover - containers often hide it
    else:  # pragma: no cover - exercised without psutil
        # The run queue over the last minute, per processor: not the
        # same figure, but the one that says "too busy" without psutil.
        used = min(100.0, round(100.0 * load[0] / count, 1)) if load else None
        cores = []
        frequency = None

    return {
        "percent": used,
        "level": level_of("cpu", used),
        "count": count,
        "cores": cores,
        "load": load,
        "frequency_mhz": frequency,
    }


# -- memory ---------------------------------------------------------------


def meminfo() -> dict[str, int]:
    """Linux's ``/proc/meminfo`` in bytes; empty anywhere else."""
    values: dict[str, int] = {}

    try:
        with open("/proc/meminfo", encoding="ascii") as source:
            for line in source:
                name, _, rest = line.partition(":")
                number = rest.split()

                if number and number[0].isdigit():
                    values[name] = int(number[0]) * 1024
    except OSError:
        pass

    return values


def memory() -> dict[str, Any]:
    if psutil is not None:
        virtual = psutil.virtual_memory()
        swap = psutil.swap_memory()
        total, available = virtual.total, virtual.available
        swap_total, swap_used = swap.total, swap.used
    else:  # pragma: no cover - exercised without psutil
        info = meminfo()
        total = info.get("MemTotal")
        available = info.get("MemAvailable")
        swap_total = info.get("SwapTotal")
        swap_free = info.get("SwapFree")
        swap_used = (
            swap_total - swap_free
            if swap_total is not None and swap_free is not None
            else None
        )

    used = total - available if total and available is not None else None
    used_percent = percent(used, total)
    swap_percent = percent(swap_used, swap_total)

    return {
        "total": total,
        "used": used,
        "available": available,
        "percent": used_percent,
        "level": level_of("memory", used_percent),
        "swap": {
            "total": swap_total,
            "used": swap_used,
            "percent": swap_percent,
            "level": level_of("swap", swap_percent),
        },
    }


# -- disks ----------------------------------------------------------------


def disk_paths() -> list[tuple[str, str]]:
    """Every place worth measuring, labelled, as configured or found."""
    declared = generic_settings.STATUS_DISKS

    if declared is not None:
        paths = []

        for entry in declared:
            if isinstance(entry, (list, tuple)):
                paths.append((str(entry[0]), str(entry[1])))
            else:
                paths.append((str(entry), str(entry)))

        return paths

    paths = [(gettext("System"), os.path.abspath(os.sep))]

    if getattr(settings, "MEDIA_ROOT", ""):
        paths.append((gettext("Media files"), str(settings.MEDIA_ROOT)))

    for alias, database in settings.DATABASES.items():
        name = str(database.get("NAME") or "")

        if "sqlite" in str(database.get("ENGINE", "")) and os.path.isabs(name):
            paths.append(
                (
                    gettext("Database %(alias)s") % {"alias": alias},
                    os.path.dirname(name),
                )
            )

    return paths


def existing(path: str) -> str | None:
    """The path itself, or the nearest folder above it that exists."""
    current = Path(path)

    for candidate in (current, *current.parents):
        if candidate.exists():
            return str(candidate)

    return None


def device_of(path: str) -> Any:
    try:
        return os.stat(path).st_dev
    except OSError:  # pragma: no cover - removed in between
        return path


def disks() -> list[dict[str, Any]]:
    """One entry per disk: two paths on the same one are one gauge."""
    found: dict[Any, dict[str, Any]] = {}

    for label, path in disk_paths():
        place = existing(path)

        if place is None:
            continue

        device = device_of(place)

        if device in found:
            found[device]["labels"].append(label)
            continue

        try:
            usage = shutil.disk_usage(place)
        except OSError:  # pragma: no cover - a vanished mount
            continue

        # As df: what is used of what an ordinary user may use, the
        # blocks kept for the system aside.
        used_percent = percent(usage.used, usage.used + usage.free)
        found[device] = {
            "labels": [label],
            "path": place,
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
            "percent": used_percent,
            "level": level_of("disk", used_percent),
        }

    entries = list(found.values())

    for entry in entries:
        entry["label"] = ", ".join(entry.pop("labels"))

    return entries


# -- the machine and the process ------------------------------------------


def boot_time() -> float | None:
    if psutil is not None:
        try:
            return float(psutil.boot_time())
        except Exception:  # pragma: no cover - some containers refuse
            return None

    try:  # pragma: no cover - exercised without psutil
        with open("/proc/uptime", encoding="ascii") as source:
            return time.time() - float(source.read().split()[0])
    except (OSError, ValueError, IndexError):  # pragma: no cover
        return None


def process() -> dict[str, Any]:
    entry: dict[str, Any] = {
        "pid": os.getpid(),
        "started": STARTED,
        "uptime": round(time.time() - STARTED),
        "memory": None,
        "threads": None,
        "cpu_percent": None,
    }

    if psutil is not None:
        try:
            current = psutil.Process()

            with current.oneshot():
                entry["memory"] = current.memory_info().rss
                entry["threads"] = current.num_threads()
                entry["cpu_percent"] = current.cpu_percent(interval=None)
        except Exception:  # pragma: no cover - a restricted sandbox
            pass

    return entry


def host() -> dict[str, Any]:
    booted = boot_time()

    return {
        "hostname": socket.gethostname(),
        "system": f"{platform.system()} {platform.release()}".strip(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "implementation": sys.implementation.name,
        "booted": booted,
        "uptime": round(time.time() - booted) if booted else None,
        "psutil": psutil is not None,
    }


def system() -> dict[str, Any]:
    """Everything above, as one entry of the status."""
    return {
        "host": host(),
        "cpu": cpu(),
        "memory": memory(),
        "disks": disks(),
        "process": process(),
    }
