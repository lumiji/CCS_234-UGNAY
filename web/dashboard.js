"use strict";

// Administrator-only map and reporting, backed by /api/admin/dashboard.
window.UgnayDashboard = (() => {
  const byId = (id) => document.getElementById(id);
  const NS = "http://www.w3.org/2000/svg";
  const trustNames = { trusted: "Trusted", review: "Review", flagged: "Flagged" };
  const trustSymbols = { trusted: "✓", review: "!", flagged: "×" };
  const trustColors = { trusted: "#a9df82", review: "#dca52f", flagged: "#c12949" };
  let context, data, initialized = false, selected = null, pinned = false, closeTimer;
  let currentView = "dashboard", collapsed = false, lastFingerprint = "", mapPage = 0;
  let box = { x: 0, y: 0, width: 1000, height: 430 }, drag = null;
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
  const filteredDevices = () => {
    const query = byId("device-search").value.trim().toLowerCase();
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
    document.querySelectorAll("[data-view]").forEach((button) => {
      const active = button.dataset.view === view;
      button.classList.toggle("active", active);
      if (active) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current");
    });
    ["tests", "history", "reports", "security", "settings"].forEach((name) => { byId(`${name}-panel`).hidden = view !== name; });
    byId("admin-panel").hidden = view !== "access";
    byId("map-stage").hidden = !["dashboard", "map"].includes(view);
    byId("device-board").hidden = !["dashboard", "devices", "map"].includes(view);
    byId("device-board").classList.toggle("full-board", view === "devices");
    byId("board-toggle").hidden = view === "devices";
    applyBoard(view === "devices" ? false : view === "map" ? true : collapsed);
    closeProfile();
    document.title = `${view === "map" ? "Network Map" : view[0].toUpperCase() + view.slice(1)} · UGNAY`;
    if (view === "access") context.loadUsers();
  }

  function applyBoard(hide) {
    byId("board-body").hidden = hide;
    byId("device-board").classList.toggle("collapsed", hide);
    byId("board-toggle").textContent = hide ? "Show devices" : "Hide";
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
    byId("scan-time").textContent = data.scanned_at ? "Select a device to see its latest test." : "Start a scan to discover your network.";
    byId("run-test").disabled = !can("network.test") || data.busy || !data.devices.length;
    byId("profile-test").disabled = data.busy;
    byId("network-empty").hidden = !!data.network;
    byId("network-empty").querySelector("h2").textContent = data.busy ? "Looking for connections…" : "Every connection. In view.";
    byId("network-empty").querySelector("p").textContent = can("network.scan") ? "Scan your network to discover responding devices." : "An administrator or user can run a scan. Results will appear here.";
    const fingerprint = JSON.stringify(data);
    if (fingerprint === lastFingerprint) return;
    lastFingerprint = fingerprint;
    renderMap(); renderDevices(); renderActivities(); renderTests(); renderHistory(); renderReport(); renderSecurity();
    if (selected !== null) {
      if (currentDevice()) showProfile(selected, pinned, true); else closeProfile();
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
      group.addEventListener("mouseenter", () => { clearTimeout(closeTimer); if (!pinned) showProfile(device.id, false); });
      group.addEventListener("mouseleave", scheduleClose);
      group.addEventListener("focus", () => { if (!pinned) showProfile(device.id, false); });
      group.addEventListener("blur", scheduleClose);
      group.addEventListener("click", () => showProfile(device.id, true));
      group.addEventListener("keydown", (event) => { if (["Enter", " "].includes(event.key)) { event.preventDefault(); showProfile(device.id, true); } });
      graph.append(group);
    });
    const hub = svg("g", { transform: `translate(${root.x} ${root.y})`, role: "img", "aria-label": `Scanned subnet ${data.network.subnet}. Lines indicate subnet membership.` });
    hub.append(svg("circle", { r: 49, class: "node-halo" }));
    [48, 39, 30].forEach((r) => hub.append(svg("circle", { r, class: "node-ring" })));
    hub.append(svg("circle", { r: 26, fill: "#fff", stroke: "#233a53", "stroke-width": 3 }));
    hub.append(svg("path", { d: "M-8-12H8V-3H-8ZM0-3V8M-13 8H13M-13 8V14M13 8V14M-17 14H-9M9 14H17", fill: "none", stroke: "#15283e", "stroke-width": 2.6, "stroke-linejoin": "round" }));
    hub.append(svg("text", { y: 66, class: "node-name" }, "Local network"));
    hub.append(svg("text", { y: 84, class: "node-ip" }, data.network.subnet));
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
    const devices = filteredDevices();
    byId("devices-empty").hidden = devices.length > 0;
    byId("devices-empty").textContent = data.devices.length ? "No devices match your search." : data.scanned_at ? "No devices responded to the latest scan." : "No devices yet. Start a network scan.";
    byId("device-rows").replaceChildren(...devices.map((device) => {
      const row = node("tr"); row.dataset.device = device.id; row.tabIndex = 0;
      row.classList.toggle("selected", selected === device.id);
      row.setAttribute("aria-label", `${device.name}, ${device.ip_address}, ${trustNames[device.trust]}`);
      const trust = node("td"), ping = node("td"); trust.append(trustBadge(device)); ping.append(pingBadge(device));
      row.append(node("td", device.name), node("td", device.ip_address), trust, ping);
      row.addEventListener("click", () => showProfile(device.id, true));
      row.addEventListener("keydown", (event) => { if (["Enter", " "].includes(event.key)) { event.preventDefault(); showProfile(device.id, true); } });
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
  function renderActivities() {
    byId("activity-list").replaceChildren(...activities(data.activities));
    byId("activity-empty").hidden = data.activities.length > 0;
    byId("history-activity").replaceChildren(...activities(data.activities));
  }

  function showProfile(identifier, pin, refresh = false) {
    clearTimeout(closeTimer);
    const device = data?.devices.find((item) => item.id === identifier);
    if (!device) return;
    const changed = selected !== identifier;
    selected = identifier; pinned = pin;
    const pageSize = mobileMap.matches ? 4 : 8;
    const position = filteredDevices().findIndex((item) => item.id === identifier);
    if (position >= 0 && Math.floor(position / pageSize) !== mapPage) {
      mapPage = Math.floor(position / pageSize); renderMap();
    }
    byId("device-profile").hidden = false;
    byId("profile-name").textContent = device.name;
    byId("profile-avatar").textContent = initials(device.name);
    byId("profile-ip").textContent = device.ip_address;
    byId("profile-trust").className = `trust-badge ${device.trust}`;
    byId("profile-trust").textContent = `${trustSymbols[device.trust]} ${trustNames[device.trust]}`;
    const facts = [["Detected hostname", device.hostname || "Hostname unavailable"], ["Connected subnet", device.subnet], ["First discovered", date(device.first_seen)], ["Last scan response", date(device.last_seen)], ["Average latency", latency(device.ping?.average_latency_ms)], ["Packet loss", loss(device.ping?.packet_loss_percent)], ["Last ping test", device.ping ? date(device.ping.tested_at) : "Not tested"]];
    byId("profile-facts").replaceChildren(...facts.flatMap(([title, value]) => [node("dt", title), node("dd", value)]));
    byId("device-edit-form").hidden = !can("devices.manage");
    byId("profile-test").hidden = !can("network.test");
    byId("profile-test").disabled = data.busy;
    byId("profile-test").textContent = data.testing_device === identifier ? "Testing connection…" : "Test connection · 4 requests";
    if (changed || !refresh) {
      byId("device-label").value = device.label;
      byId("device-trust").value = device.trust;
      notify("profile-message");
    }
    byId("device-profile").querySelector(".profile-hint").hidden = pinned;
    document.querySelectorAll("[data-node], [data-edge], tr[data-device]").forEach((element) => {
      element.classList.toggle("selected", Number(element.dataset.node || element.dataset.edge || element.dataset.device) === identifier);
    });
  }
  function scheduleClose() {
    clearTimeout(closeTimer);
    closeTimer = setTimeout(() => {
      if (!pinned && !byId("device-profile").contains(document.activeElement)) closeProfile();
    }, 300);
  }
  function closeProfile() {
    clearTimeout(closeTimer); selected = null; pinned = false;
    byId("device-profile").hidden = true;
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
    try { await context.api(`/api/devices/${identifier}/ping`, { count }); notify(messageId); await context.refresh(); }
    catch (error) { notify(messageId, error.message); }
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
      button.addEventListener("click", () => showProfile(device.id, true)); return button;
    }));
  }
  function downloadReport() {
    if (!data.scanned_at) return;
    const lines = ["UGNAY — Network snapshot", `Last scan: ${date(data.scanned_at)}`, `Local IP: ${data.network.local_ip}`, `Subnet: ${data.network.subnet}`, `Devices detected: ${data.devices.length}`, `Average latency (latest tests): ${latency(data.metrics.average_latency_ms)}`, `Packet loss (latest tests): ${loss(data.metrics.packet_loss_percent)}`, "", "Name | IP address | Trust | Ping status | Average latency | Packet loss", ...data.devices.map((device) => `${device.name} | ${device.ip_address} | ${trustNames[device.trust]} | ${device.status} | ${latency(device.ping?.average_latency_ms)} | ${loss(device.ping?.packet_loss_percent)}`), "", "Topology shows subnet membership; physical links are not detected.", "Trust is an administrator label stored by subnet/IP; it does not block traffic."];
    const blob = new Blob([lines.join("\n")], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob), link = node("a"); link.href = url; link.download = "UGNAY-network-report.txt"; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function updateBox() { byId("device-network-map").setAttribute("viewBox", `${box.x} ${box.y} ${box.width} ${box.height}`); }
  function zoom(factor) {
    const baseWidth = mobileMap.matches ? 420 : 1000;
    const width = Math.max(baseWidth * .35, Math.min(baseWidth * 2.4, box.width * factor)), height = width * 430 / baseWidth;
    box = { x: box.x + (box.width - width) / 2, y: box.y + (box.height - height) / 2, width, height }; updateBox();
  }
  function fit() { box = { x: 0, y: 0, width: mobileMap.matches ? 420 : 1000, height: 430 }; updateBox(); }
  mobileMap.addEventListener("change", () => { if (context) { mapPage = 0; fit(); if (data) renderMap(); } });
  function initialize() {
    initialized = true;
    document.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", () => selectView(button.dataset.view)));
    byId("board-toggle").addEventListener("click", () => { collapsed = byId("board-toggle").getAttribute("aria-expanded") === "true"; applyBoard(collapsed); });
    byId("view-reports").addEventListener("click", () => selectView("reports"));
    byId("account-menu-toggle").addEventListener("click", () => { const open = byId("account-menu").hidden; byId("account-menu").hidden = !open; byId("account-menu-toggle").setAttribute("aria-expanded", String(open)); });
    byId("close-profile").addEventListener("click", closeProfile);
    byId("device-profile").addEventListener("mouseenter", () => clearTimeout(closeTimer));
    byId("device-profile").addEventListener("mouseleave", scheduleClose);
    byId("device-search").addEventListener("input", () => { mapPage = 0; renderDevices(); renderMap(); });
    byId("device-edit-form").addEventListener("submit", async (event) => {
      event.preventDefault(); if (!currentDevice()) return;
      const identifier = selected; byId("save-device").disabled = true;
      try { await context.api(`/api/devices/${identifier}`, { label: byId("device-label").value.trim(), trust: byId("device-trust").value }); await context.refresh(); notify("profile-message", "Device details saved.", true); }
      catch (error) { notify("profile-message", error.message); }
      finally { byId("save-device").disabled = false; }
    });
    byId("profile-test").addEventListener("click", async () => { if (!currentDevice()) return; byId("profile-test").disabled = true; await runPing(selected, 4, "profile-message"); if (data) byId("profile-test").disabled = data.busy; });
    byId("test-form").addEventListener("submit", async (event) => { event.preventDefault(); if (!byId("test-device").value) return; byId("run-test").disabled = true; await runPing(Number(byId("test-device").value), Number(byId("test-count").value), "test-message"); if (data) byId("run-test").disabled = data.busy || !can("network.test"); });
    byId("test-device").addEventListener("change", renderTestResult);
    byId("download-report").addEventListener("click", downloadReport);
    byId("motion-enabled").addEventListener("change", () => { motionEnabled = byId("motion-enabled").checked; try { localStorage.setItem("ugnay-motion", motionEnabled ? "on" : "off"); } catch { /* Optional preference. */ } syncMotion(); });
    byId("map-zoom-in").addEventListener("click", () => zoom(.8)); byId("map-zoom-out").addEventListener("click", () => zoom(1.25)); byId("map-fit").addEventListener("click", fit);
    byId("map-prev").addEventListener("click", () => { mapPage = Math.max(0, mapPage - 1); closeProfile(); renderMap(); });
    byId("map-next").addEventListener("click", () => { mapPage += 1; closeProfile(); renderMap(); });
    const map = byId("device-network-map");
    map.addEventListener("pointerdown", (event) => {
      if (event.button !== 0 || event.target.closest(".map-node")) return;
      drag = { x: event.clientX, y: event.clientY, box: { ...box } }; map.setPointerCapture(event.pointerId); map.classList.add("panning");
    });
    map.addEventListener("pointermove", (event) => { if (!drag) return; const scale = Math.max(box.width / map.clientWidth, box.height / map.clientHeight); box.x = drag.box.x - (event.clientX - drag.x) * scale; box.y = drag.box.y - (event.clientY - drag.y) * scale; updateBox(); });
    function endDrag() { drag = null; map.classList.remove("panning"); }
    map.addEventListener("pointerup", endDrag); map.addEventListener("pointercancel", endDrag);
    map.addEventListener("wheel", (event) => { if (event.ctrlKey) { event.preventDefault(); zoom(event.deltaY < 0 ? .9 : 1.1); } }, { passive: false });
    document.addEventListener("keydown", (event) => { if (event.key === "Escape") { closeProfile(); byId("account-menu").hidden = true; byId("account-menu-toggle").setAttribute("aria-expanded", "false"); } });
    document.addEventListener("click", (event) => { if (!event.target.closest(".sidebar-account")) { byId("account-menu").hidden = true; byId("account-menu-toggle").setAttribute("aria-expanded", "false"); } });
  }

  function mount(options) {
    if (options.session.user.role !== "admin" || !options.session.user.permissions.includes("dashboard.view")) {
      throw new Error("Administrator access is required for this dashboard.");
    }
    context = options; if (!initialized) initialize();
    lastFingerprint = ""; selected = null; data = null; mapPage = 0; collapsed = false;
    byId("access-nav").hidden = !can("users.manage");
    byId("account-initials").textContent = initials(context.session.user.username);
    byId("account-menu-email").textContent = context.session.user.email || "Temporary guest account";
    byId("role-badge").textContent = { admin: "Administrator", user: "User", guest: "Guest" }[context.session.user.role];
    byId("device-search").value = "";
    byId("run-test").hidden = !can("network.test");
    fit(); selectView("dashboard"); syncMotion();
  }
  function reset() {
    data = null; context = null; lastFingerprint = "";
    closeProfile(); byId("account-menu").hidden = true;
    // Do not leave private dashboard data in the page after logout or a role change.
    ["map-graph", "device-rows", "activity-list", "history-activity", "scan-history-rows", "test-device", "test-result", "report-summary", "trust-summary", "security-devices", "user-rows", "profile-facts", "profile-name", "profile-ip", "profile-avatar", "profile-trust", "account-menu-email", "permissions-list", "account-email", "session-expiry", "welcome-name", "role-badge"].forEach((id) => byId(id).replaceChildren());
    ["workspace-message", "admin-message", "profile-message", "test-message"].forEach((id) => notify(id));
    ["local-ip", "network-subnet"].forEach((id) => { byId(id).textContent = "Not detected"; });
    byId("device-count").textContent = "0"; byId("last-scan").textContent = "Never";
    byId("last-scan").removeAttribute("title");
    byId("device-search").value = ""; byId("account-initials").textContent = "U";
    byId("average-latency").textContent = byId("packet-loss").textContent = "—";
    byId("device-edit-form").reset();
  }
  return { mount, render, reset, syncMotion };
})();
