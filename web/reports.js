"use strict";

// Historical scan reports. No network probes run when a report is opened.
window.UgnayReports = (() => {
  const byId = (id) => document.getElementById(id), NS = "http://www.w3.org/2000/svg";
  const trustNames = { trusted: "Trusted", review: "Review", flagged: "Flagged" };
  let context, state, detail, drafts = [], active = false, initialized = false;
  let request = 0, fingerprint = "", loading = false;
  const date = (value) => value ? new Date(value).toLocaleString([], { dateStyle: "short", timeStyle: "short" }) : "Never";
  const latency = (value) => value == null ? "—" : `${value.toFixed(1)} ms`;
  const loss = (value) => value == null ? "—" : `${Number(value.toFixed(1))}%`;
  const device = () => detail?.devices.find((item) => String(item.id) === byId("report-device").value);
  function node(tag, text, className) {
    const item = document.createElement(tag);
    if (text !== undefined) item.textContent = text;
    if (className) item.className = className;
    return item;
  }
  function svg(tag, attributes, text) {
    const item = document.createElementNS(NS, tag);
    Object.entries(attributes).forEach(([key, value]) => item.setAttribute(key, value));
    if (text !== undefined) item.textContent = text;
    return item;
  }
  function message(text = "", success = false) {
    byId("report-message").textContent = text; byId("report-message").hidden = !text;
    byId("report-message").classList.toggle("success", success);
  }
  function render(next, addedTests) {
    state = next; drafts = addedTests;
    const select = byId("report-scan"), previous = select.value;
    select.replaceChildren(...state.scan_history.map((scan) => {
      const at = new Date(scan.scanned_at);
      const option = node("option", `${at.toLocaleDateString([], { year: "numeric", month: "2-digit", day: "2-digit" })} | ${at.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })} · #${scan.id}`);
      option.value = scan.id; option.title = scan.subnet; return option;
    }));
    if (!state.scan_history.length) { const option = node("option", "No saved scans"); option.value = ""; select.append(option); }
    if (state.scan_history.some((scan) => String(scan.id) === previous)) select.value = previous;
    select.disabled = !state.scan_history.length;
    if (String(detail?.id) !== select.value) detail = null;
    renderDrafts(); renderView();
    if (active) load();
  }
  async function load(force = false) {
    const scan = byId("report-scan").value;
    if (!active || !context || !scan || !state) return;
    const signature = JSON.stringify([scan, state.test_history, state.devices]);
    if (!force && fingerprint === signature) return;
    fingerprint = signature;
    const session = context.session, ticket = ++request;
    loading = true; message(); renderView();
    try {
      const result = await context.api(`/api/admin/reports/${scan}`);
      if (context?.session !== session || ticket !== request || !active || byId("report-scan").value !== scan) return;
      detail = result.report; loading = false; renderView();
    } catch (error) {
      if (context?.session !== session || ticket !== request || !active) return;
      detail = null; loading = false; fingerprint = ""; renderView(); message(`Could not load this report: ${error.message}`);
    }
  }
  // Member 3: network-wide calculations use one latest saved ping test per device.
  // This matches reporting.py's equal-weight-per-device approach and thresholds.
  function summarizeScan(scan) {
    const devices = scan?.devices || [];
    const measured = devices.map((item) => ({ item, ping: item.ping_history?.[0] }))
      .filter(({ ping }) => Boolean(ping));
    const samples = measured.map(({ ping }) => ping.average_latency_ms)
      .filter((value) => typeof value === "number" && Number.isFinite(value));
    const losses = measured.map(({ ping }) => ping.packet_loss_percent)
      .filter((value) => typeof value === "number" && Number.isFinite(value));
    const averageLatency = samples.length ? samples.reduce((sum, value) => sum + value, 0) / samples.length : null;
    const averageLoss = losses.length ? losses.reduce((sum, value) => sum + value, 0) / losses.length : null;
    const urgent = measured.some(({ ping }) => ping.status === "Unreachable" ||
      ping.packet_loss_percent >= 10 || ping.average_latency_ms >= 100);
    const fair = measured.some(({ ping }) => ping.status === "Packet loss" ||
      ping.packet_loss_percent > 0 || ping.average_latency_ms >= 50);
    const health = !devices.length ? "No devices detected" : !measured.length ? "Not tested" :
      urgent ? "Needs attention" : fair ? "Fair" :
      measured.length !== devices.length ? "Partially tested" : "Healthy";
    return { devices, measured, averageLatency, averageLoss, health };
  }
  function adviceForScan(summary) {
    const { devices, measured } = summary, items = [];
    if (!devices.length) {
      items.push({ severity: "info", message: "No devices were found in this scan. Check the network connection and run discovery again." });
    } else if (!measured.length) {
      items.push({ severity: "info", message: "No ping tests are available for this scan. Test selected devices to measure latency and packet loss." });
    } else {
      const noResponse = measured.filter(({ ping }) => ping.status === "Unreachable");
      const highLoss = measured.filter(({ ping }) => ping.status !== "Unreachable" && ping.packet_loss_percent >= 10);
      const anyLoss = measured.filter(({ ping }) => ping.status !== "Unreachable" && ping.packet_loss_percent > 0 && ping.packet_loss_percent < 10);
      const highLatency = measured.filter(({ ping }) => ping.average_latency_ms != null && ping.average_latency_ms >= 100);
      const fairLatency = measured.filter(({ ping }) => ping.average_latency_ms != null && ping.average_latency_ms >= 50 && ping.average_latency_ms < 100);
      const untested = devices.length - measured.length;
      const names = (list) => list.map(({ item }) => `${item.name || item.hostname || item.ip_address} (${item.ip_address})`).join(", ");
      if (noResponse.length) items.push({ severity: "error", message: `No ping response from: ${names(noResponse)}. Check connectivity and ICMP/firewall settings; a missing reply does not prove the device is offline.` });
      if (highLoss.length) items.push({ severity: "warning", message: `High packet loss (10% or more): ${names(highLoss)}. Check Wi-Fi signal, congestion, and network equipment.` });
      if (anyLoss.length) items.push({ severity: "warning", message: `Some packet loss detected: ${names(anyLoss)}. Repeat ping tests to check whether the problem persists.` });
      if (highLatency.length) items.push({ severity: "warning", message: `High average latency (100 ms or more): ${names(highLatency)}. Investigate response delays.` });
      if (fairLatency.length) items.push({ severity: "info", message: `Elevated average latency (50–99.9 ms): ${names(fairLatency)}. Monitor these devices over additional tests.` });
      if (untested) items.push({ severity: "info", message: `${untested} of ${devices.length} discovered devices have no saved ping test for this scan.` });
      if (!items.length) items.push({ severity: "success", message: "All detected devices have saved tests with no observed packet loss or elevated average latency." });
    }
    items.push({ severity: "info", message: "General security reminder: use strong Wi-Fi passwords, keep router firmware updated, and enable appropriate firewall protection. Ping tests do not verify these settings." });
    return items;
  }
  function renderNetworkAssessment() {
    const summary = summarizeScan(detail);
    const status = byId("report-network-health");
    status.textContent = detail ? summary.health : "No report selected";
    status.className = `report-health-status ${detail ? summary.health.toLowerCase().replaceAll(" ", "-") : ""}`;
    byId("report-network-tested").textContent = detail ? `${summary.measured.length} / ${summary.devices.length}` : "—";
    byId("report-network-latency").textContent = detail ? latency(summary.averageLatency) : "—";
    byId("report-network-loss").textContent = detail ? loss(summary.averageLoss) : "—";
    const note = !detail ? "Choose a saved scan to review its network health." :
      `Assessment uses the latest saved ping test for each device in this scan. Average latency and loss are equal-weighted device means; missing latency values are excluded.`;
    byId("report-network-summary").textContent = note;
    const tips = detail ? adviceForScan(summary) : [{ severity: "info", message: "Choose a saved scan to view recommendations." }]; 
    byId("report-recommendation-items").replaceChildren(
      ...tips.map((tip) => {
        const isSecurity = tip.message.startsWith("General security reminder:");

        const title = isSecurity
          ? "General Security Reminder"
          : tip.severity === "success"
            ? "No Connectivity Alerts"
            : tip.severity === "error"
              ? "No Ping Response"
              : tip.severity === "warning"
                ? "Connectivity Warning"
                : "Connectivity Information";

        const description = isSecurity
          ? tip.message
              .replace(/^General security reminder:\s*/, "")
              .replace(/\s*Ping tests do not verify these settings\.$/, "")
          : tip.severity === "success"
            ? "No elevated average latency or packet loss was detected in the latest tests."
            : tip.message;

        const item = node(
          "li",
          undefined,
          `report-advice ${tip.severity}${isSecurity ? " security" : ""}`
        );

        item.append(
          node("strong", title, "report-advice-title"),
          node("span", description, "report-advice-message")
        );

        return item;
      })
    );

  }
  function renderView() {
    const select = byId("report-device"), previous = select.value;
    select.replaceChildren(...(detail?.devices || []).map((item) => {
      const option = node("option", `${item.name} / ${item.ip_address}`); option.value = item.id; return option;
    }));
    if (!detail?.devices.length) { const option = node("option", loading ? "Loading devices…" : "No detected devices"); option.value = ""; select.append(option); }
    if (detail?.devices.some((item) => String(item.id) === previous)) select.value = previous;
    select.disabled = loading || !detail?.devices.length;
    byId("reports-panel").setAttribute("aria-busy", String(loading));
    byId("export-report-pdf").disabled = loading || !detail;   
    const selected = device(), tests = selected?.ping_history || [], latest = tests[0];
    const selectedScan = state?.scan_history.find((scan) => String(scan.id) === byId("report-scan").value);
    const at = detail?.scanned_at || selectedScan?.scanned_at;
    byId("report-date-context").textContent = at ? `Date: ${new Date(at).toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" })}     |     Selected Scan: ${new Date(at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}` : "Scan your network to create a report.";
    byId("report-print-context").textContent = detail ? `${selected ? `${selected.name} / ${selected.ip_address}` : "No detected devices"} · ${date(detail.scanned_at)} · ${detail.network.subnet}` : "";
    byId("report-sent").textContent = tests.length ? String(tests.reduce((total, test) => total + test.replies.length, 0)) : "—";
    byId("report-tested").textContent = selected ? String(tests.length) : "—";
    byId("report-latest").textContent = latest ? `${latency(latest.average_latency_ms)} / ${loss(latest.packet_loss_percent)} loss` : "No test yet";
    const plotted = tests.slice(0, 3);
    context?.drawReplyChart({ chart: "report-line-chart", plot: "report-line-plot", title: "report-line-title", description: "report-line-description", rows: "report-reply-data", legend: "report-line-legend" }, selected, plotted, 28, 652);
    drawBars(plotted);
    byId("report-line-empty").hidden = byId("report-bar-empty").hidden = !!plotted.length;
    const empty = loading ? "Loading saved results…" : !detail ? "Select a saved scan to view its results." : !selected ? "No devices responded in this scan." : "No ping tests recorded for this device in the selected scan.";
    byId("report-line-empty").textContent = byId("report-bar-empty").textContent = byId("report-packets-empty").textContent = empty;
    byId("report-packets-empty").hidden = !!tests.length;
    renderNetworkAssessment();
    const identity = byId("report-device-identity"); identity.replaceChildren();
    byId("report-device-empty").hidden = !!selected;
    if (selected) identity.append(node("strong", selected.name), node("span", trustNames[selected.trust], `trust-badge ${selected.trust}`));
    const facts = selected ? [["Hostname", selected.hostname || "Not detected"], ["IP address", selected.ip_address], ["Connected subnet", selected.subnet], ["First discovered", date(selected.first_seen)], ["Last scan response", date(selected.last_seen)]] : [];
    byId("report-device-facts").replaceChildren(...facts.map(([label, value]) => { const row = node("div"); row.append(node("dt", label), node("dd", value)); return row; }));
    byId("report-packet-rows").replaceChildren(...tests.flatMap((test) => test.replies.map((reply) => {
      const row = node("tr"), success = reply.latency_ms != null;
      [reply.sequence, success ? 1 : 0, success ? 0 : 1, "—", date(test.tested_at)].forEach((value) => row.append(node("td", value)));
      row.title = `Request ${reply.sequence}: ${success ? latency(reply.latency_ms) : "No response"}`;
      return row;
    })));
  }
  function drawBars(tests) {
    const plot = byId("report-bar-plot"); plot.replaceChildren();
    byId("report-bar-chart").toggleAttribute("hidden", !tests.length);
    if (!tests.length) return;
    const maximum = Math.max(1, ...tests.map((test) => test.replies.length)), step = Math.max(1, Math.ceil(maximum / 4));
    const ceiling = Math.ceil(maximum / step) * step, y = (value) => 264 - value / ceiling * 248;
    for (let value = 0; value <= ceiling; value += step) {
      plot.append(svg("line", { x1: 26, x2: 414, y1: y(value), y2: y(value), class: "latency-grid" }), svg("text", { x: 18, y: y(value) + 4, "text-anchor": "end", class: "latency-axis" }, value));
    }
    const descriptions = [];
    tests.forEach((test, index) => {
      const received = test.replies.filter((reply) => reply.latency_ms != null).length, failed = test.replies.length - received;
      const width = 388 / tests.length, center = 26 + width * (index + .5), barWidth = Math.min(53, width * .38);
      [[received, -barWidth, "#5147ed", "Replies"], [failed, 1, "#e914bf", "No response"]].forEach(([value, offset, fill, label]) => {
        const bar = svg("rect", { x: center + offset, y: y(value), width: barWidth - 1, height: 264 - y(value), fill, "data-reply-count": value });
        bar.append(svg("title", {}, `${date(test.tested_at)} · ${label}: ${value}`)); plot.append(bar);
      });
      plot.append(svg("text", { x: center, y: 292, "text-anchor": "middle", class: "latency-axis" }, index ? `Previous ${index}` : "Latest"));
      descriptions.push(`${date(test.tested_at)}: ${received} replies, ${failed} without a response`);
    });
    byId("report-bar-description").textContent = descriptions.join("; ");
  }
  function renderDrafts() {
    byId("report-added-tests").hidden = !drafts.length;
    byId("report-test-rows").replaceChildren(...drafts.map((entry) => {
      const row = node("tr"), ping = entry.ping;
      [entry.name, date(ping.tested_at), ping.replies.length, ping.replies.filter((reply) => reply.latency_ms != null).length, loss(ping.packet_loss_percent), latency(ping.average_latency_ms), latency(ping.maximum_latency_ms)].forEach((value) => row.append(node("td", value)));
      return row;
    }));
  }
  function downloadText() {
    if (!detail || loading) return;
    const selected = device(), tests = selected?.ping_history || [];
    const lines = ["UGNAY — Network health report", `Selected scan: ${date(detail.scanned_at)}`, `Subnet: ${detail.network.subnet}`, `Local IP: ${detail.network.local_ip}`, `Device: ${selected ? `${selected.name} | ${selected.ip_address} | ${trustNames[selected.trust]}` : "No detected devices"}`];
    const add = (name, ping) => lines.push("", `${name} | ${date(ping.tested_at)}`, `Sent: ${ping.replies.length} | Received: ${ping.replies.filter((reply) => reply.latency_ms != null).length} | Loss: ${loss(ping.packet_loss_percent)} | Average: ${latency(ping.average_latency_ms)} | Maximum: ${latency(ping.maximum_latency_ms)}`, ...ping.replies.map((reply) => `Request ${reply.sequence}: ${reply.latency_ms == null ? "Timed out" : latency(reply.latency_ms)}`));
    tests.forEach((test) => add(selected.name, test));
    if (drafts.length) { lines.push("", "Added ping tests"); drafts.forEach((entry) => add(`${entry.name} | ${entry.ip_address}`, entry.ping)); }
    lines.push("", "Tests belong to the interval from the selected scan until the next scan. Device details use current saved values. History retains up to 1,000 tests. Failure means no reply; packet error codes are not recorded.");
    const url = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/plain;charset=utf-8" })), link = node("a");
    link.href = url; link.download = "UGNAY-network-report.txt"; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function mount(options) {
    context = options; detail = state = null; drafts = []; fingerprint = ""; loading = active = false; request += 1;
    if (initialized) return;
    initialized = true;
    byId("report-scan").addEventListener("change", () => { detail = null; fingerprint = ""; message(); load(true); });
    byId("report-device").addEventListener("change", () => { message(); renderView(); });
    byId("export-report-pdf").addEventListener("click", () => {
      if (!active || !detail || loading) return;
      const title = document.title;
      document.title = `UGNAY Report - ${device()?.name || "Network"} - ${new Date(detail.scanned_at).toLocaleDateString()}`;
      try { window.print(); } finally { document.title = title; }
      message("Choose Save as PDF in the print dialog to export this report.", true);
    });
  }
  function setActive(value) {
    active = value;
    if (active) { if (state) { renderView(); load(true); } }
    else { request += 1; fingerprint = ""; loading = false; }
  }
  function reset() {
    request += 1; context = state = detail = null; drafts = []; active = loading = false; fingerprint = "";
    ["report-device", "report-scan", "report-device-identity", "report-device-facts", "report-packet-rows", "report-test-rows", "report-line-plot", "report-line-legend", "report-reply-data", "report-bar-plot", "report-line-title", "report-line-description", "report-bar-description", "report-date-context", "report-print-context"].forEach((id) => byId(id).replaceChildren());
    ["report-sent", "report-tested", "report-latest"].forEach((id) => { byId(id).textContent = "—"; });
    renderNetworkAssessment();
    ["export-report-pdf", "report-device", "report-scan"].forEach((id) => { byId(id).disabled = true; });
    ["report-line-chart", "report-bar-chart"].forEach((id) => byId(id).setAttribute("hidden", ""));
    byId("report-added-tests").hidden = true; message();
  }
  return { mount, render, setActive, reset };
})();
