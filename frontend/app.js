const $ = (s) => document.querySelector(s);
const messages = $("#messages");
const trace = $("#trace");
const artifacts = $("#artifacts");

let mermaidReady = false;
try { mermaid.initialize({ startOnLoad: false, theme: "neutral" }); mermaidReady = true; } catch (e) {}

// ---------- helpers ----------
function mdInline(t) {
  return t
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\n/g, "<br/>");
}
function addMsg(text, who) {
  const el = document.createElement("div");
  el.className = `msg ${who}`;
  el.innerHTML = who === "bot" ? mdInline(text) : text.replace(/</g, "&lt;");
  messages.appendChild(el);
  messages.scrollTop = messages.scrollHeight;
  return el;
}

// ---------- trace rendering ----------
function renderTrace(steps) {
  trace.innerHTML = "";
  if (!steps.length) { trace.innerHTML = '<p class="muted">No tool calls.</p>'; return; }
  for (const s of steps) {
    const row = document.createElement("div");
    row.className = "step";
    const ok = s.ok !== false;
    row.innerHTML = `
      <div class="step-head">
        <span class="agent-pill agent-${s.agent}">${s.agent}</span>
        <span class="step-tool">${s.tool}(${shortArgs(s.args)})</span>
        <span class="${ok ? "step-ok" : "step-err"}">${ok ? "✓" : "✕"}</span>
      </div>
      <div class="step-body"><pre>${escapeJson(s.result)}</pre></div>`;
    row.querySelector(".step-head").onclick = () => row.classList.toggle("open");
    trace.appendChild(row);
  }
}
function shortArgs(a) {
  if (!a || !Object.keys(a).length) return "";
  return Object.entries(a).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", ").slice(0, 60);
}
function escapeJson(o) {
  return JSON.stringify(o, null, 2).replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// ---------- artifacts: root cause + HITL ticket ----------
function renderArtifacts(data) {
  artifacts.innerHTML = "";
  const rc = data.root_cause;
  if (rc && rc.hypotheses && rc.hypotheses.length) {
    const h = rc.hypotheses[0];
    const card = document.createElement("div");
    card.className = "card";
    card.innerHTML = `
      <h3>Root cause</h3>
      <div class="rc-cause">${h.root_cause}</div>
      <div class="rc-conf">confidence ${Math.round(h.confidence * 100)}% · blast radius: ${h.blast_radius || "n/a"}</div>
      <ul class="rc-ev">${h.evidence.map((e) => `<li>${e}</li>`).join("")}</ul>`;
    artifacts.appendChild(card);
  }
  if (data.proposed_ticket) renderTicket(data.proposed_ticket);
}

function renderTicket(t) {
  const card = document.createElement("div");
  card.className = "card card-ticket";
  card.innerHTML = `
    <h3>Proposed ServiceNow incident</h3>
    <div class="tk-row"><b>${t.short_description}</b></div>
    <div class="tk-row">priority: ${t.priority} · group: ${t.assignment_group}</div>
    <div class="tk-row">CI: ${t.cmdb_ci || "n/a"}</div>
    <div class="hitl-note">Requires approval before this incident is filed.</div>
    <div class="tk-actions">
      <button class="btn btn-ok" id="approveBtn">Approve &amp; create</button>
      <button class="btn btn-ghost" id="rejectBtn">Reject</button>
    </div>`;
  artifacts.appendChild(card);
  card.querySelector("#approveBtn").onclick = async () => {
    const res = await postJSON("/api/approve-ticket", { ticket: t });
    const c = res.created;
    card.querySelector(".tk-actions").innerHTML =
      `<span class="tk-created">✓ Created ${c.number} (${c.state})</span>`;
    card.querySelector(".hitl-note").remove();
  };
  card.querySelector("#rejectBtn").onclick = () => card.remove();
}

// ---------- networking ----------
async function postJSON(url, body) {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  return r.json();
}

async function send(text) {
  addMsg(text, "user");
  const thinking = addMsg("running agents...", "bot");
  thinking.classList.add("thinking");
  try {
    const data = await postJSON("/api/chat", { message: text });
    thinking.remove();
    addMsg(data.answer || "(no answer)", "bot");
    renderTrace(data.steps || []);
    renderArtifacts(data);
  } catch (e) {
    thinking.remove();
    addMsg("Error: " + e.message, "bot");
  }
}

// ---------- scenario toggle ----------
async function refreshScenario() {
  const r = await fetch("/api/sim/scenario").then((x) => x.json());
  const badge = $("#scenarioBadge");
  if (r.incident_active) {
    badge.textContent = "P1 outage active (checkout)";
    badge.className = "badge badge-p1";
    $("#injectBtn").hidden = true; $("#resolveBtn").hidden = false;
  } else {
    badge.textContent = "all systems nominal";
    badge.className = "badge badge-ok";
    $("#injectBtn").hidden = false; $("#resolveBtn").hidden = true;
  }
}
$("#injectBtn").onclick = async () => { await postJSON("/api/sim/incident", { active: true }); refreshScenario(); };
$("#resolveBtn").onclick = async () => { await postJSON("/api/sim/incident", { active: false }); refreshScenario(); };

// ---------- graph modal ----------
$("#graphBtn").onclick = async () => {
  $("#graphModal").hidden = false;
  const el = $("#graphContent");
  el.textContent = "loading...";
  const { mermaid: src } = await fetch("/api/graph").then((x) => x.json());
  if (mermaidReady) {
    try {
      const { svg } = await mermaid.render("g" + Date.now(), src);
      el.innerHTML = svg; return;
    } catch (e) {}
  }
  el.innerHTML = `<pre style="color:#111">${src.replace(/</g, "&lt;")}</pre>`;
};
$("#graphClose").onclick = () => { $("#graphModal").hidden = true; };

// ---------- wire up ----------
$("#composer").onsubmit = (e) => {
  e.preventDefault();
  const v = $("#input").value.trim();
  if (!v) return;
  $("#input").value = "";
  send(v);
};
document.querySelectorAll(".chip").forEach((c) => (c.onclick = () => send(c.dataset.q)));

addMsg("NetOps Copilot. Ask a network question (connectivity, VIP, or pool health), or give it a P1 outage to run the root-cause pipeline across the firewall, F5, AKS and Splunk. Pick a chip below, or hit Inject P1 outage first.", "bot");
refreshScenario();
