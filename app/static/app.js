"use strict";
const $ = (id) => document.getElementById(id);
const views = ["login-view", "today-view", "list-view", "fruit-view", "ask-view", "you-view", "detail-view", "new-view"];
let filterStatus = "ongoing";
let pollTimer = null;

function show(view) {
  views.forEach((v) => $(v).classList.toggle("hidden", v !== view));
  const loggedOut = view === "login-view";
  $("header-actions").classList.toggle("hidden", loggedOut);
  $("nav").classList.toggle("hidden", loggedOut);
  if (pollTimer && view !== "detail-view") { clearInterval(pollTimer); pollTimer = null; }
}

// Highlight the active nav tab (today | prayers | fruit)
function setNav(name) {
  document.querySelectorAll(".nav-item").forEach((b) =>
    b.classList.toggle("active", b.dataset.nav === name));
}

// The ongoing prayer that has waited longest for attention
function longestWaiting(items) {
  const ongoing = items.filter((i) => i.status === "ongoing");
  return ongoing.length
    ? ongoing.slice().sort((a, b) => String(a.date).localeCompare(String(b.date)))[0]
    : null;
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
  setNav("prayers");
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
  // Featured "a word is needed" \u2014 the ongoing prayer that has waited longest for attention
  const featured = longestWaiting(items);
  const heroHtml = (featured && filterStatus !== "answered") ? `
    <div class="hero" data-id="${esc(featured.id)}">
      <div class="eyebrow">A word is needed</div>
      <h2>${esc(featured.title)}</h2>
      <p>When you're ready, carry this one back into the light.</p>
      <button class="link" style="font-size:1rem" data-hero-open="${esc(featured.id)}">Open &rarr;</button>
    </div>` : "";
  $("list-view").innerHTML =
    heroHtml +
    `<input id="search-box" placeholder="Search prayers by meaning\u2026 (press Enter)" style="margin-bottom:12px">` +
    `<div class="row" style="margin-bottom:14px">${chips}</div>` +
    (rows || `<p class="meta">No ${filterStatus === "all" ? "" : filterStatus + " "}prayers yet.</p>`);
  const hero = $("list-view").querySelector(".hero");
  if (hero) hero.addEventListener("click", () => renderDetail(hero.dataset.id));
  $("search-box").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.target.value.trim()) renderSearch(e.target.value.trim());
  });
  $("list-view").querySelectorAll(".chip").forEach((c) =>
    c.addEventListener("click", () => { filterStatus = c.dataset.filter; renderList(); }));
  $("list-view").querySelectorAll(".card").forEach((c) =>
    c.addEventListener("click", () => renderDetail(c.dataset.id)));
}

async function renderSearch(q) {
  show("list-view");
  let results;
  try { results = await api("/api/search?q=" + encodeURIComponent(q)); }
  catch (e) { $("list-view").innerHTML = `<p class="meta">${esc(e.message)}</p><button class="link" id="btn-back3">&larr; Back</button>`;
    $("btn-back3").addEventListener("click", renderList); return; }
  const rows = results.map((i) => `
    <div class="card clickable" data-id="${esc(i.id)}">
      <div class="row" style="justify-content:space-between">
        <strong>${esc(i.title)}</strong>
        <span><span class="badge">${Math.round(i.score * 100)}% match</span>
        <span class="badge ${i.status}">${esc(i.status)}</span></span>
      </div>
      <div class="meta">${esc(i.date)}${i.requested_by ? " \u00b7 for " + esc(i.requested_by) : ""}</div>
      <div class="meta" style="margin-top:6px">${esc(i.preview)}</div>
    </div>`).join("");
  $("list-view").innerHTML =
    `<button class="link" id="btn-back3">&larr; All prayers</button>
     <p class="meta">Results for \u201c${esc(q)}\u201d</p>` +
    (rows || `<p class="meta">Nothing similar found.</p>`);
  $("btn-back3").addEventListener("click", renderList);
  $("list-view").querySelectorAll(".card").forEach((c) =>
    c.addEventListener("click", () => renderDetail(c.dataset.id)));
}

// ---------- Today ----------
// Curated, offline verse-of-the-day list (Reformed-friendly). No external calls.
const VERSES = [
  ["The Lord is my shepherd; I shall not want.", "Psalm 23:1"],
  ["Cast all your anxieties on him, because he cares for you.", "1 Peter 5:7"],
  ["Be still, and know that I am God.", "Psalm 46:10"],
  ["The steadfast love of the Lord never ceases; his mercies are new every morning.", "Lamentations 3:22-23"],
  ["Trust in the Lord with all your heart, and do not lean on your own understanding.", "Proverbs 3:5"],
  ["I can do all things through him who strengthens me.", "Philippians 4:13"],
  ["Come to me, all who labor and are heavy laden, and I will give you rest.", "Matthew 11:28"],
  ["The Lord is near to all who call on him, to all who call on him in truth.", "Psalm 145:18"],
  ["Do not be anxious about anything, but in everything by prayer let your requests be made known to God.", "Philippians 4:6"],
  ["Wait for the Lord; be strong, and let your heart take courage.", "Psalm 27:14"],
  ["And we know that for those who love God all things work together for good.", "Romans 8:28"],
  ["He heals the brokenhearted and binds up their wounds.", "Psalm 147:3"],
  ["The Lord will fight for you, and you have only to be silent.", "Exodus 14:14"],
  ["My grace is sufficient for you, for my power is made perfect in weakness.", "2 Corinthians 12:9"],
  ["Fear not, for I am with you; be not dismayed, for I am your God.", "Isaiah 41:10"],
  ["This is the day that the Lord has made; let us rejoice and be glad in it.", "Psalm 118:24"],
  ["The Lord is my light and my salvation; whom shall I fear?", "Psalm 27:1"],
  ["Whom have I in heaven but you? And there is nothing on earth that I desire besides you.", "Psalm 73:25"],
  ["Delight yourself in the Lord, and he will give you the desires of your heart.", "Psalm 37:4"],
  ["The name of the Lord is a strong tower; the righteous man runs into it and is safe.", "Proverbs 18:10"],
  ["Weeping may tarry for the night, but joy comes with the morning.", "Psalm 30:5"],
  ["Let us hold fast the confession of our hope without wavering, for he who promised is faithful.", "Hebrews 10:23"],
  ["Bless the Lord, O my soul, and forget not all his benefits.", "Psalm 103:2"],
  ["In peace I will both lie down and sleep; for you alone, O Lord, make me dwell in safety.", "Psalm 4:8"],
];

function verseOfDay() {
  const start = new Date(new Date().getFullYear(), 0, 0);
  const day = Math.floor((Date.now() - start) / 86400000);
  return VERSES[day % VERSES.length];
}

function greeting() {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}

async function renderToday() {
  show("today-view");
  setNav("today");
  const items = await api("/api/prayers");
  const [text, ref] = verseOfDay();
  const featured = longestWaiting(items);
  const answered = items.filter((i) => i.status === "answered");
  const today = new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });

  const heroHtml = featured ? `
    <div class="hero" data-id="${esc(featured.id)}">
      <div class="eyebrow">A word is needed</div>
      <h2>${esc(featured.title)}</h2>
      <p>Carry this one back into the light this morning.</p>
      <button class="link" style="font-size:1rem">Open &rarr;</button>
    </div>
    <div class="next-step">The step before you now: sit with this prayer for a moment before the day begins.</div>`
    : (answered.length
      ? `<div class="next-step">No prayers are waiting on you today. Visit <strong>Fruit</strong> to remember how God has answered.</div>`
      : `<div class="next-step">Nothing is on your heart here yet. When you're ready, bring a matter into the light.</div>
         <div class="row" style="justify-content:center"><button class="primary" id="today-new">+ Bring a matter</button></div>`);

  $("today-view").innerHTML = `
    <div class="greeting">
      <span class="eyebrow">${esc(today)}</span>
      <h2>${greeting()}, Sean.</h2>
    </div>
    <div class="verse-card">
      <div class="eyebrow">A word for today</div>
      <div class="verse-text">“${esc(text)}”</div>
      <div class="verse-ref">${esc(ref)}</div>
    </div>
    ${heroHtml}`;

  const hero = $("today-view").querySelector(".hero");
  if (hero) hero.addEventListener("click", () => renderDetail(hero.dataset.id));
  const tn = $("today-new");
  if (tn) tn.addEventListener("click", renderNew);
}

// ---------- Fruit (answered prayers) ----------
async function renderFruit() {
  show("fruit-view");
  setNav("fruit");
  const items = await api("/api/prayers");
  const answered = items.filter((i) => i.status === "answered")
    .sort((a, b) => String(b.answered_date || b.date).localeCompare(String(a.answered_date || a.date)));
  const cards = answered.map((i) => `
    <div class="fruit-card" data-id="${esc(i.id)}">
      <div class="answered-on">Answered${i.answered_date ? " · " + esc(i.answered_date) : ""}</div>
      <h3>${esc(i.title)}</h3>
      <div class="meta" style="margin-top:6px">${esc(i.preview)}${i.preview.length >= 160 ? "…" : ""}</div>
    </div>`).join("");
  $("fruit-view").innerHTML = `
    <div class="greeting">
      <span class="eyebrow">Fruit</span>
      <h2>How God has answered</h2>
    </div>
    ${answered.length
      ? `<div class="fruit-grid">${cards}</div>`
      : `<p class="meta" style="text-align:center">No answered prayers yet. Mark a prayer answered and it will bloom here.</p>`}`;
  $("fruit-view").querySelectorAll(".fruit-card").forEach((c) =>
    c.addEventListener("click", () => renderDetail(c.dataset.id)));
}

// ---------- Ask (Scripture Q&A) ----------
function renderAsk() {
  show("ask-view");
  setNav("ask");
  $("ask-view").innerHTML = `
    <div class="greeting">
      <span class="eyebrow">Ask</span>
      <h2>Bring a question to Scripture</h2>
    </div>
    <div class="card">
      <label>Your question</label>
      <textarea id="ask-q" placeholder="e.g. How do I trust God when the future feels uncertain?"></textarea>
      <div class="error-msg" id="ask-error"></div>
      <button class="primary" id="ask-go" style="margin-top:6px">Seek an answer</button>
    </div>
    <div id="ask-result"></div>`;
  $("ask-go").addEventListener("click", doAsk);
  $("ask-q").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) doAsk();
  });
}

async function doAsk() {
  const q = $("ask-q").value.trim();
  if (!q) { $("ask-error").textContent = "Type a question first."; return; }
  $("ask-error").textContent = "";
  const btn = $("ask-go");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Searching Scripture…';
  $("ask-result").innerHTML = "";
  try {
    const r = await api("/api/ask", { method: "POST", body: JSON.stringify({ question: q }) });
    $("ask-result").innerHTML = `
      <div class="card">
        ${r.scripture_md ? `<div class="section-title">Scripture</div>${md(r.scripture_md)}` : ""}
        ${r.answer ? `<div class="section-title">A word</div>${md(r.answer)}` : ""}
        <p class="meta" style="margin-top:16px;font-style:italic">An aid for reflection, drawn from Scripture — not a replacement for reading God's Word or the counsel of your church.</p>
      </div>`;
  } catch (e) {
    $("ask-error").textContent = e.message;
  }
  btn.disabled = false;
  btn.innerHTML = "Seek an answer";
}

// ---------- You (settings) ----------
async function renderYou() {
  show("you-view");
  setNav("you");
  $("you-view").innerHTML = `
    <div class="greeting"><span class="eyebrow">You</span><h2>Settings</h2></div>
    <p class="meta" style="text-align:center">Loading…</p>`;
  let s;
  try { s = await api("/api/settings"); }
  catch (e) { $("you-view").innerHTML = `<p class="meta">${esc(e.message)}</p>`; return; }
  const m = s.morning;
  const opts = (n, sel) => Array.from({ length: n }, (_, i) =>
    `<option value="${i}" ${i === sel ? "selected" : ""}>${String(i).padStart(2, "0")}</option>`).join("");
  $("you-view").innerHTML = `
    <div class="greeting"><span class="eyebrow">You</span><h2>Settings</h2></div>
    <div class="card">
      <div class="section-title">Morning prayer prompt</div>
      <label style="text-transform:none;letter-spacing:0;color:var(--ink);margin-top:6px">
        <input type="checkbox" id="mp-enabled" ${m.enabled ? "checked" : ""} style="width:auto;margin-right:8px;vertical-align:middle">
        Send me a morning prompt
      </label>
      <label>Delivery</label>
      <select id="mp-delivery">
        <option value="ntfy" ${m.delivery === "ntfy" ? "selected" : ""}>ntfy push notification</option>
        <option value="none" ${m.delivery === "none" ? "selected" : ""}>In-app only (no push)</option>
      </select>
      <label>ntfy topic</label>
      <input id="mp-topic" value="${esc(m.ntfy_topic)}" placeholder="e.g. sean-prayer-7fq3k9">
      <p class="meta">Install the ntfy app and subscribe to this exact topic on ${esc(s.ntfy_server)}. Choose something private and hard to guess — anyone who knows the topic can read it.</p>
      <label>Time</label>
      <div class="row">
        <select id="mp-hour" style="width:auto">${opts(24, m.hour)}</select>
        <span>:</span>
        <select id="mp-min" style="width:auto">${opts(60, m.minute)}</select>
      </div>
      <div class="error-msg" id="mp-error"></div>
      <div class="row" style="margin-top:14px">
        <button class="primary" id="mp-save">Save</button>
        <button id="mp-test">Send test push</button>
        <span id="mp-status" class="meta"></span>
      </div>
    </div>`;

  const gather = () => ({ morning: {
    enabled: $("mp-enabled").checked,
    delivery: $("mp-delivery").value,
    ntfy_topic: $("mp-topic").value.trim(),
    hour: parseInt($("mp-hour").value, 10),
    minute: parseInt($("mp-min").value, 10),
  }});

  $("mp-save").addEventListener("click", async () => {
    $("mp-error").textContent = "";
    $("mp-status").textContent = "";
    try {
      await api("/api/settings", { method: "POST", body: JSON.stringify(gather()) });
      $("mp-status").textContent = "Saved.";
    } catch (e) { $("mp-error").textContent = e.message; }
  });

  $("mp-test").addEventListener("click", async () => {
    $("mp-error").textContent = "";
    $("mp-status").textContent = "";
    const btn = $("mp-test");
    btn.disabled = true;
    try {
      await api("/api/settings", { method: "POST", body: JSON.stringify(gather()) });
      await api("/api/notify/test", { method: "POST", body: JSON.stringify({}) });
      $("mp-status").textContent = "Test push sent — check your ntfy app.";
    } catch (e) { $("mp-error").textContent = e.message; }
    btn.disabled = false;
  });
}

// ---------- Detail ----------
function relatedHtml(s) {
  if (!s["Related"]) return "";
  const items = s["Related"].split("\n").map((line) => {
    const m = line.match(/\[\[([^\]|]+)\|([^\]]+)\]\]/) || line.match(/\[\[([^\]]+)\]\]/);
    if (!m) return "";
    return `<li><button class="link rel-link" data-id="${esc(m[1])}">${esc(m[2] || m[1])}</button></li>`;
  }).join("");
  return `<div class="section-title">Related</div><ul>${items}</ul>`;
}

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
      ${sec("Prayer")}${sec("Scripture")}${sec("Reflection")}${sec("How to Pray")}${relatedHtml(s)}${sec("Updates")}
      <div class="row" style="margin-top:18px">
        ${fm.status === "ongoing"
          ? '<button class="primary" id="btn-answered">Mark answered</button>'
          : '<button id="btn-reopen">Reopen</button>'}
        <button id="btn-update">Add update</button>
        ${fm.ai !== "pending" ? '<button id="btn-regen">Regenerate response</button>' : ""}
      </div>
    </div>`;
  $("btn-back").addEventListener("click", renderList);
  $("detail-view").querySelectorAll(".rel-link").forEach((a) =>
    a.addEventListener("click", () => renderDetail(a.dataset.id)));
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
      <div class="row" style="justify-content:space-between;align-items:flex-end">
        <label style="margin-bottom:4px">Prayer</label>
        <button id="np-mic" title="Speak your prayer">&#127908; Record</button>
      </div>
      <textarea id="np-text" placeholder="Pour it out here… or press Record and speak"></textarea>
      <div class="error-msg" id="np-error"></div>
      <button class="primary" id="np-save" style="margin-top:6px">Save &amp; seek Scripture</button>
    </div>`;
  $("btn-back2").addEventListener("click", renderList);
  $("np-type").addEventListener("change", (e) =>
    $("np-who-wrap").classList.toggle("hidden", e.target.value !== "request"));
  let rec = null, chunks = [];
  const micBtn = $("np-mic");
  micBtn.addEventListener("click", async () => {
    if (rec && rec.state === "recording") { rec.stop(); return; }
    if (!navigator.mediaDevices?.getUserMedia) {
      $("np-error").textContent = "Microphone needs a secure connection \u2014 use the https:// address.";
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      chunks = [];
      rec = new MediaRecorder(stream);
      rec.ondataavailable = (e) => chunks.push(e.data);
      rec.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        micBtn.disabled = true;
        micBtn.innerHTML = '<span class="spinner"></span> Transcribing\u2026';
        try {
          const blob = new Blob(chunks, { type: rec.mimeType || "audio/webm" });
          const fd = new FormData();
          fd.append("audio", blob, "prayer.webm");
          const r = await fetch("/api/transcribe", { method: "POST", body: fd, credentials: "same-origin" });
          if (!r.ok) throw new Error((await r.json()).detail || "Transcription failed");
          const t = (await r.json()).text;
          const box = $("np-text");
          box.value = (box.value.trim() ? box.value.trim() + " " : "") + t;
        } catch (e) { $("np-error").textContent = e.message; }
        micBtn.disabled = false;
        micBtn.innerHTML = "&#127908; Record";
      };
      rec.start();
      micBtn.innerHTML = "&#9209; Stop";
      $("np-error").textContent = "";
    } catch (e) { $("np-error").textContent = "Microphone access denied: " + e.message; }
  });

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
    renderToday();
  } catch (e) { if (e.message !== "auth") $("login-error").textContent = e.message; else $("login-error").textContent = "Invalid username or password"; }
}

$("btn-login").addEventListener("click", doLogin);
$("login-pass").addEventListener("keydown", (e) => { if (e.key === "Enter") doLogin(); });
$("btn-new").addEventListener("click", renderNew);
$("btn-logout").addEventListener("click", async () => { await api("/api/logout", { method: "POST" }); show("login-view"); });
document.querySelectorAll(".nav-item").forEach((b) =>
  b.addEventListener("click", () => {
    const n = b.dataset.nav;
    if (n === "today") renderToday();
    else if (n === "fruit") renderFruit();
    else if (n === "ask") renderAsk();
    else if (n === "you") renderYou();
    else { filterStatus = "ongoing"; renderList(); }
  }));

api("/api/me").then(renderToday).catch(() => show("login-view"));
