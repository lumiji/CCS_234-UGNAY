"use strict";

const $ = (id) => document.getElementById(id);
const state = { mode: "login", session: null, polling: null, networkSequence: 0, resetUser: null, submitting: false };
const permissionNames = { "dashboard.view": "View the administrator dashboard", "network.view": "View discovered devices", "network.scan": "Run network discovery", "network.test": "Run ping tests", "devices.manage": "Recognize and label devices", "users.manage": "Manage accounts and access" };
const motionPreference = matchMedia("(prefers-reduced-motion: reduce)");
function syncMotion() {
  const map = document.querySelector(".network-map");
  if (motionPreference.matches) { map.setCurrentTime(0); map.pauseAnimations(); }
  else map.unpauseAnimations();
  window.UgnayDashboard?.syncMotion();
}
motionPreference.addEventListener("change", syncMotion);
syncMotion();

class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

async function api(path, data) {
  const options = { credentials: "same-origin", headers: { "Accept": "application/json" } };
  if (data !== undefined) {
    options.method = "POST";
    options.headers["Content-Type"] = "application/json";
    if (state.session) options.headers["X-CSRF-Token"] = state.session.csrf_token;
    options.body = JSON.stringify(data);
  }
  let response;
  try { response = await fetch(path, options); }
  catch { throw new ApiError("Could not reach UGNAY. Check that the local server is running.", 0); }
  const result = await response.json();
  if (!response.ok) {
    if (response.status === 401 && state.session) {
      showAuth("login", true);
      message("auth-message", "Your session has ended. Please log in again.");
    }
    throw new ApiError(result.error || "The request could not be completed.", response.status);
  }
  return result;
}

function message(id, value = "", success = false) {
  const element = $(id);
  element.textContent = value;
  element.hidden = !value;
  element.classList.toggle("success", success);
}

function modeFromHash() {
  return ["signup", "guest"].includes(location.hash.slice(1)) ? location.hash.slice(1) : "login";
}

function showAuth(mode = "login", focus = false) {
  state.session = null;
  state.networkSequence += 1;
  window.UgnayDashboard?.reset();
  clearTimeout(state.polling);
  state.mode = mode;
  state.submitting = false;
  document.body.classList.remove("authenticated", "member-view");
  $("workspace").hidden = true;
  $("member-workspace").hidden = true;
  $("member-device-rows").replaceChildren();
  $("member-device-count").textContent = "0";
  $("member-local-ip").textContent = $("member-subnet").textContent = "Not detected";
  $("member-last-scan").textContent = "No scan yet.";
  $("member-welcome").textContent = "Your network";
  $("member-role").textContent = $("member-session").textContent = "";
  message("member-message");
  $("reset-dialog").close();
  $("reset-form").reset();
  $("auth-view").hidden = false;
  $("auth-view").className = `auth-view ${mode}`;
  $("auth-form").reset();
  const signup = mode === "signup", guest = mode === "guest";
  $("auth-title").textContent = signup ? "NEW TO UGNAY?" : guest ? "HEY THERE!" : "WELCOME BACK!";
  $("auth-description").textContent = signup ? "Create an account." : guest ? "Want to connect as guest?" : "Log in to your account.";
  $("username-label").textContent = signup || guest ? "Username" : "Username/email";
  $("username").placeholder = signup ? "Enter your username" : guest ? "Choose a guest name (optional)" : "Enter your username or email";
  $("username").maxLength = signup ? 32 : guest ? 24 : 254;
  $("username").required = !guest;
  $("username").autocomplete = guest ? "off" : "username";
  $("email-field").hidden = $("confirm-field").hidden = !signup;
  $("email").disabled = $("confirm-password").disabled = !signup;
  $("email").required = $("confirm-password").required = signup;
  $("password").disabled = guest;
  $("password").required = !guest;
  $("password").minLength = signup ? 12 : 1;
  $("password").autocomplete = signup ? "new-password" : "current-password";
  $("password").placeholder = guest ? "No password needed for guests" : "Enter your password";
  $("remember").disabled = guest;
  document.querySelectorAll(".password-toggle").forEach((button) => {
    button.disabled = guest;
    button.setAttribute("aria-pressed", "false");
    button.setAttribute("aria-label", button.dataset.target === "confirm-password" ? "Show confirmation password" : "Show password");
    $(button.dataset.target).type = "password";
  });
  $("field-help").hidden = !signup && !guest;
  $("field-help").textContent = signup ? "Use at least 12 characters for your password." : "Temporary, read-only access. No password required.";
  $("password").setAttribute("aria-describedby", signup || guest ? "field-help" : "auth-description");
  $("auth-submit").textContent = signup ? "Sign up" : guest ? "Continue as Guest" : "Login";
  $("auth-submit").disabled = false;
  $("footer-caption").textContent = signup ? "Already have an account?" : guest ? "Have an account?" : "Don’t have an account?";
  $("footer-link").textContent = signup || guest ? "Login" : "Sign up";
  $("footer-link").href = signup || guest ? "#login" : "#signup";
  $("guest-link").hidden = signup || guest;
  document.title = `${signup ? "Sign up" : guest ? "Guest access" : "Login"} · UGNAY`;
  message("auth-message");
  if (focus) $("username").focus({ preventScroll: true });
}

async function showWorkspace(session) {
  state.session = session;
  clearTimeout(state.polling);
  $("auth-view").hidden = true;
  const user = session.user, guest = user.role === "guest", admin = user.role === "admin";
  $("workspace").hidden = !admin;
  $("member-workspace").hidden = admin;
  document.body.classList.add("authenticated");
  document.body.classList.toggle("member-view", !admin);
  document.title = "Your network · UGNAY";
   if (!admin) {
    UgnayDashboard.reset();

    const pending = user.status === "pending";
    const networkPanel = $("member-network-title").closest("section");

    networkPanel.hidden = pending;
    $("member-session").hidden = pending;
    $("member-signup").hidden = !guest;
    $("member-scan").hidden = !user.permissions.includes("network.scan");
    $("member-test-heading").hidden = !user.permissions.includes("network.test");
    message("member-message");

    if (pending) {
      document.title = "Pending approval · UGNAY";
      $("member-welcome").textContent = "Awaiting approval";
      $("member-role").textContent = "Pending";
      $("member-description").textContent =
        "Your account is awaiting administrator approval. Once approved, log in again.";
      return;
    }

    $("member-welcome").textContent = guest
      ? "Welcome, guest."
      : `Hello, ${user.username}.`;
    $("member-role").textContent = guest ? "Guest" : "User";
    $("member-description").textContent = guest
      ? "View the latest network results."
      : "Discover and test connections on your local network.";

    const expiresAt = new Date(session.expires_at * 1000);
    $("member-session").textContent = `Session expires ${expiresAt.toLocaleString(
      [],
      { dateStyle: "medium", timeStyle: "short" }
    )}`;

    await loadNetwork();
    return;
  }

  $("welcome-name").textContent = user.username;
  $("role-badge").textContent = user.role;
  $("account-email").textContent = user.email;
  $("session-expiry").textContent = new Date(
    session.expires_at * 1000
  ).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });

  $("permissions-list").replaceChildren(
    ...user.permissions.map((permission) => {
      const li = document.createElement("li");
      li.textContent = permissionNames[permission] || permission;
      return li;
    })
  );

  const canScan = user.permissions.includes("network.scan");
  const canManageUsers = user.permissions.includes("users.manage");

  $("scan").hidden = !canScan;
  $("access-description").textContent = canScan
    ? "Discover responding devices on this computer’s local network."
    : "You have read-only access to the latest discovery results.";
  $("guest-note").hidden = true;
  $("guest-signup").hidden = true;
  $("admin-panel").hidden = !canManageUsers;

  message("workspace-message");
  message("admin-message");

  UgnayDashboard.mount({
    session,
    api,
    loadUsers,
    refresh: async () => {
      clearTimeout(state.polling);
      await loadNetwork();
    },
  });

  await Promise.all([
    loadNetwork(),
    canManageUsers ? loadUsers() : Promise.resolve(),
  ]);
}

async function loadNetwork() {
  const session = state.session;
  if (!session) return;
  clearTimeout(state.polling);
  const request = ++state.networkSequence;
  try {
    const admin = session.user.role === "admin";
    const network = await api(admin ? "/api/admin/dashboard" : "/api/network");
    if (state.session !== session || request !== state.networkSequence) return;
    if (admin) UgnayDashboard.render(network); else renderMemberNetwork(network);
  } catch (error) { if (state.session === session) message(session.user.role === "admin" ? "workspace-message" : "member-message", error.message); }
  finally { if (state.session === session && request === state.networkSequence) state.polling = setTimeout(loadNetwork, 2500); }
}

function renderMemberNetwork(network) {
  const canTest = state.session.user.permissions.includes("network.test");
  $("member-local-ip").textContent = network.network?.local_ip || "Not detected";
  $("member-subnet").textContent = network.network?.subnet || "Not detected";
  $("member-device-count").textContent = String(network.devices.length);
  $("member-scan").disabled = network.busy;
  $("member-scan").textContent = network.busy && network.operation === "scan" ? "Scanning…" : "Scan network";
  $("member-last-scan").textContent = network.scanned_at ? `Last scan: ${new Date(network.scanned_at).toLocaleString()}` : "No discovery scan has been completed.";
  message("member-message", network.error || (network.busy ? network.operation === "ping" ? "Ping test in progress…" : "Scanning the local network…" : ""), network.busy);
  $("member-empty").hidden = network.devices.length > 0;
  $("member-empty").textContent = network.scanned_at ? "No devices responded to the latest scan." : "Results will appear here after a scan.";
  $("member-device-rows").replaceChildren(...network.devices.map((device) => {
    const row = document.createElement("tr");
    const values = [device.hostname || "Hostname unavailable", device.ip_address, device.status,
      device.ping?.average_latency_ms == null ? "—" : `${device.ping.average_latency_ms.toFixed(1)} ms`,
      device.ping?.packet_loss_percent == null ? "—" : `${Number(device.ping.packet_loss_percent.toFixed(1))}%`];
    values.forEach((value) => { const cell = document.createElement("td"); cell.textContent = value; row.append(cell); });
    if (canTest) {
      const cell = document.createElement("td"), button = document.createElement("button");
      button.type = "button"; button.className = "secondary-button"; button.textContent = "Test connection"; button.disabled = network.busy;
      button.addEventListener("click", async () => {
        button.disabled = true;
        try { await api(`/api/devices/${device.id}/ping`, { count: 4 }); await loadNetwork(); }
        catch (error) { message("member-message", error.message); button.disabled = false; }
      });
      cell.append(button); row.append(cell);
    }
    return row;
  }));
}

async function updateUser(id, changes) {
  message("admin-message");
  try { await api(`/api/admin/users/${id}`, changes); await loadUsers(); message("admin-message", "Account updated. Existing sessions for that account have ended.", true); }
  catch (error) { message("admin-message", error.message); await loadUsers(); }
}

async function loadUsers() {
  const session = state.session;
  if (!session?.user.permissions.includes("users.manage")) return;

  const statusLabels = {
    pending: "Pending",
    approved: "Approved",
    disabled: "Disabled",
    guest: "Temporary guest",
  };

  try {
    const { users } = await api("/api/admin/users");
    if (state.session !== session) return;

    const pending = users.filter((user) => user.status === "pending");
    const others = users.filter((user) => user.status !== "pending");
    const rows = [];

    for (const user of [...pending, ...others]) {
      const row = document.createElement("tr");
      const isSelf = user.id === session.user.id;
      const isGuest = user.role === "guest";

      const nameCell = document.createElement("td");
      nameCell.textContent = user.username;
      const email = document.createElement("small");
      email.textContent = user.email || "Temporary guest";
      nameCell.append(email);

      const roleCell = document.createElement("td");
      const select = document.createElement("select");
      select.setAttribute("aria-label", `Role for ${user.username}`);

      const roles = isGuest ? ["guest"] : ["user", "admin"];
      for (const value of roles) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = value[0].toUpperCase() + value.slice(1);
        select.append(option);
      }

      select.value = user.role;
      select.disabled = isSelf || isGuest || user.status !== "approved";
      select.addEventListener("change", async () => {
        select.disabled = true;
        await updateUser(user.id, { role: select.value });
      });
      roleCell.append(select);

      const statusCell = document.createElement("td");
      statusCell.textContent = statusLabels[user.status] ?? "Unknown";

      const actionsCell = document.createElement("td");
      const actions = document.createElement("div");
      actions.className = "table-actions";

      if (user.status === "pending" && user.role === "user") {
        const approve = document.createElement("button");
        approve.type = "button";
        approve.className = "primary-button";
        approve.textContent = "Approve";
        approve.setAttribute("aria-label", `Approve ${user.username}`);
        approve.addEventListener("click", async () => {
          approve.disabled = true;
          try {
            await updateUser(user.id, { approved: true });
          } finally {
            approve.disabled = false;
          }
        });
        actions.append(approve);
      }

      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "secondary-button";
      toggle.textContent = user.active ? "Disable" : "Enable";
      toggle.disabled = isSelf;
      toggle.setAttribute("aria-label", `${toggle.textContent} ${user.username}`);
      toggle.addEventListener("click", async () => {
        toggle.disabled = true;
        await updateUser(user.id, { active: !user.active });
      });
      actions.append(toggle);

      if (!isGuest) {
        const reset = document.createElement("button");
        reset.type = "button";
        reset.className = "secondary-button";
        reset.textContent = "Reset password";
        reset.addEventListener("click", () => {
          state.resetUser = user.id;
          $("reset-title").textContent = `Reset password for ${user.username}`;
          $("reset-form").reset();
          message("reset-message");
          $("reset-dialog").showModal();
        });
        actions.append(reset);
      }

      actionsCell.append(actions);
      row.append(nameCell, roleCell, statusCell, actionsCell);
      rows.push(row);
    }

    $("user-rows").replaceChildren(...rows);
  } catch (error) {
    if (state.session === session) {
      message("admin-message", error.message);
    }
  }
}

async function init() {
  showAuth(modeFromHash());
  try { await showWorkspace(await api("/api/session")); }
  catch (error) { if (error.status !== 401) message("auth-message", error.message); }
}
init();
