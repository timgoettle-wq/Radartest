"""Systemzeit des Pi aus der Browserzeit des Laptops setzen.

Der Pi hat keine Echtzeituhr. Nach einer Stromtrennung startet er ohne
Internet mit einer alten Uhrzeit, wodurch Zeitstempel in run.json und den
CSV-Dateien falsch sind. Die Weboberfläche schickt deshalb beim Öffnen die
Uhrzeit des Browsers; weicht sie deutlich ab, wird die Systemzeit per
``sudo -n date`` gesetzt. Während einer Messung wird die Uhr nicht verstellt.
"""

import subprocess
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


# Kleinere Abweichungen ignorieren, damit die Uhr nicht bei jedem
# Seitenaufruf um Bruchteile von Sekunden springt.
MAX_DEVIATION_S = 5.0


class ClientTime(BaseModel):
    unix_ms: int


def set_system_time(unix_s):
    subprocess.run(
        ["sudo", "-n", "date", "-u", "-s", f"@{unix_s:.3f}"],
        check=True,
        capture_output=True,
        text=True,
    )


def make_system_time_router(lock, measurement_running):
    """``lock`` muss derselbe Lock sein, unter dem Messungen starten."""
    router = APIRouter(prefix="/api/system-time", tags=["Systemzeit"])

    @router.post("")
    def sync_system_time(client: ClientTime):
        client_s = client.unix_ms / 1000
        offset_s = client_s - time.time()

        if abs(offset_s) < MAX_DEVIATION_S:
            return {"changed": False, "offset_s": round(offset_s, 3)}

        with lock:
            if measurement_running():
                raise HTTPException(
                    status_code=409,
                    detail="Während einer Messung wird die Uhrzeit nicht verstellt.",
                )

            try:
                set_system_time(client_s)
            except (OSError, subprocess.CalledProcessError) as error:
                detail = getattr(error, "stderr", None) or str(error)
                raise HTTPException(
                    status_code=500,
                    detail=f"Uhrzeit konnte nicht gesetzt werden: {detail.strip()}",
                ) from error

        return {"changed": True, "offset_s": round(offset_s, 3)}

    return router
