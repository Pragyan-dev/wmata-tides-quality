"use strict";

function streetMapProjection({ west, east, north, south, width, height }) {
  const mercatorY = latitude => (1 - Math.asinh(Math.tan(latitude * Math.PI / 180)) / Math.PI) / 2;
  const worldSize = width * 360 / (east - west);
  const originX = (west + 180) / 360 * worldSize;
  const originY = (mercatorY(north) + mercatorY(south)) / 2 * worldSize - height / 2;
  return {
    width, height, worldSize, originX, originY,
    project(latitude, longitude) {
      return [
        (longitude + 180) / 360 * worldSize - originX,
        mercatorY(latitude) * worldSize - originY
      ];
    }
  };
}

function setupStreetTiles(svg, { worldSize, originX, originY }, status) {
  if (location.protocol === "file:") {
    status.textContent = "Open the dashboard through a local web server to load the street map.";
    status.hidden = false;
    return () => {};
  }
  const layer = svg.querySelector("#street-tiles");
  const tileSource = layer.dataset.source;
  const svgNamespace = "http://www.w3.org/2000/svg";
  let active;
  let fallback;
  let frame;

  function updateStatus() {
    const states = [...active.tiles.values()].map(tile => tile.dataset.state);
    status.hidden = !states.includes("failed");
    if (states.every(state => state === "loaded")) {
      fallback?.remove();
      fallback = undefined;
    }
  }

  function draw() {
    frame = undefined;
    const view = svg.viewBox.baseVal;
    if (!svg.clientWidth) return;
    const level = Math.min(19, Math.round(Math.log2(worldSize / view.width * svg.clientWidth / 256)));
    const size = worldSize / 2 ** level;
    if (active?.level !== level) {
      // Keep the last fully drawn layer visible while the next zoom level loads.
      if (active && [...active.tiles.values()].every(tile => tile.dataset.state === "loaded")) {
        fallback?.remove();
        fallback = active.group;
      } else active?.group.remove();
      const group = document.createElementNS(svgNamespace, "g");
      layer.append(group);
      active = { level, group, tiles: new Map() };
    }

    const left = Math.floor((view.x + originX) / size);
    const right = Math.ceil((view.x + view.width + originX) / size);
    const top = Math.floor((view.y + originY) / size);
    const bottom = Math.ceil((view.y + view.height + originY) / size);
    const visible = new Set();
    for (let column = left; column < right; column++) {
      for (let row = top; row < bottom; row++) {
        const key = column + "/" + row;
        visible.add(key);
        if (active.tiles.has(key)) continue;
        const tile = document.createElementNS(svgNamespace, "image");
        tile.setAttribute("x", column * size - originX);
        tile.setAttribute("y", row * size - originY);
        tile.setAttribute("width", size);
        tile.setAttribute("height", size);
        tile.dataset.state = "loading";
        for (const [event, state] of [["load", "loaded"], ["error", "failed"]]) {
          tile.addEventListener(event, () => {
            tile.dataset.state = state;
            if (tile.parentNode === active.group) updateStatus();
          }, { once: true });
        }
        active.tiles.set(key, tile);
        active.group.append(tile);
        tile.setAttribute("href", tileSource.replace("{z}", level).replace("{x}", column).replace("{y}", row));
      }
    }
    for (const [key, tile] of active.tiles) {
      if (visible.has(key)) continue;
      tile.remove();
      active.tiles.delete(key);
    }
    updateStatus();
  }

  function scheduleDraw() {
    if (frame === undefined) frame = requestAnimationFrame(draw);
  }
  new ResizeObserver(scheduleDraw).observe(svg);
  return scheduleDraw;
}
