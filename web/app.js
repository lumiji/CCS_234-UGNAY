"use strict";

const $ = (id) => document.getElementById(id);
const state = { mode: "login", session: null, polling: null, resetUser: null, submitting: false };
const permissionNames = { "network.view": "View discovered devices", "network.scan": "Run network discovery", "users.manage": "Manage accounts and access" };
const motionPreference = matchMedia("(prefers-reduced-motion: reduce)");
function syncMotion() {
  const map = document.querySelector(".network-map");
  if (motionPreference.matches) { map.setCurrentTime(0); map.pauseAnimations(); }
  else map.unpauseAnimations();
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
  clearTimeout(state.polling);
  state.mode = mode;
  state.submitting = false;
  document.body.classList.remove("authenticated");
  $("workspace").hidden = true;
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
  $("workspace").hidden = false;
  document.body.classList.add("authenticated");
  document.title = "Your network · UGNAY";
  const user = session.user, guest = user.role === "guest";
  $("welcome-name").textContent = guest ? "Welcome, guest." : `Hello, ${user.username}.`;
  $("role-badge").textContent = user.role;
  $("account-email").textContent = user.email || "Temporary guest account";
  $("session-expiry").textContent = new Date(session.expires_at * 1000).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
  $("permissions-list").replaceChildren(...user.permissions.map((permission) => {
    const li = document.createElement("li"); li.textContent = permissionNames[permission] || permission; return li;
  }));
  const canScan = user.permissions.includes("network.scan");
  $("scan").hidden = !canScan;
  $("access-description").textContent = canScan ? "Discover responding devices on this computer’s local network." : "You have read-only access to the latest discovery results. Sign up to run a scan.";
  $("guest-note").hidden = $("guest-signup").hidden = !guest;
  $("admin-panel").hidden = !user.permissions.includes("users.manage");
  message("workspace-message"); message("admin-message");
  await Promise.all([loadNetwork(), user.permissions.includes("users.manage") ? loadUsers() : Promise.resolve()]);
}

async function loadNetwork() {
  const session = state.session;
  if (!session) return;
  try {
    const network = await api("/api/network");
    if (state.session !== session) return;
    $("device-count").textContent = network.scanned_at ? String(network.devices.length) : "—";
    $("network-subnet").textContent = network.network?.subnet || "Not scanned";
    $("scan-time").textContent = network.busy ? "Discovery is running. You can leave this page open." : network.scanned_at ? `Last scan: ${new Date(network.scanned_at).toLocaleString()} · Local IP: ${network.network.local_ip}` : "No discovery scan has been run in this server session.";
    $("scan").disabled = network.busy;
    $("scan").textContent = network.busy ? "Scanning…" : "Scan network";
    message("workspace-message", network.error || "");
    $("network-empty").hidden = network.devices.length > 0;
    $("device-table-wrap").hidden = !network.devices.length;
    $("network-empty").querySelector("h3").textContent = network.busy ? "Looking for connections…" : network.scanned_at ? "No devices responded." : "Your network starts here.";
    $("network-empty").querySelector("p").textContent = network.scanned_at ? "Devices that block ICMP or are asleep may not appear." : session.user.role === "guest" ? "An administrator or user can run discovery. Results will appear here." : "Run discovery to see devices that respond on your local network.";
    $("device-rows").replaceChildren(...network.devices.map((device) => {
      const tr = document.createElement("tr");
      [device.ip_address, device.hostname || "Hostname unavailable", device.status].forEach((text) => { const td = document.createElement("td"); td.textContent = text; tr.append(td); });
      return tr;
    }));
  } catch (error) { if (state.session === session) message("workspace-message", error.message); }
  finally { if (state.session === session) state.polling = setTimeout(loadNetwork, 2500); }
}

async function updateUser(id, changes) {
  message("admin-message");
  try { await api(`/api/admin/users/${id}`, changes); await loadUsers(); message("admin-message", "Account updated. Existing sessions for that account have ended.", true); }
  catch (error) { message("admin-message", error.message); await loadUsers(); }
}

async function loadUsers() {
  const session = state.session;
  if (!session?.user.permissions.includes("users.manage")) return;
  try {
    const { users } = await api("/api/admin/users");
    if (state.session !== session) return;
    $("user-rows").replaceChildren(...users.map((user) => {
      const tr = document.createElement("tr"), name = document.createElement("td"), email = document.createElement("small");
      name.textContent = user.username; email.textContent = user.email || "Temporary guest"; name.append(email);
      const role = document.createElement("td"), select = document.createElement("select");
      select.setAttribute("aria-label", `Role for ${user.username}`);
      (user.role === "guest" ? ["guest"] : ["user", "admin"]).forEach((value) => { const option = document.createElement("option"); option.value = value; option.textContent = value[0].toUpperCase() + value.slice(1); select.append(option); });
      select.value = user.role; select.disabled = user.id === session.user.id || user.role === "guest";
      select.addEventListener("change", async () => { select.disabled = true; await updateUser(user.id, { role: select.value }); });
      role.append(select);
      const status = document.createElement("td"); status.textContent = user.active ? "Active" : "Disabled";
      const actions = document.createElement("td"), wrapper = document.createElement("div"); wrapper.className = "table-actions";
      const toggle = document.createElement("button"); toggle.type = "button"; toggle.className = "secondary-button"; toggle.textContent = user.active ? "Disable" : "Enable"; toggle.disabled = user.id === session.user.id;
      toggle.setAttribute("aria-label", `${toggle.textContent} ${user.username}`);
      toggle.addEventListener("click", async () => { toggle.disabled = true; await updateUser(user.id, { active: !user.active }); });
      wrapper.append(toggle);
      if (user.role !== "guest") {
        const reset = document.createElement("button"); reset.type = "button"; reset.className = "secondary-button"; reset.textContent = "Reset password";
        reset.addEventListener("click", () => { state.resetUser = user.id; $("reset-title").textContent = `Reset password for ${user.username}`; $("reset-form").reset(); message("reset-message"); $("reset-dialog").showModal(); });
        wrapper.append(reset);
      }
      actions.append(wrapper); tr.append(name, role, status, actions); return tr;
    }));
  } catch (error) { message("admin-message", error.message); }
}

$("auth-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.submitting) return;
  message("auth-message");
  const mode = state.mode, signup = mode === "signup", guest = mode === "guest";
  const password = $("password").value;
  if (signup && password !== $("confirm-password").value) { message("auth-message", "Your passwords do not match."); $("confirm-password").focus(); return; }
  state.submitting = true;
  $("auth-submit").disabled = true;
  $("auth-form").setAttribute("aria-busy", "true");
  $("auth-submit").textContent = signup ? "Creating account…" : guest ? "Connecting…" : "Logging in…";
  try {
    const data = { username: $("username").value.trim(), identifier: $("username").value.trim(), password, email: $("email").value.trim(), confirm_password: $("confirm-password").value, remember: $("remember").checked };
    const session = await api(`/api/${signup ? "signup" : guest ? "guest" : "login"}`, data);
    $("auth-form").reset();
    await showWorkspace(session);
  } catch (error) { message("auth-message", error.message); }
  finally {
    state.submitting = false;
    $("auth-submit").disabled = false;
    $("auth-form").removeAttribute("aria-busy");
    $("auth-submit").textContent = signup ? "Sign up" : guest ? "Continue as Guest" : "Login";
  }
});

document.querySelectorAll(".password-toggle").forEach((button) => button.addEventListener("click", () => {
  const input = $(button.dataset.target), visible = input.type === "password";
  input.type = visible ? "text" : "password";
  button.setAttribute("aria-pressed", String(visible));
  button.setAttribute("aria-label", `${visible ? "Hide" : "Show"} ${button.dataset.target === "confirm-password" ? "confirmation password" : "password"}`);
}));
$("forgot-password").addEventListener("click", () => $("recovery-dialog").showModal());
$("close-recovery").addEventListener("click", () => $("recovery-dialog").close());
$("recovery-done").addEventListener("click", () => $("recovery-dialog").close());
$("close-reset").addEventListener("click", () => $("reset-dialog").close());
$("logout").addEventListener("click", async () => {
  $("logout").disabled = true;
  try { await api("/api/logout", {}); history.replaceState(null, "", "#login"); showAuth("login", true); }
  catch (error) { message("workspace-message", error.message); }
  finally { $("logout").disabled = false; }
});
$("scan").addEventListener("click", async () => {
  $("scan").disabled = true;
  try { await api("/api/network/scan", {}); clearTimeout(state.polling); await loadNetwork(); }
  catch (error) { message("workspace-message", error.message); $("scan").disabled = false; }
});
$("refresh-users").addEventListener("click", loadUsers);
$("reset-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if ($("reset-password").value !== $("reset-confirm").value) { message("reset-message", "Your passwords do not match."); return; }
  const button = $("reset-form").querySelector("button[type=submit]"); button.disabled = true;
  try {
    const ownAccount = state.resetUser === state.session.user.id;
    await api(`/api/admin/users/${state.resetUser}`, { password: $("reset-password").value });
    $("reset-dialog").close(); $("reset-form").reset();
    if (ownAccount) { showAuth("login", true); message("auth-message", "Password updated. Please log in with your new password.", true); }
    else message("admin-message", "Password updated. Existing sessions for that account have ended.", true);
  } catch (error) { message("reset-message", error.message); }
  finally { button.disabled = false; }
});
window.addEventListener("hashchange", async () => {
  // Signing up from a guest session explicitly ends the temporary session.
  if (state.session) {
    try { await api("/api/logout", {}); }
    catch (error) { if (error.status !== 401) { message("workspace-message", error.message); return; } }
  }
  showAuth(modeFromHash(), true);
});

async function init() {
  showAuth(modeFromHash());
  try { await showWorkspace(await api("/api/session")); }
  catch (error) { if (error.status !== 401) message("auth-message", error.message); }
}
init();
