"use strict";

// Administrator-only map and reporting, backed by /api/admin/dashboard.
window.UgnayDashboard = (() => {
  const byId = (id) => document.getElementById(id);
  const NS = "http://www.w3.org/2000/svg";
  const trustNames = { trusted: "Trusted", review: "Review", flagged: "Flagged" };
  const trustSymbols = { trusted: "✓", review: "!", flagged: "×" };
  const trustColors = { trusted: "#a9df82", review: "#dca52f", flagged: "#c12949" };
  let context, data, initialized = false, selected = null;
  let currentView = "dashboard", collapsed = false, lastFingerprint = "", mapPage = 0;
  let box = { x: 0, y: 0, width: 1000, height: 430 }, drag = null;
  let suppressMapClick = false;
  let browserSelected = null, browserFilter = "all", browserDetail = null, browserRequest = 0, browserDraft = null;
  let browserListFingerprint = "", deviceSaving = false, devicePinging = false;
  let motionEnabled = true;
  try { motionEnabled = localStorage.getItem("ugnay-motion") !== "off"; } catch { /* Storage is optional. */ }
  const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
  const mobileMap = matchMedia("(max-width: 700px)");

  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (className) element.className = className;
    return element;
  }
  function svg(tag, attrs = {}, text) {
    const element = document.createElementNS(NS, tag);
    Object.entries(attrs).forEach(([key, value]) => element.setAttribute(key, value));
    if (text !== undefined) element.textContent = text;
    return element;
  }
  function notify(id, text = "", success = false) {
    const element = byId(id); element.textContent = text; element.hidden = !text;
    element.classList.toggle("success", success);
  }
  const can = (permission) => context?.session.user.permissions.includes(permission);
  const date = (value) => value ? new Date(value).toLocaleString([], { dateStyle: "short", timeStyle: "short" }) : "Never";
  const latency = (value) => value == null ? "—" : `${value.toFixed(1)} ms`;
  const loss = (value) => value == null ? "—" : `${Number(value.toFixed(1))}%`;
  const initials = (value) => value.split(/[\s_.-]+/).filter(Boolean).slice(0, 2).map((word) => [...word][0]).join("").toUpperCase() || "?";
  const currentDevice = () => data?.devices.find((device) => device.id === selected);
  const canEditDevice = () => ["devices", "security"].includes(currentView) && can("devices.manage");
  const filteredDevices = () => {
    const query = currentView === "devices" ? byId("device-search").value.trim().toLowerCase() : "";
    return (data?.devices || []).filter((device) => `${device.name} ${device.hostname || ""} ${device.ip_address}`.toLowerCase().includes(query));
  };

  function syncMotion() {
    const pause = !motionEnabled || reducedMotion.matches;
    document.body.classList.toggle("motion-paused", pause);
    document.querySelectorAll(".network-map, #device-network-map").forEach((map) => {
      if (pause) map.pauseAnimations(); else map.unpauseAnimations();
    });
    if (byId("motion-enabled")) byId("motion-enabled").checked = motionEnabled;
  }
  reducedMotion.addEventListener("change", syncMotion);

  function selectView(view) {
    if (context?.session.user.role !== "admin") return;
    if (view === "access" && !can("users.manage")) return;
    currentView = view;
    byId("workspace").dataset.view = view;
    byId("device-search").hidden = view !== "devices";
    byId("map-disclosure").hidden = view === "dashboard";
    byId("map-description").textContent = view === "dashboard"
      ? "Devices are linked to the scanned subnet. Select a node to view its read-only profile. Zoom in and drag to pan. Use Fit to restore the map."
      : "Devices are linked to the scanned subnet. Select a node for its profile. Drag to pan; use the zoom controls to explore.";
    document.querySelectorAll("[data-view]").forEach((button) => {
      const active = button.dataset.view === view;
      button.classList.toggle("active", active);
      if (active) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current");
    });
    ["tests", "history", "reports", "security", "settings"].forEach((name) => { byId(`${name}-panel`).hidden = view !== name; });
    byId("admin-panel").hidden = view !== "access";
    byId("dashboard-overview").hidden = !["dashboard", "map"].includes(view);
    byId("devices-panel").hidden = view !== "devices";
    byId("map-stage").hidden = !["dashboard", "map"].includes(view);
    byId("device-board").hidden = !["dashboard", "map"].includes(view);
    byId("board-toggle").hidden = view === "devices";
    applyBoard(view === "devices" ? false : view === "map" ? true : collapsed);
    closeProfile();
    mapPage = 0; fit();
    if (data) { renderMap(); renderDevices(); renderActivities(); renderDeviceBrowser(); loadBrowserDetail(); }
    document.title = `${view === "map" ? "Network Map" : view[0].toUpperCase() + view.slice(1)} · UGNAY`;
    if (view === "access") context.loadUsers();
  }

  function applyBoard(hide) {
    byId("board-device-details").hidden = hide;
    byId("board-activity").hidden = hide;
    byId("device-board").classList.toggle("collapsed", hide);
    byId("board-toggle").textContent = hide ? "Show" : "Hide";
    byId("board-toggle").setAttribute("aria-expanded", String(!hide));
  }

  function render(next) {
    if (context?.session.user.role !== "admin") return;
    data = next;
    byId("local-ip").textContent = data.network?.local_ip || "Not detected";
    byId("network-subnet").textContent = data.network?.subnet || "Not detected";
    byId("device-count").textContent = String(data.devices.length);
    byId("last-scan").textContent = data.scanned_at ? new Date(data.scanned_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "Never";
    byId("last-scan").title = date(data.scanned_at);
    byId("scan").disabled = data.busy;
    byId("scan").textContent = data.busy && data.operation === "scan" ? "Scanning…" : "Scan network";
    byId("scan").setAttribute("aria-busy", String(data.busy && data.operation === "scan"));
    notify("workspace-message", data.error || (data.busy ? data.operation === "ping" ? "Ping test in progress…" : "Scanning the local network. This can take a few minutes on larger subnets." : ""), data.busy);
    byId("average-latency").textContent = latency(data.metrics.average_latency_ms);
    byId("packet-loss").textContent = loss(data.metrics.packet_loss_percent);
    byId("average-latency").title = `Latest tests for ${data.metrics.tested_devices} currently detected devices`;
    byId("run-test").disabled = !can("network.test") || data.busy || !data.devices.length;
    byId("profile-test").disabled = data.busy;
    byId("network-empty").hidden = !!data.network;
    byId("network-empty").querySelector("h2").textContent = data.busy ? "Looking for connections…" : "Every connection. In view.";
    byId("network-empty").querySelector("p").textContent = can("network.scan") ? "Scan your network to discover responding devices." : "An administrator or user can run a scan. Results will appear here.";
    const fingerprint = JSON.stringify(data);
    if (fingerprint === lastFingerprint) return;
    lastFingerprint = fingerprint;
    renderMap(); renderDevices(); renderActivities(); renderTests(); renderHistory(); renderReport(); renderSecurity();
    renderDeviceBrowser(); loadBrowserDetail();
    if (selected !== null) {
      if (currentDevice() || (selected === "network" && data.network)) showProfile(selected, true); else closeProfile();
    }
  }

  function renderMap() {
    const graph = svg("g", { class: "map-content" });
    if (!data.network) { byId("map-graph").replaceChildren(); return; }
    const devices = filteredDevices();
    const pageSize = mobileMap.matches ? 4 : 8;
    const pages = Math.max(1, Math.ceil(devices.length / pageSize));
    mapPage = Math.min(mapPage, pages - 1);
    const visible = devices.slice(mapPage * pageSize, mapPage * pageSize + pageSize);
    byId("map-pager").hidden = pages <= 1;
    byId("map-page").textContent = pages > 1 ? `${mapPage + 1} / ${pages}` : "";
    byId("map-prev").hidden = byId("map-next").hidden = pages <= 1;
    byId("map-prev").disabled = mapPage === 0; byId("map-next").disabled = mapPage >= pages - 1;
    const root = mobileMap.matches ? { x: 210, y: 210 } : { x: 455, y: 215 };
    const smallLayout = mobileMap.matches ? [{ x: 90, y: 95 }, { x: 325, y: 95 }, { x: 325, y: 295 }, { x: 90, y: 295 }] : [{ x: 250, y: 126 }, { x: 610, y: 126 }, { x: 790, y: 223 }];
    visible.forEach((device, index) => {
      const angle = (-145 + index * 360 / visible.length) * Math.PI / 180;
      const point = mobileMap.matches || visible.length <= 3 ? smallLayout[index] : { x: 500 + 345 * Math.cos(angle), y: 193 + 120 * Math.sin(angle) };
      const edge = svg("line", { x1: root.x, y1: root.y, x2: point.x, y2: point.y,
        class: `map-edge${selected === device.id ? " selected" : ""}`, "data-edge": device.id });
      graph.append(edge);
      const packet = svg("circle", { r: 2.5, fill: "#d8eeff", opacity: .65 });
      const motion = svg("animateMotion", { dur: `${7 + index % 4}s`, begin: `${-(index % 5)}s`, repeatCount: "indefinite", path: `M${root.x} ${root.y} L${point.x} ${point.y}` });
      packet.append(motion); graph.append(packet);
      const group = svg("g", { class: `map-node${selected === device.id ? " selected" : ""}`, transform: `translate(${point.x} ${point.y})`, tabindex: "0", role: "button", "aria-label": `${device.name}, ${device.ip_address}, ${trustNames[device.trust]}`, "data-node": device.id });
      group.append(svg("title", {}, `${device.name} · ${device.ip_address} · ${trustNames[device.trust]}`));
      [48, 38, 29].forEach((r) => group.append(svg("circle", { r, class: "node-ring" })));
      group.append(svg("circle", { r: 26, class: `node-core palette-${index % 5}` }));
      group.append(svg("text", { y: 0, class: `node-initials palette-${index % 5}` }, initials(device.name)));
      const limit = mobileMap.matches ? 16 : 22;
      const label = device.name.length > limit ? device.name.slice(0, limit - 1) + "…" : device.name;
      group.append(svg("text", { y: 66, class: "node-name" }, label));
      const badgeX = Math.min(93, label.length * 3.6 + 12);
      group.append(svg("circle", { cx: badgeX, cy: 61, r: 8, fill: trustColors[device.trust] }));
      group.append(svg("text", { x: badgeX, y: 61, class: "node-symbol" }, trustSymbols[device.trust]));
      group.append(svg("text", { y: 85, class: "node-ip" }, device.ip_address));
      group.addEventListener("click", () => showProfile(device.id));
      group.addEventListener("keydown", (event) => { if (["Enter", " "].includes(event.key)) { event.preventDefault(); showProfile(device.id); } });
      graph.append(group);
    });
    const hub = svg("g", { class: `map-node${selected === "network" ? " selected" : ""}`, "data-node": "network", transform: `translate(${root.x} ${root.y})`, tabindex: "0", role: "button", "aria-label": `View scanned network ${data.network.subnet}. Lines indicate subnet membership.` });
    hub.append(svg("circle", { r: 49, class: "node-halo" }));
    [48, 39, 30].forEach((r) => hub.append(svg("circle", { r, class: "node-ring" })));
    hub.append(svg("circle", { r: 26, fill: "#fff", stroke: "#233a53", "stroke-width": 3 }));
    hub.append(svg("path", { d: "M-8-12H8V-3H-8ZM0-3V8M-13 8H13M-13 8V14M13 8V14M-17 14H-9M9 14H17", fill: "none", stroke: "#15283e", "stroke-width": 2.6, "stroke-linejoin": "round" }));
    hub.append(svg("text", { y: 66, class: "node-name" }, "Local network"));
    hub.append(svg("text", { y: 84, class: "node-ip" }, data.network.subnet));
    hub.addEventListener("click", () => showProfile("network"));
    hub.addEventListener("keydown", (event) => { if (["Enter", " "].includes(event.key)) { event.preventDefault(); showProfile("network"); } });
    graph.append(hub);
    byId("map-graph").replaceChildren(graph);
    syncMotion();
  }

  function trustBadge(device) { return node("span", trustNames[device.trust], `trust-badge ${device.trust}`); }
  function pingBadge(device) {
    const status = device.ping?.status;
    const type = !status ? "untested" : status === "Responding" ? "responding" : status === "Unreachable" ? "unreachable" : "loss";
    return node("span", type === "untested" ? "−  Not tested" : type === "responding" ? "✓  Responded" : type === "unreachable" ? "◷  No ping response" : "!  Packet loss", `ping-badge ${type}`);
  }
  function renderDevices() {
    const devices = currentView === "dashboard" ? filteredDevices().slice(0, 4) : filteredDevices();
    byId("scan-time").textContent = currentView === "dashboard" ? "Go to the Devices tab to see the full list." : data.scanned_at ? "Select a device to see its latest test." : "Start a scan to discover your network.";
    byId("devices-empty").hidden = devices.length > 0;
    byId("devices-empty").textContent = data.devices.length ? "No devices match your search." : data.scanned_at ? "No devices responded to the latest scan." : "No devices yet. Start a network scan.";
    byId("device-rows").replaceChildren(...devices.map((device) => {
      const row = node("tr"); row.dataset.device = device.id; row.tabIndex = 0;
      row.classList.toggle("selected", selected === device.id);
      row.setAttribute("aria-label", `${device.name}, ${device.ip_address}, ${trustNames[device.trust]}`);
      const trust = node("td"), ping = node("td"); trust.append(trustBadge(device)); ping.append(pingBadge(device));
      row.append(node("td", device.name), node("td", device.ip_address), trust, ping);
      row.addEventListener("click", () => showProfile(device.id));
      row.addEventListener("keydown", (event) => { if (["Enter", " "].includes(event.key)) { event.preventDefault(); showProfile(device.id); } });
      return row;
    }));
  }
  function activities(items) {
    return items.map((activity) => {
      const row = node("li"), time = node("time", date(activity.at)); time.dateTime = activity.at;
      row.append(time, node("span", activity.message));
      if (activity.actor) row.title = `By ${activity.actor}`;
      return row;
    });
  }

  function browserDevice() { return data?.devices.find((device) => device.id === browserSelected); }
  function facts(values) {
    return values.map(([label, value]) => { const item = node("div"); item.append(node("dt", label), node("dd", value)); return item; });
  }
  function renderDeviceBrowser() {
    if (currentView !== "devices" || !data) return;
    const devices = filteredDevices().filter((device) => browserFilter === "all" || device.trust === browserFilter);
    if (!devices.some((device) => device.id === browserSelected)) {
      browserSelected = devices[0]?.id ?? null; browserDetail = null; browserDraft = null; browserRequest += 1;
      notify("selected-device-message");
    }
    document.querySelectorAll("[data-device-filter]").forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.deviceFilter === browserFilter)));
    byId("device-list-empty").hidden = devices.length > 0;
    byId("device-list-empty").textContent = data.devices.length ? "No devices match your search or trust filter." : "No detected devices yet. Scan your network to get started.";
    byId("devices-go-scan").hidden = data.devices.length > 0;
    const fingerprint = JSON.stringify([browserSelected, devices.map((device) => [device.id, device.name, device.trust, device.ip_address])]);
    if (fingerprint !== browserListFingerprint) {
      browserListFingerprint = fingerprint;
      const activeId = document.activeElement?.closest("[data-browser-device]")?.dataset.browserDevice;
      byId("device-list").replaceChildren(...devices.map((device) => {
        const button = node("button", undefined, "device-list-item"); button.type = "button"; button.dataset.browserDevice = device.id;
        button.setAttribute("aria-pressed", String(device.id === browserSelected)); button.setAttribute("aria-controls", "selected-device-card device-latency-chart");
        const avatar = node("span", undefined, "profile-avatar"); avatar.setAttribute("aria-hidden", "true");
        avatar.append(Object.assign(node("img"), { src: "/assets/device-wifi.svg", alt: "", width: 30, height: 30 }));
        const copy = node("span", undefined, "device-list-copy"), name = node("span", undefined, "profile-name-line");
        name.append(node("strong", device.name), trustBadge(device)); copy.append(name, node("small", device.ip_address));
        const chevron = node("span", "›", "device-list-chevron"); chevron.setAttribute("aria-hidden", "true"); button.append(avatar, copy, chevron);
        button.addEventListener("click", () => {
          if (browserSelected !== device.id) { browserSelected = device.id; browserDetail = null; browserDraft = null; notify("selected-device-message"); }
          renderDeviceBrowser(); loadBrowserDetail();
        });
        return button;
      }));
      if (activeId) byId("device-list").querySelector(`[data-browser-device="${activeId}"]`)?.focus({ preventScroll: true });
    }
    renderSelectedDevice();
  }
  async function loadBrowserDetail() {
    if (currentView !== "devices" || browserSelected === null || !context) return;
    const identifier = browserSelected, session = context.session, request = ++browserRequest;
    try {
      const result = await context.api(`/api/admin/devices/${identifier}`);
      if (context?.session !== session || currentView !== "devices" || browserSelected !== identifier || request !== browserRequest) return;
      browserDetail = result.device; renderSelectedDevice();
    } catch (error) {
      if (context?.session === session && currentView === "devices" && browserSelected === identifier && request === browserRequest) notify("selected-device-message", `Could not load device history: ${error.message}`);
    }
  }
  function renderSelectedDevice() {
    if (currentView !== "devices") return;
    const device = browserDevice();
    byId("device-selection-empty").hidden = !!device;
    byId("selected-device-main").hidden = byId("selected-device-activity").hidden = !device;
    byId("selected-device-measurements").hidden = !device;
    renderDeviceLatency(device);
    if (!device) return;
    byId("selected-device-name").textContent = device.name;
    if (!byId("selected-device-avatar").firstChild) byId("selected-device-avatar").append(Object.assign(node("img"), { src: "/assets/device-wifi.svg", alt: "", width: 30, height: 30 }));
    byId("selected-device-ip").textContent = device.ip_address;
    byId("selected-device-trust").className = `trust-badge ${device.trust}`;
    byId("selected-device-trust").textContent = trustNames[device.trust];
    byId("selected-device-facts").replaceChildren(...facts([
      ["Detected hostname", device.hostname || "Hostname unavailable"], ["Device type", device.device_type || "Not identified"],
      ["Connected subnet", device.subnet], ["IP Address", device.ip_address], ["MAC Address", device.mac_address || "Not available"],
      ["First discovered", date(device.first_seen)], ["Last scan response", date(device.last_seen)],
    ]));
    byId("selected-device-measurements").replaceChildren(...facts([
      ["Average latency", latency(device.ping?.average_latency_ms)], ["Maximum latency", latency(device.ping?.maximum_latency_ms)],
      ["Ping status", device.ping?.status || "Not tested"], ["Packet loss", loss(device.ping?.packet_loss_percent)],
      ["Replies received", device.ping ? `${device.ping.replies.filter((reply) => reply.latency_ms != null).length} / ${device.ping.replies.length}` : "Not tested"], ["Last ping test", device.ping ? date(device.ping.tested_at) : "Not tested"],
    ]));
    if (browserDraft !== device.id) {
      browserDraft = device.id; byId("selected-device-label").value = device.label; byId("selected-device-trust-input").value = device.trust;
    }
    byId("selected-device-form").hidden = !can("devices.manage");
    ["selected-device-label", "selected-device-trust-input", "selected-device-save"].forEach((id) => { byId(id).disabled = deviceSaving || !can("devices.manage"); });
    byId("selected-device-save").textContent = deviceSaving ? "Saving…" : "Save changes";
    byId("device-run-ping").hidden = !can("network.test");
    byId("device-run-ping").disabled = data.busy || devicePinging;
    byId("device-run-ping").querySelector("span").textContent = data.testing_device === device.id || devicePinging ? "Testing…" : "Run ping test";
    const history = browserDetail?.id === device.id ? browserDetail.activities : data.activities.filter((item) => item.device_id === device.id);
    byId("selected-device-activity-list").replaceChildren(...activities(history || []));
    byId("selected-device-activity-empty").hidden = !!history?.length;
  }
  function renderDeviceLatency(device) {
    const plot = byId("device-chart-plot"); plot.replaceChildren(); byId("device-latency-legend").replaceChildren(); byId("device-reply-data").replaceChildren();
    let tests = device ? (browserDetail?.id === device.id ? browserDetail.ping_history || [] : data.test_history.filter((test) => test.device_id === device.id)) : [];
    if (device?.ping && !tests.some((test) => test.tested_at === device.ping.tested_at)) tests = [device.ping, ...tests];
    tests = tests.slice(0, 3);
    byId("device-latency-chart").toggleAttribute("hidden", !tests.length);
    byId("device-latency-empty").hidden = !!tests.length;
    byId("device-latency-empty").textContent = device ? "Run a ping test to see measured reply latency for this device." : "Select a device to view its reply latency.";
    const samples = tests.flatMap((test) => test.replies).filter((reply) => reply.latency_ms != null);
    byId("device-latency-description").textContent = tests.length && !samples.length ? "All requests timed out; no latency samples were received." : "Latency (ms) by request number; gaps indicate timeouts.";
    if (!tests.length) return;
    byId("device-chart-title").textContent = `${device.name} reply latency`;
    byId("device-chart-description").textContent = `Latest ${tests.length} ping test${tests.length === 1 ? "" : "s"} for ${device.name}. ` + tests[0].replies.map((reply) => `Request ${reply.sequence}: ${reply.latency_ms == null ? "timed out" : latency(reply.latency_ms)}`).join("; ");
    byId("device-reply-data").replaceChildren(...tests[0].replies.map((reply) => { const row = node("tr"); row.append(node("td", reply.sequence), node("td", reply.latency_ms == null ? "Timed out" : latency(reply.latency_ms))); return row; }));
    const maximum = Math.max(1, ...samples.map((reply) => reply.latency_ms));
    const magnitude = 10 ** Math.floor(Math.log10(maximum / 4)), roughStep = maximum / 4 / magnitude;
    const step = (roughStep <= 1 ? 1 : roughStep <= 2 ? 2 : roughStep <= 5 ? 5 : 10) * magnitude;
    const ceiling = Math.ceil(maximum / step) * step;
    const requests = Math.max(2, ...tests.flatMap((test) => test.replies.map((reply) => reply.sequence)));
    const x = (sequence) => 18 + (sequence - 1) / (requests - 1) * 398, y = (value) => 264 - value / ceiling * 248;
    for (let tick = 0; tick <= Math.round(ceiling / step); tick += 1) {
      const value = Number((tick * step).toPrecision(4)), position = y(value);
      plot.append(svg("line", { x1: 18, y1: position, x2: 416, y2: position, class: "latency-grid" }), svg("text", { x: 10, y: position + 4, "text-anchor": "end", class: "latency-axis" }, String(value)));
    }
    for (let sequence = 1; sequence <= requests; sequence += 1) {
      if (sequence !== 1 && sequence !== requests && (sequence - 1) % Math.ceil(requests / 6)) continue;
      plot.append(svg("line", { x1: x(sequence), y1: 16, x2: x(sequence), y2: 264, class: "latency-grid" }), svg("text", { x: x(sequence), y: 292, "text-anchor": "middle", class: "latency-axis" }, String(sequence)));
    }
    const colors = ["#a7d7ff", "#ed7da9", "#a9df82"];
    tests.forEach((test, index) => {
      const label = node("span"), swatch = node("i", undefined, "latency-swatch"); swatch.style.setProperty("--series-color", colors[index]); swatch.setAttribute("aria-hidden", "true");
      label.append(swatch, document.createTextNode(`${index === 0 ? "Latest" : "Previous"} · ${date(test.tested_at)}`)); byId("device-latency-legend").append(label);
      const group = svg("g", { "data-ping-series": index }); let path = "";
      const finish = () => { if (path) group.prepend(svg("path", { d: path, stroke: colors[index], class: "latency-path" })); path = ""; };
      test.replies.forEach((reply) => {
        const horizontal = x(reply.sequence);
        if (reply.latency_ms == null) {
          finish();
          if (index === 0) { const marker = svg("path", { d: `M${horizontal - 3} 270L${horizontal + 3} 276M${horizontal + 3} 270L${horizontal - 3} 276`, class: "latency-timeout" }); marker.append(svg("title", {}, `Request ${reply.sequence}: timed out`)); group.append(marker); }
          return;
        }
        path += `${path ? "L" : "M"}${horizontal} ${y(reply.latency_ms)} `;
        const point = svg("circle", { cx: horizontal, cy: y(reply.latency_ms), r: 3.5, fill: colors[index], class: "latency-point" });
        point.append(svg("title", {}, `Request ${reply.sequence}: ${latency(reply.latency_ms)}`)); group.append(point);
      });
      finish(); plot.append(group);
    });
  }
  function renderActivities() {
    byId("activity-list").replaceChildren(...activities(currentView === "dashboard" ? data.activities.slice(0, 11) : data.activities));
    byId("activity-empty").hidden = data.activities.length > 0;
    byId("history-activity").replaceChildren(...activities(data.activities));
  }

  function showProfile(identifier, refresh = false) {
    const network = identifier === "network" && data?.network;
    const device = data?.devices.find((item) => item.id === identifier);
    if (!device && !network) return;
    const changed = selected !== identifier;
    selected = identifier;
    const pageSize = mobileMap.matches ? 4 : 8;
    const position = filteredDevices().findIndex((item) => item.id === identifier);
    if (position >= 0 && Math.floor(position / pageSize) !== mapPage) {
      mapPage = Math.floor(position / pageSize); renderMap();
    }
    const profile = byId("device-profile");
    profile.hidden = false;
    byId("profile-name").textContent = network ? "Local network" : device.name;
    byId("profile-avatar").replaceChildren(network ? Object.assign(node("img"), { src: "/assets/network-placeholder.svg", alt: "", width: 28, height: 28 }) : document.createTextNode(initials(device.name)));
    byId("profile-ip").textContent = network ? network.local_ip : device.ip_address;
    byId("profile-trust").hidden = !!network;
    byId("profile-trust").className = network ? "trust-badge" : `trust-badge ${device.trust}`;
    byId("profile-trust").textContent = network ? "" : trustNames[device.trust];
    const facts = network
      ? [["Network range", network.subnet], ["Network type", "Local subnet"], ["Devices detected", String(data.devices.length)], ["Average latency", latency(data.metrics.average_latency_ms)], ["Last scan", date(data.scanned_at)], ["Packet loss", loss(data.metrics.packet_loss_percent)]]
      : [["Detected hostname", device.hostname || "Hostname unavailable"], ["Device type", "Network device"], ["Connected subnet", device.subnet], ["Average latency", latency(device.ping?.average_latency_ms)], ["First discovered", date(device.first_seen)], ["Packet loss", loss(device.ping?.packet_loss_percent)], ["Last scan response", date(device.last_seen)], ["Last ping test", device.ping ? date(device.ping.tested_at) : "Not tested"]];
    byId("profile-facts").replaceChildren(...facts.map(([title, value]) => { const fact = node("div"); fact.append(node("dt", title), node("dd", value)); return fact; }));
    const editable = !!device && canEditDevice();
    byId("device-edit-form").hidden = !editable;
    byId("device-label").disabled = byId("device-trust").disabled = byId("save-device").disabled = !editable;
    byId("profile-test").hidden = !device || currentView === "dashboard" || !can("network.test");
    byId("profile-test").disabled = data.busy;
    byId("profile-test").textContent = data.testing_device === identifier ? "Testing connection…" : "Test connection · 4 requests";
    if (changed || !refresh) {
      byId("device-label").value = device?.label || "";
      byId("device-trust").value = device?.trust || "review";
      notify("profile-message");
    }
    if (!profile.matches(":popover-open")) profile.showPopover();
    positionProfile();
    document.querySelectorAll("[data-node], [data-edge], tr[data-device]").forEach((element) => {
      element.classList.toggle("selected", (element.dataset.node || element.dataset.edge || element.dataset.device) === String(identifier));
    });
  }
  function positionProfile() {
    const profile = byId("device-profile");
    if (profile.hidden) return;
    const viewportWidth = document.documentElement.clientWidth;
    profile.style.maxWidth = `${viewportWidth - 32}px`;
    const anchor = ["dashboard", "map"].includes(currentView) ? byId("map-stage") : document.querySelector(".dashboard-content");
    const bounds = anchor.getBoundingClientRect();
    const left = mobileMap.matches ? (viewportWidth - profile.offsetWidth) / 2 : Math.max(16, Math.min(bounds.left - 8, viewportWidth - profile.offsetWidth - 16));
    const top = Math.max(16, Math.min(bounds.top + (["dashboard", "map"].includes(currentView) ? 230 : 160), innerHeight - profile.offsetHeight - 24));
    profile.style.left = `${left}px`; profile.style.top = `${top}px`;
  }
  function closeProfile() {
    const profile = byId("device-profile");
    const returnFocus = profile.contains(document.activeElement) ? document.querySelector(`[data-node="${selected}"], tr[data-device="${selected}"]`) : null;
    selected = null;
    if (profile.matches(":popover-open")) profile.hidePopover();
    profile.hidden = true;
    returnFocus?.focus({ preventScroll: true });
    document.querySelectorAll("[data-node], [data-edge], tr[data-device]").forEach((element) => element.classList.remove("selected"));
  }

  function cards(values) {
    return values.map(([label, value]) => { const card = node("div"); card.append(node("span", label), node("strong", value)); return card; });
  }
  function renderTests() {
    const previous = byId("test-device").value;
    byId("test-device").replaceChildren(...data.devices.map((device) => {
      const option = node("option", `${device.name} · ${device.ip_address}`); option.value = device.id; return option;
    }));
    if (data.devices.some((device) => String(device.id) === previous)) byId("test-device").value = previous;
    byId("test-device").disabled = !data.devices.length;
    byId("run-test").textContent = data.busy && data.operation === "ping" ? "Testing…" : "Run ping test";
    renderTestResult();
  }
  function renderTestResult() {
    const device = data?.devices.find((item) => String(item.id) === byId("test-device").value);
    const container = byId("test-result"); container.replaceChildren();
    if (!device?.ping) { container.append(node("p", device ? "No detailed ping test yet. Run a test to measure this connection." : "Scan for devices before running a test.", "muted")); return; }
    const metrics = node("div", undefined, "test-metrics");
    metrics.append(...cards([["Average latency", latency(device.ping.average_latency_ms)], ["Maximum latency", latency(device.ping.maximum_latency_ms)], ["Packet loss", loss(device.ping.packet_loss_percent)]]));
    const replies = node("div", undefined, "reply-list");
    replies.append(...device.ping.replies.map((reply) => {
      const result = node("div", undefined, reply.latency_ms == null ? "timeout" : "");
      result.append(node("small", `Request ${reply.sequence}`), node("span", reply.latency_ms == null ? "No response" : latency(reply.latency_ms))); return result;
    }));
    container.append(node("h2", device.name), node("p", `Tested ${date(device.ping.tested_at)}`, "muted"), metrics, replies);
  }
  async function runPing(identifier, count, messageId) {
    if (currentView === "dashboard" || !can("network.test")) return;
    try { await context.api(`/api/devices/${identifier}/ping`, { count }); notify(messageId); await context.refresh(); }
    catch (error) { notify(messageId, error.message); }
  }
  async function saveBrowserDevice(event) {
    event.preventDefault();
    if (currentView !== "devices" || !browserDevice() || !can("devices.manage") || deviceSaving) return;
    const identifier = browserSelected, session = context.session;
    deviceSaving = true; notify("selected-device-message"); renderSelectedDevice();
    try {
      await context.api(`/api/devices/${identifier}`, { label: byId("selected-device-label").value.trim(), trust: byId("selected-device-trust-input").value });
      if (context?.session !== session) return;
      if (browserSelected === identifier) browserDraft = null;
      await context.refresh();
      if (context?.session === session && currentView === "devices" && browserSelected === identifier) notify("selected-device-message", "Device details saved.", true);
    } catch (error) {
      if (context?.session === session && currentView === "devices" && browserSelected === identifier) notify("selected-device-message", error.message);
    } finally {
      if (context?.session === session) { deviceSaving = false; renderSelectedDevice(); }
    }
  }
  async function pingBrowserDevice() {
    if (currentView !== "devices" || !browserDevice() || !can("network.test") || data.busy || devicePinging) return;
    const identifier = browserSelected, session = context.session;
    devicePinging = true; notify("selected-device-message"); renderSelectedDevice();
    try { await context.api(`/api/devices/${identifier}/ping`, { count: 4 }); if (context?.session === session) await context.refresh(); }
    catch (error) { if (context?.session === session && currentView === "devices" && browserSelected === identifier) notify("selected-device-message", error.message); }
    finally { if (context?.session === session) { devicePinging = false; renderSelectedDevice(); } }
  }
  function renderHistory() {
    byId("scan-history-rows").replaceChildren(...data.scan_history.map((scan) => {
      const row = node("tr"); row.append(node("td", date(scan.scanned_at)), node("td", scan.subnet), node("td", scan.device_count)); return row;
    }));
  }
  function renderReport() {
    byId("report-summary").replaceChildren(...cards([["Devices detected", String(data.devices.length)], ["Latest average latency", latency(data.metrics.average_latency_ms)], ["Latest packet loss", loss(data.metrics.packet_loss_percent)], ["Last scan", date(data.scanned_at)]]));
    byId("download-report").disabled = !data.scanned_at;
  }
  function renderSecurity() {
    byId("trust-summary").replaceChildren(...cards(Object.entries(trustNames).map(([key, title]) => [title, String(data.devices.filter((device) => device.trust === key).length)])));
    byId("security-devices").replaceChildren(...data.devices.map((device) => {
      const button = node("button", undefined, "security-device"); button.type = "button";
      button.append(node("strong", device.name), node("small", device.ip_address), trustBadge(device));
      button.addEventListener("click", () => showProfile(device.id)); return button;
    }));
  }
  function downloadReport() {
    if (!data.scanned_at) return;
    const lines = ["UGNAY — Network snapshot", `Last scan: ${date(data.scanned_at)}`, `Local IP: ${data.network.local_ip}`, `Subnet: ${data.network.subnet}`, `Devices detected: ${data.devices.length}`, `Average latency (latest tests): ${latency(data.metrics.average_latency_ms)}`, `Packet loss (latest tests): ${loss(data.metrics.packet_loss_percent)}`, "", "Name | IP address | Trust | Ping status | Average latency | Packet loss", ...data.devices.map((device) => `${device.name} | ${device.ip_address} | ${trustNames[device.trust]} | ${device.status} | ${latency(device.ping?.average_latency_ms)} | ${loss(device.ping?.packet_loss_percent)}`), "", "Topology shows subnet membership; physical links are not detected.", "Trust is an administrator label stored by subnet/IP; it does not block traffic."];
    const blob = new Blob([lines.join("\n")], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob), link = node("a"); link.href = url; link.download = "UGNAY-network-report.txt"; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  const canPanMap = () => currentView === "map" || (currentView === "dashboard" && box.width < (mobileMap.matches ? 420 : 1000) - .01);
  function endDrag(event) {
    if (event && drag?.pointerId !== event.pointerId) return;
    const pointerId = drag?.pointerId, stage = byId("map-stage");
    drag = null; stage.classList.remove("panning");
    if (pointerId !== undefined && stage.hasPointerCapture(pointerId)) stage.releasePointerCapture(pointerId);
    if (event?.type === "pointercancel") suppressMapClick = false;
  }
  function updateBox() {
    byId("device-network-map").setAttribute("viewBox", `${box.x} ${box.y} ${box.width} ${box.height}`);
    byId("map-stage").classList.toggle("pan-enabled", canPanMap());
  }
  function zoom(factor) {
    endDrag();
    const baseWidth = mobileMap.matches ? 420 : 1000;
    const width = Math.max(baseWidth * .35, Math.min(baseWidth * 2.4, box.width * factor)), height = width * 430 / baseWidth;
    box = { x: box.x + (box.width - width) / 2, y: box.y + (box.height - height) / 2, width, height }; updateBox();
  }
  function fit() { endDrag(); box = { x: 0, y: 0, width: mobileMap.matches ? 420 : 1000, height: 430 }; updateBox(); }
  mobileMap.addEventListener("change", () => { if (context) { mapPage = 0; fit(); if (data) renderMap(); } });
  function initialize() {
    initialized = true;
    document.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", () => selectView(button.dataset.view)));
    byId("board-toggle").addEventListener("click", () => { collapsed = byId("board-toggle").getAttribute("aria-expanded") === "true"; applyBoard(collapsed); });
    byId("view-reports").addEventListener("click", () => selectView("reports"));
    byId("account-menu-toggle").addEventListener("click", () => { const open = byId("account-menu").hidden; byId("account-menu").hidden = !open; byId("account-menu-toggle").setAttribute("aria-expanded", String(open)); });
    byId("close-profile").addEventListener("click", closeProfile);
    window.addEventListener("resize", positionProfile);
    window.addEventListener("scroll", positionProfile, { passive: true });
    byId("device-search").addEventListener("input", () => { renderDeviceBrowser(); loadBrowserDetail(); });
    document.querySelectorAll("[data-device-filter]").forEach((button) => button.addEventListener("click", () => { browserFilter = button.dataset.deviceFilter; renderDeviceBrowser(); loadBrowserDetail(); }));
    byId("devices-go-scan").addEventListener("click", () => selectView("dashboard"));
    byId("selected-device-form").addEventListener("submit", saveBrowserDevice);
    byId("device-run-ping").addEventListener("click", pingBrowserDevice);
    byId("device-edit-form").addEventListener("submit", async (event) => {
      event.preventDefault(); if (!currentDevice() || !canEditDevice()) return;
      const identifier = selected; byId("save-device").disabled = true;
      try { await context.api(`/api/devices/${identifier}`, { label: byId("device-label").value.trim(), trust: byId("device-trust").value }); await context.refresh(); notify("profile-message", "Device details saved.", true); }
      catch (error) { notify("profile-message", error.message); }
      finally { byId("save-device").disabled = false; }
    });
    byId("profile-test").addEventListener("click", async () => { if (!currentDevice() || currentView === "dashboard" || !can("network.test")) return; byId("profile-test").disabled = true; await runPing(selected, 4, "profile-message"); if (data) byId("profile-test").disabled = data.busy; });
    byId("test-form").addEventListener("submit", async (event) => { event.preventDefault(); if (!byId("test-device").value) return; byId("run-test").disabled = true; await runPing(Number(byId("test-device").value), Number(byId("test-count").value), "test-message"); if (data) byId("run-test").disabled = data.busy || !can("network.test"); });
    byId("test-device").addEventListener("change", renderTestResult);
    byId("download-report").addEventListener("click", downloadReport);
    byId("motion-enabled").addEventListener("change", () => { motionEnabled = byId("motion-enabled").checked; try { localStorage.setItem("ugnay-motion", motionEnabled ? "on" : "off"); } catch { /* Optional preference. */ } syncMotion(); });
    byId("map-zoom-in").addEventListener("click", () => zoom(.8)); byId("map-zoom-out").addEventListener("click", () => zoom(1.25)); byId("map-fit").addEventListener("click", fit);
    byId("map-prev").addEventListener("click", () => { mapPage = Math.max(0, mapPage - 1); closeProfile(); renderMap(); });
    byId("map-next").addEventListener("click", () => { mapPage += 1; closeProfile(); renderMap(); });
    const map = byId("device-network-map"), stage = byId("map-stage");
    stage.addEventListener("pointerdown", (event) => {
      if (event.isPrimary === false) return;
      suppressMapClick = false;
      if (!canPanMap() || event.button !== 0 || event.target.closest(".map-toolbar")) return;
      const inverse = map.getScreenCTM()?.inverse();
      if (!inverse) return;
      drag = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, box: { ...box }, inverse, moved: false };
    });
    window.addEventListener("pointermove", (event) => {
      if (!drag || event.pointerId !== drag.pointerId) return;
      const dx = event.clientX - drag.x, dy = event.clientY - drag.y;
      if (!drag.moved && Math.hypot(dx, dy) < 4) return;
      if (!drag.moved) {
        drag.moved = true; suppressMapClick = true;
        stage.setPointerCapture(event.pointerId); stage.classList.add("panning");
      }
      event.preventDefault();
      box.x = drag.box.x - dx * drag.inverse.a - dy * drag.inverse.c;
      box.y = drag.box.y - dx * drag.inverse.b - dy * drag.inverse.d;
      updateBox();
    }, { passive: false });
    window.addEventListener("pointerup", endDrag);
    window.addEventListener("pointercancel", endDrag);
    stage.addEventListener("lostpointercapture", (event) => { if (event.target === stage) endDrag(event); });
    stage.addEventListener("click", (event) => {
      if (!suppressMapClick || event.detail === 0) return;
      suppressMapClick = false; event.preventDefault(); event.stopImmediatePropagation();
    }, true);
    stage.addEventListener("wheel", (event) => { if (event.ctrlKey) { event.preventDefault(); zoom(event.deltaY < 0 ? .9 : 1.1); } }, { passive: false });
    document.addEventListener("keydown", (event) => { if (event.key === "Escape") { closeProfile(); byId("account-menu").hidden = true; byId("account-menu-toggle").setAttribute("aria-expanded", "false"); } });
    document.addEventListener("click", (event) => {
      if (!event.target.closest(".sidebar-account")) { byId("account-menu").hidden = true; byId("account-menu-toggle").setAttribute("aria-expanded", "false"); }
      if (!event.target.closest("#device-profile, .map-node, .map-toolbar, tr[data-device], .security-device, #board-toggle")) closeProfile();
    });
  }

  function mount(options) {
    if (options.session.user.role !== "admin" || !options.session.user.permissions.includes("dashboard.view")) {
      throw new Error("Administrator access is required for this dashboard.");
    }
    context = options; if (!initialized) initialize();
    lastFingerprint = ""; selected = null; data = null; mapPage = 0; collapsed = false;
    browserSelected = null; browserFilter = "all"; browserDetail = null; browserDraft = null; browserListFingerprint = ""; browserRequest += 1; deviceSaving = devicePinging = false;
    byId("access-nav").hidden = !can("users.manage");
    byId("account-initials").textContent = initials(context.session.user.username);
    byId("account-menu-email").textContent = context.session.user.email || "Temporary guest account";
    byId("role-badge").textContent = { admin: "Administrator", user: "User", guest: "Guest" }[context.session.user.role];
    byId("device-search").value = "";
    byId("run-test").hidden = !can("network.test");
    fit(); selectView("dashboard"); syncMotion();
  }
  function reset() {
    endDrag();
    data = null; context = null; lastFingerprint = "";
    browserSelected = null; browserFilter = "all"; browserDetail = null; browserDraft = null; browserListFingerprint = ""; browserRequest += 1; deviceSaving = devicePinging = false;
    closeProfile(); byId("account-menu").hidden = true;
    // Do not leave private dashboard data in the page after logout or a role change.
    ["map-graph", "device-rows", "activity-list", "history-activity", "scan-history-rows", "test-device", "test-result", "report-summary", "trust-summary", "security-devices", "user-rows", "profile-facts", "profile-name", "profile-ip", "profile-avatar", "profile-trust", "account-menu-email", "permissions-list", "account-email", "session-expiry", "welcome-name", "role-badge"].forEach((id) => byId(id).replaceChildren());
    ["workspace-message", "admin-message", "profile-message", "test-message"].forEach((id) => notify(id));
    ["device-list", "selected-device-name", "selected-device-avatar", "selected-device-ip", "selected-device-trust", "selected-device-facts", "selected-device-measurements", "selected-device-activity-list", "device-chart-plot", "device-latency-legend", "device-reply-data", "device-chart-title", "device-chart-description"].forEach((id) => byId(id).replaceChildren());
    byId("selected-device-form").reset(); notify("selected-device-message");
    ["local-ip", "network-subnet"].forEach((id) => { byId(id).textContent = "Not detected"; });
    byId("device-count").textContent = "0"; byId("last-scan").textContent = "Never";
    byId("last-scan").removeAttribute("title");
    byId("device-search").value = ""; byId("account-initials").textContent = "U";
    byId("average-latency").textContent = byId("packet-loss").textContent = "—";
    byId("device-edit-form").reset();
  }
  return { mount, render, reset, syncMotion };
})();
