"use strict";

// Der Pi hat keine Echtzeituhr: Browserzeit des Laptops an den Pi schicken.
fetch("/api/system-time", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({unix_ms: Date.now()})
})
    .then(response => response.json())
    .then(result => {
        if (result.changed) {
            console.info(`Pi-Uhrzeit um ${result.offset_s} s korrigiert.`);
        } else if (result.detail) {
            console.warn(result.detail);
        }
    })
    .catch(error => console.warn("Uhrzeitabgleich fehlgeschlagen:", error));
