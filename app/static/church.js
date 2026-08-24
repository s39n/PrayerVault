"use strict";
// PrayerVault multi-church frontend. Dependency-free, no inline scripts (CSP-safe).

const app = document.getElementById("app");
const whoEl = document.getElementById("who");
const logoutBtn = document.getElementById("logoutBtn");

let account = null;

// --- tiny helpers --------------------------------------------------------
async function api(path, method = "GET", body) {
  const opt = { method, headers: {}, credentials: "same-origin" };
  if (body !== undefined) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
  const r = await fetch(path, opt);
  let data = null;
  try { data = await r.json(); } catch (e) { /* no body */ }
  if (!r.ok) throw { status: r.status, detail: (data && data.detail) || r.statusText };
  return data;
}
function el(tag, attrs = {}, kids = []) {
  const n = document.createElement(tag);
  for (const k in attrs) {
    if (k === "class") n.className = attrs[k];
    else if (k === "text") n.textContent = attrs[k];
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), attrs[k]);
    else n.setAttribute(k, attrs[k]);
  }
  (Array.isArray(kids) ? kids : [kids]).forEach(c => { if (c) n.append(c); });
  return n;
}
function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
function fmtDate(s) { if (!s) return ""; const d = new Date(s); return isNaN(d) ? "" : d.toLocaleDateString(); }
function qs(name) { return new URLSearchParams(location.search).get(name); }
const isElder = () => account && (account.role === "elder" || account.role === "admin");

// --- boot ----------------------------------------------------------------
async function boot() {
  const inviteTok = qs("invite");
  if (inviteTok) return renderAccept(inviteTok);
  try {
    account = await api("/api/account/me");
    renderHome();
  } catch (e) {
    account = null;
    renderAuth();
  }
}

logoutBtn.addEventListener("click", async () => {
  try { await api("/api/account/logout", "POST"); } catch (e) {}
  account = null; location.href = "/church";
});

function setHeader() {
  if (account) {
    whoEl.textContent = `${account.name || account.email} · ${account.role}`;
    logoutBtn.classList.remove("hidden");
  } else {
    whoEl.textContent = ""; logoutBtn.classList.add("hidden");
  }
}

// --- auth screens --------------------------------------------------------
function renderAuth() {
  setHeader();
  clear(app);
  let mode = "login";
  const err = el("div", { class: "err" });

  const emailIn = el("input", { type: "email", placeholder: "you@church.org" });
  const passIn = el("input", { type: "password", placeholder: "password" });
  const nameIn = el("input", { type: "text", placeholder: "Your name" });
  const churchIn = el("input", { type: "text", placeholder: "Church name" });

  const form = el("div", { class: "card" });
  const submit = el("button", {});
  const toggle = el("button", { class: "link" });

  function paint() {
    clear(form); err.textContent = "";
    form.append(el("h2", { text: mode === "signup" ? "Start a church" : "Sign in" }));
    if (mode === "signup") {
      form.append(el("label", { text: "Church name" }), churchIn);
      form.append(el("label", { text: "Your name" }), nameIn);
    }
    form.append(el("label", { text: "Email" }), emailIn);
    form.append(el("label", { text: "Password" }), passIn);
    submit.textContent = mode === "signup" ? "Create church" : "Sign in";
    toggle.textContent = mode === "signup"
      ? "Already have an account? Sign in"
      : "Start a new church";
    form.append(el("div", { class: "row", style: "margin-top:12px" }, [submit, el("span", { class: "spacer" }), toggle]));
    form.append(err);
  }
  submit.addEventListener("click", async () => {
    err.textContent = "";
    try {
      if (mode === "signup") {
        await api("/api/churches", "POST", {
          church_name: churchIn.value.trim(), name: nameIn.value.trim(),
          email: emailIn.value.trim(), password: passIn.value,
        });
      } else {
        await api("/api/account/login", "POST", { email: emailIn.value.trim(), password: passIn.value });
      }
      account = await api("/api/account/me");
      renderHome();
    } catch (e) { err.textContent = e.detail || "Something went wrong"; }
  });
  toggle.addEventListener("click", () => { mode = mode === "signup" ? "login" : "signup"; paint(); });

  paint();
  app.append(el("p", { class: "muted center", text: "A place to carry one another's prayers." }), form);
}

function renderAccept(token) {
  setHeader();
  clear(app);
  const nameIn = el("input", { type: "text", placeholder: "Your name" });
  const passIn = el("input", { type: "password", placeholder: "Choose a password" });
  const err = el("div", { class: "err" });
  const submit = el("button", { text: "Join" });
  submit.addEventListener("click", async () => {
    err.textContent = "";
    try {
      await api("/api/invites/accept", "POST", { token, name: nameIn.value.trim(), password: passIn.value });
      account = await api("/api/account/me");
      history.replaceState({}, "", "/church");
      renderHome();
    } catch (e) { err.textContent = e.detail || "Invitation could not be accepted"; }
  });
  app.append(el("div", { class: "card" }, [
    el("h2", { text: "You've been invited" }),
    el("p", { class: "muted", text: "Set up your account to join your church's prayer list." }),
    el("label", { text: "Your name" }), nameIn,
    el("label", { text: "Password" }), passIn,
    el("div", { class: "row", style: "margin-top:12px" }, [submit]), err,
  ]));
}

// --- home ----------------------------------------------------------------
let tab = "mine";
function renderHome() {
  setHeader();
  clear(app);
  const tabs = el("div", { class: "tabs" });
  const defs = [["mine", "My prayers"], ["new", "Request prayer"]];
  if (isElder()) defs.push(["queue", "Elder queue"], ["flock", "My flock"], ["followup", "Follow-up"]);
  if (account.role === "admin" || account.role === "elder") defs.push(["invite", "Invite"]);
  defs.push(["settings", "Settings"]);
  defs.forEach(([k, label]) => {
    tabs.append(el("button", { class: tab === k ? "active" : "", onclick: () => { tab = k; renderHome(); }, text: label }));
  });
  app.append(tabs);
  const body = el("div", {});
  app.append(body);
  ({ mine: viewMine, new: viewNew, queue: viewQueue, flock: viewFlock,
     followup: viewFollowUp, invite: viewInvite, settings: viewSettings }[tab] || viewMine)(body);
}

function prayerCard(p, opts = {}) {
  const badges = el("div", { class: "row" });
  if (p.status === "answered") badges.append(el("span", { class: "badge answered", text: "answered" }));
  else if (!p.owner_id && p.visibility === "elders") badges.append(el("span", { class: "badge unclaimed", text: "needs an elder" }));
  else badges.append(el("span", { class: "badge", text: "ongoing" }));
  const card = el("div", { class: "prayer", onclick: () => renderDetail(p.id) }, [
    el("div", { class: "row" }, [el("span", { class: "title", text: p.title }), el("span", { class: "spacer" }), badges]),
    p.subject_name ? el("div", { class: "muted", text: "For " + p.subject_name }) : null,
    p.last_activity ? el("div", { class: "muted", text: "Last activity " + fmtDate(p.last_activity) }) : null,
  ]);
  return card;
}

async function listInto(node, path, empty) {
  clear(node);
  node.append(el("p", { class: "muted", text: "Loading…" }));
  try {
    const items = await api(path);
    clear(node);
    if (!items.length) { node.append(el("p", { class: "muted", text: empty })); return; }
    items.forEach(p => node.append(prayerCard(p)));
  } catch (e) { clear(node); node.append(el("p", { class: "err", text: e.detail || "Could not load" })); }
}

function viewMine(node) {
  const list = el("div", {});
  node.append(el("div", { class: "card" }, [el("h2", { text: "Prayers you're following" }), list]));
  listInto(list, "/api/mine", "Nothing yet. Request prayer to get started.");
}

function viewNew(node) {
  const title = el("input", { type: "text", placeholder: "Short title (e.g. Job interview)" });
  const subj = el("input", { type: "text", placeholder: "Who is this for? (optional)" });
  const bodyIn = el("textarea", { placeholder: "Share the need…" });
  const err = el("div", { class: "err" });
  const submit = el("button", { text: "Send to the elders" });
  submit.addEventListener("click", async () => {
    err.textContent = "";
    try {
      await api("/api/requests", "POST", { title: title.value.trim(), subject_name: subj.value.trim(), body: bodyIn.value.trim() });
      tab = "mine"; renderHome();
    } catch (e) { err.textContent = e.detail || "Could not submit"; }
  });
  node.append(el("div", { class: "card" }, [
    el("h2", { text: "Request prayer from the elders" }),
    el("label", { text: "Title" }), title,
    el("label", { text: "For whom" }), subj,
    el("label", { text: "Details" }), bodyIn,
    el("div", { class: "row", style: "margin-top:12px" }, [submit]), err,
  ]));
}

function viewQueue(node) {
  const list = el("div", {});
  node.append(el("div", { class: "card" }, [el("h2", { text: "Unclaimed requests" }), list]));
  listInto(list, "/api/elders/queue", "The queue is clear. Well shepherded.");
}
function viewFlock(node) {
  const list = el("div", {});
  node.append(el("div", { class: "card" }, [el("h2", { text: "Prayers you're shepherding" }), list]));
  listInto(list, "/api/elders/flock", "You aren't shepherding any prayers yet.");
}
function viewFollowUp(node) {
  const list = el("div", {});
  node.append(el("div", { class: "card" }, [
    el("h2", { text: "Needs follow-up" }),
    el("p", { class: "muted", text: "Ongoing prayers you own with no recent update." }), list]));
  listInto(list, "/api/elders/follow-up", "Nothing overdue. Everyone's been checked on.");
}

function viewInvite(node) {
  const email = el("input", { type: "email", placeholder: "person@church.org" });
  const role = el("select", {});
  const roles = account.role === "admin" ? [["member", "Member"], ["elder", "Elder"], ["admin", "Admin"]] : [["member", "Member"]];
  roles.forEach(([v, l]) => role.append(el("option", { value: v, text: l })));
  const out = el("div", {});
  const err = el("div", { class: "err" });
  const submit = el("button", { text: "Create invite link" });
  submit.addEventListener("click", async () => {
    err.textContent = ""; clear(out);
    try {
      const r = await api("/api/invites", "POST", { email: email.value.trim(), church_role: role.value });
      const link = location.origin + "/church?invite=" + encodeURIComponent(r.token);
      out.append(el("p", { class: "muted", text: "Share this link with " + r.email + ":" }),
                 el("input", { type: "text", value: link, readonly: "readonly" }));
    } catch (e) { err.textContent = e.detail || "Could not create invite"; }
  });
  node.append(el("div", { class: "card" }, [
    el("h2", { text: "Invite someone" }),
    el("label", { text: "Email" }), email,
    el("label", { text: "Role" }), role,
    el("div", { class: "row", style: "margin-top:12px" }, [submit]), err, out,
  ]));
}

// --- detail --------------------------------------------------------------
async function renderDetail(pid) {
  setHeader(); clear(app);
  app.append(el("button", { class: "link", onclick: renderHome, text: "← Back" }));
  const wrap = el("div", { class: "card" });
  app.append(wrap);
  wrap.append(el("p", { class: "muted", text: "Loading…" }));
  let p, timeline, notes = null;
  try {
    p = await api("/api/shared/" + pid);
    timeline = await api("/api/shared/" + pid + "/timeline");
    if (isElder()) { try { notes = await api("/api/shared/" + pid + "/notes"); } catch (e) {} }
  } catch (e) { clear(wrap); wrap.append(el("p", { class: "err", text: e.detail || "Could not load" })); return; }
  clear(wrap);

  wrap.append(el("div", { class: "row" }, [
    el("h2", { text: p.title, style: "margin:0" }), el("span", { class: "spacer" }),
    el("span", { class: "badge " + (p.status === "answered" ? "answered" : ""), text: p.status }),
  ]));
  if (p.subject_name) wrap.append(el("div", { class: "muted", text: "For " + p.subject_name }));
  if (p.body_md) wrap.append(el("p", { text: p.body_md }));

  // Elder: claim if unclaimed
  const err = el("div", { class: "err" });
  const actions = el("div", { class: "row", style: "margin-top:6px" });
  if (isElder() && !p.owner_id) {
    actions.append(el("button", { class: "small", text: "I've got this", onclick: () => act(() => api("/api/shared/" + pid + "/claim", "POST")) }));
  }
  const canStatus = isElder() || p.owner_id === account.user_id;
  if (canStatus && p.status !== "answered") {
    actions.append(el("button", { class: "small ghost", text: "Mark answered", onclick: () => {
      const t = prompt("A word of praise (optional):") || "";
      act(() => api("/api/shared/" + pid + "/status", "POST", { answered: true, text: t }));
    } }));
  } else if (canStatus && p.status === "answered") {
    actions.append(el("button", { class: "small ghost", text: "Reopen", onclick: () => act(() => api("/api/shared/" + pid + "/status", "POST", { answered: false, text: "" })) }));
  }
  wrap.append(actions);

  // Timeline
  wrap.append(el("h3", { text: "Updates" }));
  const tl = el("div", {});
  timeline.forEach(u => tl.append(el("div", { class: "update" }, [
    el("div", { class: "k", text: u.kind + " · " + fmtDate(u.created_at) }),
    el("div", { text: u.text }),
  ])));
  wrap.append(tl);
  const upd = el("textarea", { placeholder: "Add an update…" });
  wrap.append(upd, el("div", { class: "row", style: "margin-top:6px" }, [
    el("button", { class: "small", text: "Post update", onclick: () => {
      if (!upd.value.trim()) return;
      act(() => api("/api/shared/" + pid + "/updates", "POST", { text: upd.value.trim() }));
    } }),
  ]));

  // Elder-only pastoral notes
  if (isElder()) {
    wrap.append(el("h3", { text: "Pastoral notes (elders only)" }));
    const nn = el("div", {});
    (notes || []).forEach(n => nn.append(el("div", { class: "note" }, [
      el("div", { class: "k", text: fmtDate(n.created_at) }), el("div", { text: n.text }),
    ])));
    wrap.append(nn);
    const noteIn = el("textarea", { placeholder: "Private note (the member never sees this)…" });
    wrap.append(noteIn, el("div", { class: "row", style: "margin-top:6px" }, [
      el("button", { class: "small ghost", text: "Save note", onclick: () => {
        if (!noteIn.value.trim()) return;
        act(() => api("/api/shared/" + pid + "/notes", "POST", { text: noteIn.value.trim() }));
      } }),
    ]));
  }
  wrap.append(err);

  async function act(fn) {
    err.textContent = "";
    try { await fn(); renderDetail(pid); }
    catch (e) { err.textContent = e.detail || "Action failed"; }
  }
}

async function viewSettings(node) {
  const card = el("div", { class: "card" }, [el("h2", { text: "Notifications" }), el("p", { class: "muted", text: "Loading…" })]);
  node.append(card);
  let prefs;
  try { prefs = await api("/api/account/prefs"); }
  catch (e) { clear(card); card.append(el("p", { class: "err", text: e.detail || "Could not load" })); return; }
  clear(card);
  const emailCb = el("input", { type: "checkbox" }); emailCb.checked = prefs.email_enabled;
  const digestCb = el("input", { type: "checkbox" }); digestCb.checked = prefs.digest_weekly;
  const daySel = el("select", {});
  ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"].forEach((d, i) => {
    const o = el("option", { value: String(i), text: d });
    if (i === prefs.digest_day) o.selected = "selected";
    daySel.append(o);
  });
  const err = el("div", { class: "err" });
  const save = el("button", { text: "Save", onclick: async () => {
    err.textContent = "";
    try {
      await api("/api/account/prefs", "POST", {
        email_enabled: emailCb.checked, digest_weekly: digestCb.checked, digest_day: Number(daySel.value) });
      err.textContent = "Saved.";
    } catch (e) { err.textContent = e.detail || "Could not save"; }
  } });
  const pushStatus = el("div", { class: "muted" });
  const pushBtn = el("button", { class: "ghost", text: "Enable push on this device",
    onclick: () => enablePush(pushStatus) });
  card.append(
    el("h2", { text: "Notifications" }),
    el("label", { class: "row", style: "gap:8px" }, [emailCb, el("span", { text: "Email me about prayers I follow" })]),
    el("label", { class: "row", style: "gap:8px" }, [digestCb, el("span", { text: "Also send a weekly digest" })]),
    el("label", { text: "Digest day" }), daySel,
    el("div", { class: "row", style: "margin-top:12px" }, [save]), err,
    el("h3", { text: "Browser notifications" }),
    el("p", { class: "muted", text: "Get a push on this device when prayers you follow are updated." }),
    el("div", { class: "row" }, [pushBtn]), pushStatus,
  );
}

function urlB64ToUint8Array(b64) {
  const pad = "=".repeat((4 - (b64.length % 4)) % 4);
  const base = (b64 + pad).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base);
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
}

async function enablePush(statusEl) {
  statusEl.textContent = "";
  try {
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
      statusEl.textContent = "This browser doesn't support push notifications."; return;
    }
    const info = await api("/api/push/key");
    if (!info.enabled || !info.key) {
      statusEl.textContent = "Push isn't configured on the server yet."; return;
    }
    const reg = await navigator.serviceWorker.register("/church-sw.js", { scope: "/church" });
    const perm = await Notification.requestPermission();
    if (perm !== "granted") { statusEl.textContent = "Notification permission was denied."; return; }
    const sub = await reg.pushManager.subscribe({
      userVisibleOnly: true, applicationServerKey: urlB64ToUint8Array(info.key) });
    await api("/api/push/subscribe", "POST", { subscription: sub.toJSON() });
    statusEl.textContent = "Push enabled on this device.";
  } catch (e) {
    statusEl.textContent = (e && e.detail) || "Could not enable push here.";
  }
}

boot();
