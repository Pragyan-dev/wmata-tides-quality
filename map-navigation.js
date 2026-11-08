"use strict";

function setupMapNavigation(surface, { width, height }, scheduleTiles) {
  const fitButton = document.getElementById("map-fit");
  const svg = surface.querySelector("svg");
  const maxZoom = 256;
  const clamp = (value, min, max) => Math.min(Math.max(value, min), max);
  let routeId;
  let zoom = 1;
  let x = 0;
  let y = 0;
  let drag = null;

  function setView(nextZoom, left, top) {
    zoom = nextZoom;
    x = clamp(left, 0, width - width / zoom);
    y = clamp(top, 0, height - height / zoom);
    svg.setAttribute("viewBox", [x, y, width / zoom, height / zoom].join(" "));
    surface.style.setProperty("--marker-scale", 1 / zoom);
    surface.classList.toggle("zoomed", zoom > 1);
    scheduleTiles();
  }

  function zoomBy(factor, anchorX = .5, anchorY = .5) {
    const nextZoom = clamp(zoom * factor, 1, maxZoom);
    const delta = 1 / zoom - 1 / nextZoom;
    setView(nextZoom, x + width * anchorX * delta, y + height * anchorY * delta);
  }

  function centerOn(cx, cy, nextZoom = zoom) {
    setView(nextZoom, cx - width / (2 * nextZoom), cy - height / (2 * nextZoom));
  }

  function reset() {
    setView(1, 0, 0);
  }

  function fitRoute() {
    const markers = [...svg.querySelectorAll("[data-stop]")];
    if (!routeId || !markers.length) {
      reset();
      return;
    }
    const xs = markers.map(marker => marker.cx.baseVal.value);
    const ys = markers.map(marker => marker.cy.baseVal.value);
    const west = Math.min(...xs);
    const east = Math.max(...xs);
    const north = Math.min(...ys);
    const south = Math.max(...ys);
    const fittedZoom = clamp(Math.min(
      width / (east - west + .18 * width),
      height / (south - north + .18 * height)
    ), 1, maxZoom);
    centerOn((west + east) / 2, (north + south) / 2, fittedZoom);
  }

  document.getElementById("map-zoom-in").onclick = () => zoomBy(2);
  document.getElementById("map-zoom-out").onclick = () => zoomBy(.5);
  document.getElementById("map-reset").onclick = reset;
  fitButton.onclick = fitRoute;

  surface.addEventListener("wheel", event => {
    if (!event.ctrlKey && !event.metaKey) return;
    event.preventDefault();
    const rect = svg.getBoundingClientRect();
    zoomBy(event.deltaY < 0 ? 1.25 : 1 / 1.25,
      (event.clientX - rect.left) / rect.width, (event.clientY - rect.top) / rect.height);
  }, { passive: false });

  surface.addEventListener("keydown", event => {
    const directions = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
    const direction = directions[event.key];
    if (event.key === "+" || event.key === "=") zoomBy(2);
    else if (event.key === "-") zoomBy(.5);
    else if (event.key === "Home") reset();
    else if (direction && zoom > 1) {
      setView(zoom, x + direction[0] * width / (8 * zoom), y + direction[1] * height / (8 * zoom));
    } else return;
    event.preventDefault();
  });

  surface.addEventListener("pointerdown", event => {
    if (zoom === 1 || !event.isPrimary || event.button !== 0) return;
    drag = { id: event.pointerId, clientX: event.clientX, clientY: event.clientY, x, y, moved: false };
  });

  surface.addEventListener("pointermove", event => {
    if (event.pointerId !== drag?.id) return;
    const dx = event.clientX - drag.clientX;
    const dy = event.clientY - drag.clientY;
    if (!drag.moved) {
      if (Math.hypot(dx, dy) < 5) return;
      drag.moved = true;
      surface.setPointerCapture(event.pointerId);
      surface.classList.add("dragging");
    }
    const unitsPerPixel = width / (zoom * svg.clientWidth);
    setView(zoom, drag.x - dx * unitsPerPixel, drag.y - dy * unitsPerPixel);
  });

  for (const type of ["pointerup", "pointercancel", "lostpointercapture"]) {
    surface.addEventListener(type, event => {
      if (event.pointerId !== drag?.id) return;
      drag = null;
      surface.classList.remove("dragging");
    });
  }

  return {
    refresh(id) {
      fitButton.disabled = !id || !svg.querySelector("[data-stop]");
      if (id === routeId) setView(zoom, x, y);
      else {
        routeId = id;
        fitRoute();
      }
    },
    reveal(marker) {
      if (!marker) return;
      const cx = marker.cx.baseVal.value;
      const cy = marker.cy.baseVal.value;
      if (cx < x || cx > x + width / zoom || cy < y || cy > y + height / zoom) centerOn(cx, cy);
    }
  };
}
