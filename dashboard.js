"use strict";

const byId = id => document.getElementById(id);
const labels = ["Loose", "Moderate", "Strict"];
const integer = new Intl.NumberFormat("en-US");
const count = value => integer.format(value);
const events = value => count(value) + (value === 1 ? " event" : " events");
const rate = (part, whole) => whole ? part / whole : null;
const percent = (value, digits = 1) => value === null ? "—" : (100 * value).toFixed(digits) + "%";
const escape = value => String(value).replace(/[&<>"']/g, character => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
})[character]);
const empty = message => '<p class="empty">' + escape(message) + '</p>';
const routeName = id => id + (snapshot.routes[id] ? " · " + snapshot.routes[id] : "");
const route = byId("route");
const stop = byId("stop");
const mapSurface = byId("stop-map");
const streetMap = streetMapProjection(stopMap);
mapSurface.innerHTML = chart(streetMap.width, streetMap.height, "WMATA timepoint stops on a Washington region street map",
  '<g id="street-tiles" aria-hidden="true" data-source="https://tile.openstreetmap.org/{z}/{x}/{y}.png"></g><g id="stop-markers"></g>'
);
const scheduleTiles = setupStreetTiles(mapSurface.querySelector("svg"), streetMap, byId("map-status"));
const mapNavigation = setupMapNavigation(mapSurface, streetMap, scheduleTiles);

function aggregate(records, level, keyIndex) {
  const groups = new Map();
  const offset = 4 + 3 * level;
  for (const row of records) {
    const key = keyIndex === null ? "" : row[keyIndex];
    const total = groups.get(key) ?? { scheduled: 0, inferred: 0, eligible: 0, onTime: 0, early: 0 };
    total.scheduled += row[3];
    total.inferred += row[4];
    total.eligible += row[offset];
    total.onTime += row[offset + 1];
    total.early += row[offset + 2];
    groups.set(key, total);
  }
  return groups;
}

function metricCards(items) {
  return items.map(([label, value]) =>
    '<div class="kpi"><strong>' + escape(value) + '</strong><span>' + escape(label) + '</span></div>'
  ).join("");
}

function chart(width, height, title, content) {
  return '<svg class="chart" viewBox="0 0 ' + width + ' ' + height +
    '" role="group" aria-label="' + escape(title) + '">' + content + '</svg>';
}

function renderHours(records, level) {
  const hours = [...aggregate(records, level, 2)]
    .filter(([, value]) => value.eligible)
    .sort(([a], [b]) => a - b);
  if (!hours.length) {
    byId("hour-chart").innerHTML = empty("No eligible events for this selection.");
    return;
  }
  const bottom = 167;
  const width = 540;
  const step = (width - 51) / hours.length;
  let content = [0, 25, 50, 75, 100].map(tick => {
    const y = bottom - tick * 1.46;
    return '<line class="grid" x1="42" x2="534" y1="' + y + '" y2="' + y + '"/>' +
      '<text x="35" y="' + (y + 4) + '" text-anchor="end">' + tick + '%</text>';
  }).join("");
  hours.forEach(([hour, value], index) => {
    const x = 44 + step * (index + .5);
    const otp = rate(value.onTime, value.eligible);
    const height = (otp ?? 0) * 146;
    const y = bottom - height;
    const detail = hour + ':00 ET · ' + percent(otp) + ' OTP · ' + count(value.eligible) + ' eligible events';
    content += '<g role="img" aria-label="' + escape(detail) + '"><title>' + escape(detail) +
      '</title><rect x="' + (x - step * .27) + '" y="' + y + '" width="' + step * .54 +
      '" height="' + height + '" fill="var(--blue)" rx="2"/><text class="value" x="' + x +
      '" y="' + (y - 7) + '" text-anchor="middle">' + percent(otp) + '</text><text x="' +
      x + '" y="187" text-anchor="middle">' + hour + ':00</text><text x="' +
      x + '" y="204" text-anchor="middle">n=' + count(value.eligible) + '</text></g>';
  });
  byId("hour-chart").innerHTML = chart(width, 213, "On-time performance by scheduled hour in Eastern time", content);
}

function renderRoutes(records, level) {
  const groups = [...aggregate(records, level, 0)]
    .filter(([, item]) => item.eligible)
    .sort((a, b) => b[1].eligible - a[1].eligible).slice(0, 8);
  const header = '<div class="bar-row bar-heading"><span>Route</span><span>Outcome mix</span><span>On time</span><span>Eligible</span></div>';
  byId("route-chart").innerHTML = groups.length ? header + groups.map(([id, value]) => {
    const parts = [value.onTime, value.early, value.eligible - value.onTime - value.early];
    const breakdown = parts.map(part => percent(rate(part, value.eligible)));
    const description = breakdown[0] + ' on time, ' + breakdown[1] + ' early, ' +
      breakdown[2] + ' late, ' + events(value.eligible);
    return '<div class="bar-row"><button class="route-button" data-route="' + escape(id) +
      '" aria-label="Filter to ' + escape(routeName(id)) + '" title="' + escape(routeName(id)) + '">' +
      escape(id) + '</button><span class="stack" role="img" aria-label="' + description +
      '" title="' + description + '">' + breakdown.map((width, i) =>
        '<i class="' + ["on-time", "early", "late"][i] + '" style="width:' + width + '"></i>'
      ).join("") + '</span><span>' + breakdown[0] + '</span><span>' + count(value.eligible) + '</span></div>';
  }).join("") : empty("No eligible events for this selection.");
}

function table(headers, body) {
  return '<div class="table-wrap"><table><thead><tr>' +
    headers.map(label => '<th scope="col">' + escape(label) + '</th>').join("") +
    '</tr></thead><tbody>' + body.map(cells => '<tr>' +
      cells.map(cell => '<td>' + escape(cell) + '</td>').join("") +
      '</tr>').join("") + '</tbody></table></div>';
}

function renderStops(records, level) {
  const groups = [...aggregate(records, level, 1)]
    .filter(([id, item]) => item.eligible && snapshot.stops[id])
    .sort((a, b) => b[1].eligible - a[1].eligible);
  const available = new Map(groups);
  byId("map-count").textContent = groups.length
    ? count(groups.length) + (groups.length === 1 ? " stop" : " stops")
    : "No eligible stops";
  const priorStop = stop.value;
  stop.replaceChildren(new Option("Choose a stop", ""));
  for (const [id] of groups.slice().sort((a, b) => snapshot.stops[a[0]][0].localeCompare(snapshot.stops[b[0]][0]))) {
    stop.add(new Option(snapshot.stops[id][0] + " · " + id, id));
  }
  stop.value = available.has(priorStop) ? priorStop : "";
  stop.disabled = groups.length === 0;

  const points = groups.slice().reverse().map(([id, value]) => {
    const [name, lat, lon] = snapshot.stops[id];
    const [x, y] = streetMap.project(lat, lon);
    const otp = rate(value.onTime, value.eligible);
    const detail = name + ' · ' + percent(otp) + ' on time · ' + events(value.eligible);
    return '<circle class="datum" data-stop="' + escape(id) + '" role="img" aria-label="' +
      escape(detail) + '" cx="' + x.toFixed(2) + '" cy="' + y.toFixed(2) + '" r="' +
      Math.min(8, 1.9 + Math.sqrt(value.eligible) * .48) + '" fill="' +
      (otp >= .75 ? "var(--blue)" : "var(--brick)") + '" fill-opacity=".78" stroke="#fff" stroke-width="1"><title>' +
      escape(detail) + '</title></circle>';
  }).join("");
  byId("stop-markers").innerHTML = points;
  byId("stop-table").innerHTML = groups.length ? table(["Stop", "Eligible", "On time"], groups.slice(0, 7).map(([id, value]) => [
    snapshot.stops[id][0], count(value.eligible), percent(rate(value.onTime, value.eligible))
  ])) : empty("No eligible stop observations.");
  updateStop(available);
  mapNavigation.refresh(route.value);
  stop.onchange = () => {
    updateStop(available);
    mapNavigation.reveal(mapSurface.querySelector(".datum.selected"));
  };
  mapSurface.onclick = event => {
    const id = event.target.closest("[data-stop]")?.dataset.stop;
    if (id) {
      stop.value = id;
      updateStop(available);
    }
  };
}

function updateStop(groups) {
  const selected = groups.get(stop.value);
  byId("stop-detail-title").textContent = selected ? snapshot.stops[stop.value][0] : "Stop details";
  byId("stop-detail").textContent = selected ?
    events(selected.eligible) + " · " + percent(rate(selected.onTime, selected.eligible)) + " on time" :
    "Choose a stop on the map or from the list.";
  mapSurface.querySelectorAll("[data-stop]").forEach(dot => {
    dot.classList.toggle("selected", dot.dataset.stop === stop.value);
  });
}

function renderHeadways(id) {
  const [pairs, bunched, frequent, onTime, ratio] = snapshot.headways[id] ?? [0, 0, 0, 0, null];
  byId("headway-kpis").innerHTML = metricCards([
    ["Headway pairs", count(pairs)], ["Bunched", percent(rate(bunched, pairs))],
    ["Adherence · frequent service", percent(rate(onTime, frequent))],
    ["Median actual / scheduled", ratio === null ? "—" : ratio.toFixed(2) + "×"]
  ]);
  const groups = Object.entries(snapshot.headways).filter(([key]) => key && (!id || key === id));
  if (!groups.length) {
    byId("scatter").innerHTML = empty("No headway pairs for this route.");
    byId("scatter-detail").textContent = "";
    return;
  }
  const xMax = Math.ceil(Math.max(...groups.map(([, values]) => values[0])) / 50) * 50;
  const grid = [0, 25, 50, 75, 100].map(tick => {
    const y = 178 - tick * 1.62;
    const x = 48 + tick / 100 * 641;
    return '<line class="grid" x1="48" x2="689" y1="' + y + '" y2="' + y + '"/>' +
      '<text x="41" y="' + (y + 4) + '" text-anchor="end">' + tick + '%</text>' +
      '<text x="' + x + '" y="198" text-anchor="middle">' + Math.round(tick / 100 * xMax) + '</text>';
  }).join("");
  const points = groups.map(([key, values]) => {
    const [n, b] = values;
    const detail = routeName(key) + ' · ' + percent(rate(b, n)) + ' bunched · ' + count(n) + ' pairs';
    return '<circle class="datum" role="img" tabindex="0" data-detail="' + escape(detail) +
      '" aria-label="' + escape(detail) + '" cx="' + (48 + n / xMax * 641) + '" cy="' +
      (178 - b / n * 162) + '" r="' + (id ? 6 : 4) + '" fill="var(--blue)" fill-opacity=".78"><title>' +
      escape(detail) + '</title></circle>';
  }).join("");
  byId("scatter").innerHTML = chart(720, 222, "Bunching percentage by number of observed headway pairs",
    grid + points + '<text x="360" y="219" text-anchor="middle">Observed headway pairs</text>'
  );
  const detail = byId("scatter-detail");
  detail.textContent = "Low pair counts can produce extreme rates.";
  byId("scatter").onfocusin = byId("scatter").onpointerover = event => {
    if (event.target.dataset.detail) detail.textContent = event.target.dataset.detail;
  };
}

function renderQuality(records, id) {
  const all = labels.map((_, index) => aggregate(records, index, null).get(""));
  const loose = all[0]?.eligible ?? 0;
  const header = '<div class="sensitivity-row sensitivity-heading"><span>Filter</span><span>Eligible sample</span><span>On time</span></div>';
  byId("sensitivity").innerHTML = header + labels.map((label, i) => {
    const value = all[i];
    const n = value?.eligible ?? 0;
    const share = percent(rate(n, loose));
    return '<div class="sensitivity-row"><strong>' + label + '</strong><div><span class="stack" role="img" aria-label="' +
      (loose ? share + ' retained' : 'No eligible observations') + '"><i class="on-time" style="width:' +
      (loose ? share : "0%") + '"></i></span><small>' + count(n) + ' · ' + share +
      ' retained</small></div><strong>' + percent(rate(value?.onTime, n), 2) + '</strong></div>';
  }).join("");
  const strict = all[2]?.eligible ?? 0;
  if (strict && loose) {
    const shift = 100 * (all[2].onTime / strict - all[0].onTime / loose);
    byId("quality-insight").textContent = 'Strict retains ' + percent(rate(strict, loose)) +
      ' of the Loose sample. The on-time rate shifts by ' + (shift >= 0 ? "+" : "−") +
      Math.abs(shift).toFixed(2) + ' percentage points.';
  } else {
    byId("quality-insight").textContent = "This selection has no Strict events to compare.";
  }

  const checks = new Map();
  for (const [key, level, name, checked, flagged] of snapshot.checks) {
    if (id && key !== id) continue;
    const check = checks.get(level + ":" + name) ?? { name, checked: 0, flagged: 0 };
    check.checked += checked;
    check.flagged += flagged;
    checks.set(level + ":" + name, check);
  }
  const top = [...checks.values()].filter(value => value.checked)
    .sort((a, b) => b.flagged / b.checked - a.flagged / a.checked).slice(0, 7);
  byId("check-table").innerHTML = top.length ? table(["Check", "Flagged / checked", "Rate"], top.map(item => [
    item.name.replaceAll("_", " "), count(item.flagged) + " / " + count(item.checked),
    percent(rate(item.flagged, item.checked), 2)
  ])) : empty("No checks for this route.");
}

function render() {
  const id = route.value;
  const level = Number(document.querySelector('input[name="level"]:checked').value);
  const records = id ? snapshot.timepoints.filter(row => row[0] === id) : snapshot.timepoints;
  const total = aggregate(records, level, null).get("") ??
    { scheduled: 0, inferred: 0, eligible: 0, onTime: 0, early: 0 };
  byId("kpis").innerHTML = metricCards([
    ["On-time performance", percent(rate(total.onTime, total.eligible))],
    ["Early", percent(rate(total.early, total.eligible))],
    ["Late", percent(rate(total.eligible - total.onTime - total.early, total.eligible))],
    ["Eligible timepoints", count(total.eligible)],
    ["Inferred coverage · all filters", percent(rate(total.inferred, total.scheduled))]
  ]);
  renderHours(records, level);
  renderRoutes(records, level);
  renderStops(records, level);
  renderHeadways(id);
  renderQuality(records, id);
}

for (const id of Object.keys(snapshot.routes).sort((a, b) => a.localeCompare(b, undefined, { numeric: true }))) {
  route.add(new Option(routeName(id), id));
}
route.addEventListener("change", render);
document.querySelectorAll('input[name="level"]').forEach(input => input.addEventListener("change", render));
byId("route-chart").addEventListener("click", event => {
  const button = event.target.closest("[data-route]");
  if (button) {
    route.value = button.dataset.route;
    render();
    route.focus({ preventScroll: true });
  }
});
render();
