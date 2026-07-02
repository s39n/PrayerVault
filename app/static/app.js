"use strict";
const $ = (id) => document.getElementById(id);
const views = ["login-view", "list-view", "detail-view", "new-view"];
let filterStatus = "ongoing";
let pollTimer = null;

function show(view) {
  views.forEach((v) => $(v).classList.toggle("hidden", v !== view));
  $("header-actions").classList.toggle("hidden", view === "login-view");
  if (pollTimer && view !== "detail-view") { clearInterval(pollTimer); pollTimer = null; }
}

async function api(path, opts = {}) {
  const r = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    ...opts,
  });
  if (r.status === 401) { show("login-view"); throw new Error("auth"); }
  if (!r.ok) {
    let msg = "Request failed";
    try { msg = (await r.json()).detail || msg; } catch {}
    throw new Error(msg);
  }
  return r.json();
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// Minimal renderer for the markdown we generate (bold, wikilinks, list items, paragraphs)
function md(s) {
  let h = esc(s);
  h = h.replace(/\[\[([^\]|]+)\|([^\]]+)\]\]/g, '<span class="scripture-ref">$2</span>');
  h = h.replace(/\[\[([^\]]+)\]\]/g, '<span class="scripture-ref">$1</span>');
  h = h.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  const lines = h.split("\n");
  let out = "", inList = false;
  for (const line of lines) {
    if (/^- /.test(line)) {
      if (!inList) { out += "<ul>"; inList = true; }
      out += "<li>" + line.slice(2) + "</li>";
    } else {
      if (inList) { out += "</ul>"; inList = false; }
      if (line.trim()) out += "<p>" + line + "</p>";
    }
  }
  if (inList) out += "</ul>";
  return out;
}

const aiBadge = (ai) =>
  ai === "pending" ? '<span class="badge pending"><span class="spinner"></span> seeking Scripture…</span>'
  : ai === "error" ? '<span class="badge error">AI failed</span>' : "";

// ---------- List ----------
async function renderList() {
  show("list-view");
  const items = await api("/api/prayers");
  const filtered = items.filter((i) => filterStatus === "all" || i.status === filterStatus);
  const chips = ["ongoing", "answered", "all"].map((f) =>
    `<span class="chip ${f === filterStatus ? "active" : ""}" data-filter="${f}">${f[0].toUpperCase() + f.slice(1)}</span>`).join(" ");
  const rows = filtered.map((i) => `
    <div class="card clickable" data-id="${esc(i.id)}">
      <div class="row" style="justify-content:space-between">
        <strong>${esc(i.title)}</strong>
        <span>
          <span class="badge">${i.type === "request" ? "Request" : "Prayer"}</span>
          <span class="badge ${i.status}">${esc(i.status)}</span>
          ${aiBadge(i.ai)}
        </span>
      </div>
      <div class="meta">${esc(i.date)}${i.requested_by ? " · for " + esc(i.requested_by) : ""}</div>
      <div class="meta" style="margin-top:6px">${esc(i.preview)}${i.preview.length >= 160 ? "…" : ""}</div>
    </div>`).join("");
  $("list-view").innerHTML = `<div class="row" style="margin-bottom:14px">${chips}</div>` +
    (rows || `<p class="meta">No ${filterStatus === "all" ? "" : filterStatus + " "}prayers yet.</p>`);
  $("list-view").querySelectorAll(".chip").forEach((c) =>
    c.addEventListener("click", () => { filterStatus = c.dataset.filter; renderList(); }));
  $("list-view").querySelectorAll(".card").forEach((c) =>
    c.addEventListener("click", () => renderDetail(c.dataset.id)));
}

// ---------- Detail ----------
async function renderDetail(id) {
  show("detail-view");
  const n = await api("/api/prayers/" + encodeURIComponent(id));
  const fm = n.frontmatter, s = n.sections;
  const sec = (name) => s[name] ? `<div class="section-title">${name}</div>${md(s[name])}` : "";
  const pending = fm.ai === "pending";
  $("detail-view").innerHTML = `
    <button class="link" id="btn-back">&larr; Back</button>
    <div class="card">
      <div class="row" style="justify-content:space-between">
        <h2 style="margin:0;font-weight:normal">${esc(fm.title)}</h2>
        <span>
          <span class="badge">${fm.type === "request" ? "Request" : "Prayer"}</span>
          <span class="badge ${esc(fm.status)}">${esc(fm.status)}</span>
          ${aiBadge(fm.ai)}
        </span>
      </div>
      <div class="meta">${esc(fm.date)}${fm["requested-by"] ? " · for " + esc(fm["requested-by"]) : ""}${fm["answered-date"] ? " · answered " + esc(fm["answered-date"]) : ""}</div>
      ${sec("Prayer")}${sec("Scripture")}${sec("Reflection")}${sec("How to Pray")}${sec("Updates")}
      <div class="row" style="margin-top:18px">
        ${fm.status === "ongoing"
          ? '<button class="primary" id="btn-answered">Mark answered</button>'
          : '<button id="btn-reopen">Reopen</button>'}
        <button id="btn-update">Add update</button>
        ${fm.ai !== "pending" ? '<button id="btn-regen">Regenerate response</button>' : ""}
      </div>
    </div>`;
  $("btn-back").addEventListener("click", renderList);
  const btnA = $("btn-answered"), btnR = $("btn-reopen"), btnU = $("btn-update"), btnG = $("btn-regen");
  if (btnA) btnA.addEventListener("click", async () => {
    const t = prompt("How was this prayer answered? (optional)") ?? "";
    await api(`/api/prayers/${encodeURIComponent(id)}/answered`, { method: "POST", body: JSON.stringify({ text: t }) });
    renderDetail(id);
  });
  if (btnR) btnR.addEventListener("click", async () => {
    await api(`/api/prayers/${encodeURIComponent(id)}/reopen`, { method: "POST", body: JSON.stringify({ text: "" }) });
    renderDetail(id);
  });
  if (btnU) btnU.addEventListener("click", async () => {
    const t = prompt("Update:");
    if (!t) return;
    await api(`/api/prayers/${encodeURIComponent(id)}/updates`, { method: "POST", body: JSON.stringify({ text: t }) });
    renderDetail(id);
  });
  if (btnG) btnG.addEventListener("click", async () => {
    await api(`/api/prayers/${encodeURIComponent(id)}/regenerate`, { method: "POST", body: JSON.stringify({}) });
    renderDetail(id);
  });
  if (pending && !pollTimer) {
    pollTimer = setInterval(async () => {
      const fresh = await api("/api/prayers/" + encodeURIComponent(id));
      if (fresh.frontmatter.ai !== "pending") { clearInterval(pollTimer); pollTimer = null; renderDetail(id); }
    }, 4000);
  }
}

// ---------- New ----------
function renderNew() {
  show("new-view");
  $("new-view").innerHTML = `
    <button class="link" id="btn-back2">&larr; Back</button>
    <div class="card">
      <h2 style="margin-top:0;font-weight:normal">New prayer</h2>
      <label>Type</label>
      <select id="np-type">
        <option value="prayer">My prayer</option>
        <option value="request">Prayer request (for someone else)</option>
      </select>
      <div id="np-who-wrap" class="hidden"><label>Requested by / for</label><input id="np-who" placeholder="e.g. The Johnson family"></div>
      <label>Title</label><input id="np-title" placeholder="A few words, e.g. Wisdom for a hard decision">
      <label>Prayer</label><textarea id="np-text" placeholder="Pour it out here…"></textarea>
      <div class="error-msg" id="np-error"></div>
      <button class="primary" id="np-save" style="margin-top:6px">Save &amp; seek Scripture</button>
    </div>`;
  $("btn-back2").addEventListener("click", renderList);
  $("np-type").addEventListener("change", (e) =>
    $("np-who-wrap").classList.toggle("hidden", e.target.value !== "request"));
  $("np-save").addEventListener("click", async () => {
    try {
      const res = await api("/api/prayers", { method: "POST", body: JSON.stringify({
        type: $("np-type").value, title: $("np-title").value.trim(),
        text: $("np-text").value.trim(), requested_by: $("np-who").value.trim(),
      })});
      renderDetail(res.id);
    } catch (e) { $("np-error").textContent = e.message; }
  });
}

// ---------- Auth / init ----------
async function doLogin() {
  $("login-error").textContent = "";
  try {
    await api("/api/login", { method: "POST", body: JSON.stringify({
      username: $("login-user").value.trim(), password: $("login-pass").value,
    })});
    renderList();
  } catch (e) { if (e.message !== "auth") $("login-error").textContent = e.message; else $("login-error").textContent = "Invalid username or password"; }
}

$("btn-login").addEventListener("click", doLogin);
$("login-pass").addEventListener("keydown", (e) => { if (e.key === "Enter") doLogin(); });
$("btn-new").addEventListener("click", renderNew);
$("btn-logout").addEventListener("click", async () => { await api("/api/logout", { method: "POST" }); show("login-view"); });

api("/api/me").then(renderList).catch(() => show("login-view"));
