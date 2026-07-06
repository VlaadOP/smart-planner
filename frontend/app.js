/* Smart Planner — frontend minimal (vanilla JS + FullCalendar). */
"use strict";

const CATEGORY_COLORS = {
  work: "#4e79a7",
  meeting: "#b07aa1",
  sleep: "#6b7b95",
  meal: "#e8a838",
  break: "#76b7b2",
  sport: "#e15759",
  personal: "#59a14f",
  other: "#9c9c9c",
};

let calendar = null;
let sessionId = null;

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res;
}

function setStatus(text) {
  $("status-line").textContent = text;
}

function statusLabel(view) {
  const map = {
    OPTIMAL: "Planning optimal",
    FEASIBLE: "Planning faisable",
    INFEASIBLE: "⚠️ Contraintes en conflit — dernier planning valide affiché",
    UNKNOWN: "En attente de contraintes…",
    TOO_LARGE: "⚠️ Modèle trop volumineux",
  };
  return (map[view.solver_status] || view.solver_status) +
    ` · session ${view.session_id} · ${view.horizon_start} → ${view.horizon_end}`;
}

/* ---------- calendrier ---------- */

function initCalendar(view) {
  calendar = new FullCalendar.Calendar($("calendar"), {
    initialView: "timeGridWeek",
    initialDate: view.horizon_start,
    locale: "fr",
    firstDay: 1,
    allDaySlot: false,
    slotDuration: "00:15:00",
    slotLabelInterval: "01:00",
    snapDuration: "00:15:00",
    nowIndicator: true,
    height: "100%",
    headerToolbar: { left: "prev,next today", center: "title", right: "dayGridMonth,timeGridWeek,timeGridDay" },
    validRange: { start: view.horizon_start, end: addDays(view.horizon_end, 1) },
    events: [],
    eventTimeFormat: { hour: "2-digit", minute: "2-digit", hour12: false },
  });
  calendar.render();
}

function addDays(iso, n) {
  const d = new Date(iso + "T00:00:00");
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
}

function renderSchedule(schedule, diff) {
  if (!calendar) return;
  const added = new Set((diff && diff.added) || []);
  const moved = new Set((diff && diff.moved) || []);
  calendar.removeAllEvents();
  if (!schedule || !schedule.blocks) return;
  for (const b of schedule.blocks) {
    const classNames = [];
    if (b.is_default) classNames.push("evt-default");
    if (added.has(b.key)) classNames.push("evt-new");
    if (moved.has(b.key)) classNames.push("evt-moved");
    calendar.addEvent({
      id: b.key,
      title: b.label,
      start: b.start,
      end: b.end,
      backgroundColor: CATEGORY_COLORS[b.category] || CATEGORY_COLORS.other,
      borderColor: "transparent",
      classNames,
    });
  }
}

/* ---------- chat ---------- */

function appendMessage(who, text, pending = false) {
  const div = document.createElement("div");
  div.className = `msg ${who}` + (pending ? " pending" : "");
  div.textContent = text;
  $("chat-messages").appendChild(div);
  $("chat-messages").scrollTop = $("chat-messages").scrollHeight;
  return div;
}

function renderHistory(history) {
  $("chat-messages").innerHTML = "";
  for (const turn of history || []) appendMessage(turn.who, turn.text);
}

/* ---------- contraintes ---------- */

function renderConstraints(constraints) {
  const ul = $("constraint-list");
  ul.innerHTML = "";
  for (const c of constraints || []) {
    const li = document.createElement("li");
    if (c.is_default) li.classList.add("default");
    const badges = [];
    if (c.is_default) badges.push('<span class="badge default">défaut</span>');
    badges.push(`<span class="badge ${c.strength === "hard" ? "hard" : ""}">${c.strength === "hard" ? "dur" : "souple " + c.weight}</span>`);
    li.innerHTML = `${badges.join("")}<span class="lbl" title="${escapeHtml(c.summary)}">${escapeHtml(c.label)}</span>` +
      `<button class="del" title="Supprimer">✕</button>`;
    li.querySelector(".del").addEventListener("click", () => deleteConstraint(c.id, c.label));
    ul.appendChild(li);
  }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

/* ---------- bannière de conflit ---------- */

function renderConflict(report) {
  const banner = $("conflict-banner");
  if (!report || (!report.explanation && !(report.proposals || []).length)) {
    banner.classList.add("hidden");
    return;
  }
  banner.classList.remove("hidden");
  $("conflict-text").textContent = report.explanation;
  const box = $("conflict-proposals");
  box.innerHTML = "";
  (report.proposals || []).forEach((p, i) => {
    const btn = document.createElement("button");
    btn.textContent = `→ ${p.description}`;
    btn.addEventListener("click", () => acceptRelaxation(i, btn));
    box.appendChild(btn);
  });
}

/* ---------- actions ---------- */

function applyView(view, diff) {
  setStatus(statusLabel(view));
  renderSchedule(view.schedule, diff);
  renderConstraints(view.constraints);
  renderConflict(view.infeasibility);
}

async function sendMessage(text) {
  appendMessage("user", text);
  const pending = appendMessage("assistant", "…réflexion en cours…", true);
  $("chat-send").disabled = true;
  try {
    const res = await api(`/api/sessions/${sessionId}/chat`, {
      method: "POST",
      body: JSON.stringify({ message: text }),
    });
    const data = await res.json();
    pending.remove();
    appendMessage("assistant", data.assistant_message);
    applyView({ ...data, session_id: sessionId, horizon_start: window._hzStart, horizon_end: window._hzEnd }, data.diff);
  } catch (err) {
    pending.remove();
    appendMessage("assistant", `Erreur : ${err.message}`);
  } finally {
    $("chat-send").disabled = false;
    $("chat-input").focus();
  }
}

async function deleteConstraint(id, label) {
  if (!confirm(`Supprimer la contrainte « ${label} » ?`)) return;
  try {
    const res = await api(`/api/sessions/${sessionId}/constraints/${id}`, { method: "DELETE" });
    const data = await res.json();
    appendMessage("assistant", data.assistant_message);
    applyView({ ...data, session_id: sessionId, horizon_start: window._hzStart, horizon_end: window._hzEnd }, data.diff);
  } catch (err) {
    alert(err.message);
  }
}

async function acceptRelaxation(index, btn) {
  btn.disabled = true;
  try {
    const res = await api(`/api/sessions/${sessionId}/relaxations/${index}/accept`, { method: "POST" });
    const data = await res.json();
    appendMessage("assistant", data.assistant_message);
    applyView({ ...data, session_id: sessionId, horizon_start: window._hzStart, horizon_end: window._hzEnd }, data.diff);
  } catch (err) {
    alert(err.message);
    btn.disabled = false;
  }
}

async function exportIcs() {
  try {
    const res = await api(`/api/sessions/${sessionId}/export`, { method: "POST" });
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "smart-planner.ics";
    a.click();
    URL.revokeObjectURL(url);
    setStatus("Planning validé et exporté en .ics ✔");
  } catch (err) {
    alert(`Export impossible : ${err.message}`);
  }
}

/* ---------- session ---------- */

async function loadOrCreateSession(forceNew = false) {
  let view = null;
  const stored = localStorage.getItem("smart-planner-session");
  if (stored && !forceNew) {
    try {
      view = await (await api(`/api/sessions/${stored}`)).json();
    } catch (_) { /* session disparue */ }
  }
  if (!view) {
    view = await (await api("/api/sessions", { method: "POST", body: "{}" })).json();
    localStorage.setItem("smart-planner-session", view.session_id);
  }
  sessionId = view.session_id;
  window._hzStart = view.horizon_start;
  window._hzEnd = view.horizon_end;
  if (calendar) { calendar.destroy(); calendar = null; }
  initCalendar(view);
  renderHistory(view.chat_history);
  if (!(view.chat_history || []).length) {
    appendMessage(
      "assistant",
      "Bonjour ! Décrivez vos contraintes (« réunion fixe mardi à 14h », « 1h de pause par jour », " +
      "« 10h de sommeil »...) et je construis votre planning du mois. Des défauts réalistes " +
      "(sommeil, repas...) sont déjà en place — dites-le-moi pour les changer."
    );
  }
  applyView(view, null);
}

/* ---------- bootstrap ---------- */

document.addEventListener("DOMContentLoaded", () => {
  $("chat-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const text = $("chat-input").value.trim();
    if (!text) return;
    $("chat-input").value = "";
    sendMessage(text);
  });
  $("btn-export").addEventListener("click", exportIcs);
  $("btn-new-session").addEventListener("click", () => {
    if (confirm("Repartir d'une session vierge ?")) loadOrCreateSession(true);
  });
  loadOrCreateSession().catch((err) => setStatus(`Erreur d'initialisation : ${err.message}`));
});
