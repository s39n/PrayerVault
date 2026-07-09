"use strict";
const $ = (id) => document.getElementById(id);
const views = ["login-view", "today-view", "list-view", "fruit-view", "ask-view", "dictate-view", "you-view", "detail-view", "new-view"];
let filterStatus = "ongoing";
let pollTimer = null;

function show(view) {
  views.forEach((v) => $(v).classList.toggle("hidden", v !== view));
  const loggedOut = view === "login-view";
  $("header-actions").classList.toggle("hidden", loggedOut);
  $("nav").classList.toggle("hidden", loggedOut);
  document.body.classList.toggle("logged-out", loggedOut);
  if (pollTimer && view !== "detail-view") { clearInterval(pollTimer); pollTimer = null; }
  if (view !== "dictate-view" && window._dictateStopRecording) {
    window._dictateStopRecording();
  }
}

function setNav(name) {
  document.querySelectorAll(".nav-item").forEach((b) =>
    b.classList.toggle("active", b.dataset.nav === name));
}

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
    `<input id="search-box" placeholder="Search prayers by meaning… (press Enter)" style="margin-bottom:12px">` +
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
      <div class="meta">${esc(i.date)}${i.requested_by ? " · for " + esc(i.requested_by) : ""}</div>
      <div class="meta" style="margin-top:6px">${esc(i.preview)}</div>
    </div>`).join("");
  $("list-view").innerHTML =
    `<button class="link" id="btn-back3">&larr; All prayers</button>
     <p class="meta">Results for “${esc(q)}”</p>` +
    (rows || `<p class="meta">Nothing similar found.</p>`);
  $("btn-back3").addEventListener("click", renderList);
  $("list-view").querySelectorAll(".card").forEach((c) =>
    c.addEventListener("click", () => renderDetail(c.dataset.id)));
}

// ---------- Today ----------
const VERSES = [
  ["Cast your burden on the Lord, and he will sustain you.", "Psalm 55:22"],
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

// Gently rotate the displayed verse wherever one is visible (login card, Today).
let verseIdx = Math.floor(Math.random() * VERSES.length);

function fadeSwap(els, apply) {
  els.forEach((e) => { e.style.opacity = "0"; });
  setTimeout(() => { apply(); els.forEach((e) => { e.style.opacity = "1"; }); }, 600);
}

setInterval(() => {
  const loginVisible = !$("login-view").classList.contains("hidden");
  const todayText = document.querySelector("#today-view .verse-text");
  const todayVisible = todayText && !$("today-view").classList.contains("hidden");
  if (!loginVisible && !todayVisible) return;
  verseIdx = (verseIdx + 1) % VERSES.length;
  const [text, ref] = VERSES[verseIdx];
  if (loginVisible) {
    const lv = $("login-verse");
    if (lv) fadeSwap([lv], () => { lv.textContent = `“${text}” — ${ref}`; });
  }
  if (todayVisible) {
    const tr = document.querySelector("#today-view .verse-ref");
    fadeSwap([todayText, tr], () => {
      todayText.textContent = `“${text}”`;
      if (tr) tr.textContent = ref;
    });
  }
}, 10000);

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
  let first = "friend";
  try {
    const me = await api("/api/me");
    first = (me.name || me.user || "friend").split(" ")[0];
    first = first.charAt(0).toUpperCase() + first.slice(1);
  } catch (e) { /* greeting only */ }
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
      <h2>${greeting()}, ${esc(first)}.</h2>
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

// ---------- Dictate (Speech to Text) ----------
async function renderDictate() {
  try {
    const me = await api("/api/me");
    if (!me || !me.admin) {
      renderToday();
      return;
    }
  } catch (e) {
    show("login-view");
    return;
  }

  show("dictate-view");
  setNav("dictate");
  
  $("dictate-view").innerHTML = `
    <div class="greeting">
      <span class="eyebrow">Dictate</span>
      <h2>Speech to Text</h2>
    </div>
    <div class="card dictate-container">
      <div style="display:flex; justify-content:space-between; align-items:center">
        <label style="margin:0">Transcribed Text</label>
        <span id="dictate-char-count" class="meta" style="font-size:0.8rem">0 characters</span>
      </div>
      <textarea id="dictate-text" class="dictate-textarea" placeholder="Start speaking using the hotkey, or type here..."></textarea>
      <div class="row" style="margin-top:6px; justify-content:space-between">
        <div class="row">
          <button id="dictate-btn-copy" class="primary btn-dictate-action" title="Copy to clipboard">📋 Copy</button>
          <button id="dictate-btn-clear" class="btn-dictate-action" title="Clear text">🗑️ Clear</button>
          <button id="dictate-btn-download" class="btn-dictate-action" title="Download as .txt file">💾 Download</button>
        </div>
        <button id="dictate-btn-new-prayer" class="btn-dictate-action" style="border-color:var(--gold); color:var(--gold)" title="Create a new prayer note with this text">✨ Create Prayer</button>
      </div>
      <div class="error-msg" id="dictate-error"></div>
    </div>
    <div class="card dictate-mic-container">
      <button id="dictate-mic-btn" class="dictate-mic-btn" aria-label="Record button">🎙️</button>
      <div id="dictate-status" class="dictate-status-text">Ready to Record</div>
      <div id="dictate-hint" class="dictate-hint">Press and hold Spacebar to speak (Push-to-Talk)</div>
      <div class="waveform" id="dictate-waveform">
        <div class="wave-bar"></div>
        <div class="wave-bar"></div>
        <div class="wave-bar"></div>
        <div class="wave-bar"></div>
        <div class="wave-bar"></div>
        <div class="wave-bar"></div>
        <div class="wave-bar"></div>
        <div class="wave-bar"></div>
      </div>
    </div>
    <div class="card">
      <div class="section-title">Dictation Settings</div>
      <div class="settings-grid">
        <div>
          <label>Mode</label>
          <select id="dictate-setting-mode">
            <option value="ptt">Push-to-Talk (Hold key/button to record)</option>
            <option value="toggle">Tap-to-Talk (Tap key/button to toggle)</option>
          </select>
        </div>
        <div>
          <label>Hotkey</label>
          <select id="dictate-setting-hotkey">
            <option value="Space">Spacebar</option>
            <option value="Backquote">Backtick (`)</option>
            <option value="Control">Control (Ctrl)</option>
            <option value="Shift">Shift</option>
            <option value="Alt">Alt</option>
          </select>
        </div>
      </div>
      <p class="meta" style="margin-top:12px; font-size:0.8rem">
        * Spacebar hotkey only works when you are not typing in a text field.<br>
        * Dictation requires microphone permission. Please make sure HTTPS or localhost is used.
      </p>
    </div>`;

  let mediaRecorder = null;
  let audioChunks = [];
  let recordStartTime = null;
  let recordDurationInterval = null;
  let activeStream = null;

  const micBtn = $("dictate-mic-btn");
  const statusText = $("dictate-status");
  const hintText = $("dictate-hint");
  const waveform = $("dictate-waveform");
  const errorText = $("dictate-error");
  const dictateText = $("dictate-text");

  let mode = localStorage.getItem("dictate_mode") || "ptt";
  let hotkey = localStorage.getItem("dictate_hotkey") || "Space";
  
  $("dictate-setting-mode").value = mode;
  $("dictate-setting-hotkey").value = hotkey;

  function updateHint() {
    const keyLabel = {
      "Space": "Spacebar",
      "Backquote": "Backtick (`)",
      "Control": "Control Key",
      "Shift": "Shift Key",
      "Alt": "Alt Key"
    }[hotkey];
    
    if (mode === "ptt") {
      hintText.textContent = `Hold the ${keyLabel} or hold the mic button to record.`;
    } else {
      hintText.textContent = `Press the ${keyLabel} or tap the mic button to start/stop.`;
    }
  }
  updateHint();

  function updateCharCount() {
    const chars = dictateText.value.length;
    $("dictate-char-count").textContent = `${chars} character${chars === 1 ? "" : "s"}`;
  }
  dictateText.addEventListener("input", updateCharCount);

  async function startRecording() {
    if (mediaRecorder && mediaRecorder.state !== "inactive") return;
    errorText.textContent = "";
    audioChunks = [];
    if (!navigator.mediaDevices?.getUserMedia) {
      errorText.textContent = "Microphone needs a secure connection (HTTPS or localhost).";
      return;
    }
    try {
      activeStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaRecorder = new MediaRecorder(activeStream);
      mediaRecorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) audioChunks.push(e.data);
      };
      
      mediaRecorder.onstop = async () => {
        if (activeStream) {
          activeStream.getTracks().forEach(track => track.stop());
          activeStream = null;
        }
        clearInterval(recordDurationInterval);
        micBtn.className = "dictate-mic-btn transcribing";
        micBtn.innerHTML = "⏳";
        statusText.textContent = "Transcribing your voice...";
        waveform.classList.remove("active");
        
        try {
          const blob = new Blob(audioChunks, { type: mediaRecorder.mimeType || "audio/webm" });
          if (blob.size === 0) throw new Error("Recording is empty.");
          const fd = new FormData();
          fd.append("audio", blob, "dictation.webm");
          const r = await fetch("/api/transcribe", { method: "POST", body: fd, credentials: "same-origin" });
          if (!r.ok) {
            const errData = await r.json().catch(() => ({}));
            throw new Error(errData.detail || "Transcription failed.");
          }
          const result = await r.json();
          const transcribedText = result.text || "";
          if (transcribedText.trim()) {
            const oldVal = dictateText.value.trim();
            dictateText.value = (oldVal ? oldVal + " " : "") + transcribedText.trim();
            updateCharCount();
            toast("Transcribed successfully!");
          } else {
            toast("No speech detected.");
          }
        } catch (err) {
          errorText.textContent = err.message;
          toast("Transcription failed.");
        } finally {
          micBtn.className = "dictate-mic-btn";
          micBtn.innerHTML = "🎙️";
          statusText.textContent = "Ready to Record";
        }
      };
      
      mediaRecorder.start();
      recordStartTime = Date.now();
      micBtn.className = "dictate-mic-btn recording";
      micBtn.innerHTML = "🛑";
      waveform.classList.add("active");
      
      statusText.textContent = "Recording... 0:00";
      recordDurationInterval = setInterval(() => {
        const elapsed = Math.round((Date.now() - recordStartTime) / 1000);
        const mins = Math.floor(elapsed / 60);
        const secs = elapsed % 60;
        statusText.textContent = `Recording... ${mins}:${secs.toString().padStart(2, '0')}`;
      }, 1000);
    } catch (err) {
      errorText.textContent = "Microphone access denied: " + err.message;
      micBtn.className = "dictate-mic-btn";
      micBtn.innerHTML = "🎙️";
      statusText.textContent = "Ready to Record";
    }
  }

  function stopRecording() {
    if (mediaRecorder && mediaRecorder.state === "recording") {
      mediaRecorder.stop();
    }
  }

  window._dictateStopRecording = stopRecording;

  function setupMicButton() {
    const btn = $("dictate-mic-btn");
    const cloned = btn.cloneNode(true);
    btn.parentNode.replaceChild(cloned, btn);
    
    if (mode === "ptt") {
      let isDown = false;
      const start = (e) => {
        e.preventDefault();
        if (isDown) return;
        isDown = true;
        startRecording();
      };
      const end = (e) => {
        e.preventDefault();
        if (!isDown) return;
        isDown = false;
        stopRecording();
      };
      cloned.addEventListener("mousedown", start);
      cloned.addEventListener("touchstart", start, { passive: false });
      cloned.addEventListener("mouseup", end);
      cloned.addEventListener("mouseleave", end);
      cloned.addEventListener("touchend", end, { passive: false });
      cloned.addEventListener("touchcancel", end, { passive: false });
    } else {
      cloned.addEventListener("click", (e) => {
        e.preventDefault();
        if (mediaRecorder && mediaRecorder.state === "recording") {
          stopRecording();
        } else {
          startRecording();
        }
      });
    }
  }
  setupMicButton();

  function isTyping() {
    const active = document.activeElement;
    if (!active) return false;
    return active.tagName === "INPUT" || active.tagName === "TEXTAREA" || active.isContentEditable;
  }

  const handleKeyDown = (e) => {
    if ($("dictate-view").classList.contains("hidden")) return;
    let match = false;
    if (hotkey === "Space" && e.code === "Space") {
      if (isTyping()) return;
      match = true;
    } else if (hotkey === "Backquote" && e.code === "Backquote") {
      match = true;
    } else if (hotkey === "Control" && e.key === "Control") {
      match = true;
    } else if (hotkey === "Shift" && e.key === "Shift") {
      match = true;
    } else if (hotkey === "Alt" && e.key === "Alt") {
      match = true;
    }
    
    if (match) {
      e.preventDefault();
      if (mode === "ptt") {
        if (!window._dictateKeyPressed) {
          window._dictateKeyPressed = true;
          startRecording();
        }
      } else {
        if (!window._dictateKeyPressed) {
          window._dictateKeyPressed = true;
          if (mediaRecorder && mediaRecorder.state === "recording") {
            stopRecording();
          } else {
            startRecording();
          }
        }
      }
    }
  };

  const handleKeyUp = (e) => {
    if ($("dictate-view").classList.contains("hidden")) return;
    let match = false;
    if (hotkey === "Space" && e.code === "Space") match = true;
    else if (hotkey === "Backquote" && e.code === "Backquote") match = true;
    else if (hotkey === "Control" && e.key === "Control") match = true;
    else if (hotkey === "Shift" && e.key === "Shift") match = true;
    else if (hotkey === "Alt" && e.key === "Alt") match = true;
    
    if (match) {
      window._dictateKeyPressed = false;
      if (mode === "ptt") stopRecording();
    }
  };

  if (window._dictateKeydown) window.removeEventListener("keydown", window._dictateKeydown);
  if (window._dictateKeyup) window.removeEventListener("keyup", window._dictateKeyup);
  window._dictateKeydown = handleKeyDown;
  window._dictateKeyup = handleKeyUp;
  window.addEventListener("keydown", window._dictateKeydown);
  window.addEventListener("keyup", window._dictateKeyup);

  $("dictate-setting-mode").addEventListener("change", (e) => {
    mode = e.target.value;
    localStorage.setItem("dictate_mode", mode);
    updateHint();
    setupMicButton();
  });
  
  $("dictate-setting-hotkey").addEventListener("change", (e) => {
    hotkey = e.target.value;
    localStorage.setItem("dictate_hotkey", hotkey);
    updateHint();
    setupMicButton();
  });

  $("dictate-btn-copy").addEventListener("click", () => {
    const text = dictateText.value;
    if (!text) { toast("Nothing to copy."); return; }
    navigator.clipboard.writeText(text).then(() => {
      const copyBtn = $("dictate-btn-copy");
      const origText = copyBtn.textContent;
      copyBtn.textContent = "✅ Copied!";
      toast("Text copied to clipboard.");
      setTimeout(() => { copyBtn.textContent = origText; }, 2000);
    }).catch(err => { toast("Failed to copy text: " + err); });
  });

  $("dictate-btn-clear").addEventListener("click", () => {
    if (dictateText.value.trim() && confirm("Are you sure you want to clear the transcribed text?")) {
      dictateText.value = "";
      updateCharCount();
      toast("Text cleared.");
    }
  });

  $("dictate-btn-download").addEventListener("click", () => {
    const text = dictateText.value;
    if (!text) { toast("Nothing to download."); return; }
    const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    const dateStr = new Date().toISOString().slice(0, 10);
    a.download = `dictation-${dateStr}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    toast("Download started.");
  });

  $("dictate-btn-new-prayer").addEventListener("click", () => {
    const text = dictateText.value;
    if (!text) { toast("Write or dictate some text first."); return; }
    renderNew(text);
  });
}

// ---------- You (settings) ----------
async function renderYou() {
  show("you-view");
  setNav("you");
  $("you-view").innerHTML = `
    <div class="greeting"><span class="eyebrow">You</span><h2>Settings</h2></div>
    <p class="meta" style="text-align:center">Loading…</p>`;
  let me;
  try { me = await api("/api/me"); }
  catch (e) { $("you-view").innerHTML = `<p class="meta">${esc(e.message)}</p>`; return; }
  const backupCard = `
    <div class="card">
      <div class="section-title">Backups</div>
      <p class="meta">Your prayers are plain Markdown files. Download them anytime${APP_CONFIG.google_login ? ", or send a backup to your own Google Drive — the app can only see backup files it created" : ""}.</p>
      <div class="row" style="margin-top:12px">
        ${APP_CONFIG.google_login ? `<a class="drive-btn" href="/api/backup/drive">Back up to Google Drive</a>` : ""}
        <a class="drive-btn" href="/api/export.zip">Download .zip</a>
      </div>
    </div>`;
  if (!me.admin) {
    $("you-view").innerHTML = `
      <div class="greeting"><span class="eyebrow">You</span><h2>${esc(me.name || "Your account")}</h2></div>
      <div class="card">
        <div class="section-title">Account</div>
        <p class="meta">Signed in with Google${me.email ? " as " + esc(me.email) : ""}. Your prayer journal is private to you.</p>
      </div>` + backupCard;
    return;
  }
  let s;
  try { s = await api("/api/settings"); }
  catch (e) { $("you-view").innerHTML = `<p class="meta">${esc(e.message)}</p>`; return; }
  const m = s.morning;
  const defs = s.prompt_defaults || { system: "", answer: "" };
  const cur = s.prompts || { system: "", answer: "" };
  const sysText = (cur.system && cur.system.trim()) ? cur.system : defs.system;
  const ansText = (cur.answer && cur.answer.trim()) ? cur.answer : defs.answer;
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
      <label>ntfy server URL</label>
      <input id="mp-server" value="${esc(m.ntfy_server || s.ntfy_server || "")}" placeholder="https://ntfy.salife.us">
      <label>ntfy topic</label>
      <input id="mp-topic" value="${esc(m.ntfy_topic)}" placeholder="e.g. prayervault">
      <p class="meta">Set your server and a topic (e.g. prayervault). You can also paste a full URL like https://ntfy.salife.us/prayervault into the topic box. Subscribe to the same topic in the ntfy app — anyone who knows it can read it, so keep it private.</p>
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
    </div>
    <div class="card">
      <div class="section-title">AI prompts</div>
      <p class="meta">These instructions steer your local model's voice. They start as the built-in Reformed (Westminster) prompts — edit them to change the tone, or use "Reset to built-in" to restore the originals. The models must still return the same JSON, so keep the parts describing the JSON keys.</p>
      <label>Prayer &amp; request generation</label>
      <textarea id="pr-system" spellcheck="false" style="min-height:220px;font-size:.88rem;line-height:1.5">${esc(sysText)}</textarea>
      <label>Ask (Scripture Q&amp;A)</label>
      <textarea id="pr-answer" spellcheck="false" style="min-height:220px;font-size:.88rem;line-height:1.5">${esc(ansText)}</textarea>
      <div class="error-msg" id="pr-error"></div>
      <div class="row" style="margin-top:12px">
        <button class="primary" id="pr-save">Save prompts</button>
        <button id="pr-reset">Reset to built-in</button>
        <span id="pr-status" class="meta"></span>
      </div>
    </div>` + backupCard;
  const gather = () => ({ morning: {
    enabled: $("mp-enabled").checked,
    delivery: $("mp-delivery").value,
    ntfy_server: $("mp-server").value.trim(),
    ntfy_topic: $("mp-topic").value.trim(),
    hour: parseInt($("mp-hour").value, 10),
    minute: parseInt($("mp-min").value, 10),
  }});
  $("mp-save").addEventListener("click", async () => {
    $("mp-error").textContent = ""; $("mp-status").textContent = "";
    try {
      await api("/api/settings", { method: "POST", body: JSON.stringify(gather()) });
      $("mp-status").textContent = "Saved.";
    } catch (e) { $("mp-error").textContent = e.message; }
  });
  $("mp-test").addEventListener("click", async () => {
    $("mp-error").textContent = ""; $("mp-status").textContent = "";
    const btn = $("mp-test"); btn.disabled = true;
    try {
      await api("/api/settings", { method: "POST", body: JSON.stringify(gather()) });
      await api("/api/notify/test", { method: "POST", body: JSON.stringify({}) });
      $("mp-status").textContent = "Test push sent — check your ntfy app.";
    } catch (e) { $("mp-error").textContent = e.message; }
    btn.disabled = false;
  });
  const savePrompts = (system, answer) =>
    api("/api/settings", { method: "POST", body: JSON.stringify({ prompts: { system, answer } }) });
  $("pr-save").addEventListener("click", async () => {
    $("pr-error").textContent = ""; $("pr-status").textContent = "";
    try {
      const sv = $("pr-system").value, av = $("pr-answer").value;
      await savePrompts(
        sv.trim() === defs.system.trim() ? "" : sv,
        av.trim() === defs.answer.trim() ? "" : av);
      $("pr-status").textContent = "Prompts saved.";
    } catch (e) { $("pr-error").textContent = e.message; }
  });
  $("pr-reset").addEventListener("click", async () => {
    $("pr-error").textContent = ""; $("pr-status").textContent = "";
    try {
      await savePrompts("", "");
      $("pr-system").value = defs.system;
      $("pr-answer").value = defs.answer;
      $("pr-status").textContent = "Reset to built-in.";
    } catch (e) { $("pr-error").textContent = e.message; }
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
function renderNew(initialText = "") {
  if (typeof initialText !== "string") initialText = "";
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
      <textarea id="np-text" placeholder="Pour it out here… or press Record and speak">${esc(initialText)}</textarea>
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
      $("np-error").textContent = "Microphone needs a secure connection — use the https:// address.";
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
        micBtn.innerHTML = '<span class="spinner"></span> Transcribing…';
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
    const me = await api("/api/me");
    checkAdminAccess(me);
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
    else if (n === "dictate") renderDictate();
    else if (n === "you") renderYou();
    else { filterStatus = "ongoing"; renderList(); }
  }));

function toast(msg) {
  const t = document.createElement("div");
  t.className = "toast";
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 5000);
}

let APP_CONFIG = { google_login: false };
fetch("/api/app-config").then((r) => r.json()).then((c) => {
  APP_CONFIG = c;
  $("google-signin").classList.toggle("hidden", !c.google_login);
}).catch(() => {});

const _params = new URLSearchParams(location.search);
if (_params.has("login") || _params.has("backup")) {
  if (_params.get("login") === "failed") $("login-error").textContent = "Google sign-in didn't complete. Please try again.";
  if (_params.get("backup") === "ok") toast("Backup saved to your Google Drive.");
  if (_params.get("backup") === "failed") toast("Google Drive backup failed — please try again.");
  history.replaceState(null, "", location.pathname);
}

function checkAdminAccess(me) {
  const dictateNav = document.querySelector('.nav-item[data-nav="dictate"]');
  if (dictateNav) {
    dictateNav.classList.toggle("hidden", !me || !me.admin);
  }
}

api("/api/me").then((me) => {
  checkAdminAccess(me);
  renderToday();
}).catch(() => {
  checkAdminAccess(null);
  show("login-view");
});

// ---- PWA: install support ----
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}
