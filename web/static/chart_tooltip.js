"use strict";

(function () {
    let tooltip = null;
    let markers = null;

    function ensureTooltip() {
        if (tooltip) return tooltip;

        const style = document.createElement("style");
        style.textContent = `
            .distance-chart-tooltip {
                position: fixed;
                z-index: 1000;
                min-width: 175px;
                padding: 9px 11px;
                border: 1px solid #abcdb9;
                border-radius: 5px;
                background: rgba(255, 255, 255, .97);
                box-shadow: 0 5px 18px rgba(0, 59, 50, .16);
                color: #003b32;
                font: 12px/1.45 Arial, sans-serif;
                pointer-events: none;
            }
            .distance-chart-tooltip strong {
                display: block;
                margin-bottom: 3px;
            }
            .distance-chart-marker {
                position: fixed;
                z-index: 999;
                width: 10px;
                height: 10px;
                border: 2px solid white;
                border-radius: 50%;
                box-shadow: 0 1px 5px rgba(0, 59, 50, .35);
                pointer-events: none;
                transform: translate(-50%, -50%);
            }
            .distance-chart-marker.radest {
                background: #008143;
            }
            .distance-chart-marker.vehicle {
                background: #d58a00;
            }
            canvas[data-distance-tooltip] {
                cursor: crosshair;
            }
        `;
        document.head.append(style);

        tooltip = document.createElement("div");
        tooltip.className = "distance-chart-tooltip";
        tooltip.hidden = true;
        document.body.append(tooltip);
        return tooltip;
    }

    function ensureMarkers() {
        if (markers) return markers;

        const radest = document.createElement("span");
        radest.className = "distance-chart-marker radest";
        radest.hidden = true;
        const vehicle = document.createElement("span");
        vehicle.className = "distance-chart-marker vehicle";
        vehicle.hidden = true;
        document.body.append(radest, vehicle);
        markers = {radest, vehicle};
        return markers;
    }

    function positionMarker(marker, value, time, rect, state) {
        if (value === null || time === null || typeof state.y !== "function") {
            marker.hidden = true;
            return;
        }

        const scaleX = rect.width / state.width;
        const scaleY = rect.height / state.height;
        marker.style.left = rect.left + state.x(time) * scaleX + "px";
        marker.style.top = rect.top + state.y(value) * scaleY + "px";
        marker.hidden = false;
    }

    function number(value) {
        const parsed = Number(value);
        return Number.isFinite(parsed) ? parsed : null;
    }

    function format(value, unit) {
        return value === null
            ? "–"
            : value.toFixed(2).replace(".", ",") + " " + unit;
    }

    function hide() {
        if (tooltip) tooltip.hidden = true;
        if (markers) {
            markers.radest.hidden = true;
            markers.vehicle.hidden = true;
        }
    }

    function handlePointerMove(event) {
        const canvas = event.currentTarget;
        const state = canvas.__distanceTooltipState;
        if (!state || !state.points.length) {
            hide();
            return;
        }

        const rect = canvas.getBoundingClientRect();
        const mouseX = event.clientX - rect.left;
        const mouseY = event.clientY - rect.top;
        const plotRight = state.width - state.pad.right;
        const plotBottom = state.height - state.pad.bottom;

        if (
            mouseX < state.pad.left
            || mouseX > plotRight
            || mouseY < state.pad.top
            || mouseY > plotBottom
        ) {
            hide();
            return;
        }

        let closest = state.points[0];
        let closestDistance = Math.abs(state.x(number(closest[state.timeKey])) - mouseX);
        for (const point of state.points.slice(1)) {
            const distance = Math.abs(state.x(number(point[state.timeKey])) - mouseX);
            if (distance < closestDistance) {
                closest = point;
                closestDistance = distance;
            }
        }

        const time = number(closest[state.timeKey]);
        const radest = number(closest[state.radestKey]);
        const vehicle = number(closest[state.vehicleKey]);
        const deviation = radest !== null && vehicle !== null ? vehicle - radest : null;
        const box = ensureTooltip();
        box.replaceChildren();

        const heading = document.createElement("strong");
        heading.textContent = "Messpunkt bei " + format(time, "s");
        box.append(heading);
        for (const [label, value, unit] of [
            ["RadEsT", radest, "m"],
            ["Fahrzeug", vehicle, "m"],
            ["Abweichung", deviation, "m"]
        ]) {
            const line = document.createElement("div");
            line.textContent = label + ": " + format(value, unit);
            box.append(line);
        }

        box.hidden = false;
        const left = Math.min(event.clientX + 14, window.innerWidth - box.offsetWidth - 8);
        const top = Math.min(event.clientY + 14, window.innerHeight - box.offsetHeight - 8);
        box.style.left = Math.max(8, left) + "px";
        box.style.top = Math.max(8, top) + "px";

        const pointMarkers = ensureMarkers();
        positionMarker(pointMarkers.radest, radest, time, rect, state);
        positionMarker(pointMarkers.vehicle, vehicle, time, rect, state);
    }

    function update(canvas, state) {
        canvas.__distanceTooltipState = state;
        canvas.dataset.distanceTooltip = "true";
        if (canvas.dataset.distanceTooltipBound === "true") return;
        canvas.dataset.distanceTooltipBound = "true";
        canvas.addEventListener("pointermove", handlePointerMove);
        canvas.addEventListener("pointerleave", hide);
    }

    function clear(canvas) {
        canvas.__distanceTooltipState = null;
        hide();
    }

    window.DistanceChartTooltip = {update, clear};
})();
