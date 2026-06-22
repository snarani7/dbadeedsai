/**
 * dbadeeds.ai — Main JavaScript
 * SSE streaming · AJAX helpers · Toast · Markdown renderer
 */

/* ── Toast notifications ─────────────────────────────── */
const Toast = {
  show(msg, type = "info") {
    const el = document.createElement("div");
    el.className = `toast toast-${type}`;
    el.textContent = msg;
    document.getElementById("toast-container").appendChild(el);
    setTimeout(() => el.remove(), 3500);
  },
  success: (m) => Toast.show(m, "success"),
  error:   (m) => Toast.show(m, "error"),
  info:    (m) => Toast.show(m, "info"),
};


/* ── Simple markdown → HTML (subset) ────────────────── */
const MD = {
  render(text) {
    return text
      // code blocks
      .replace(/```[\w]*\n?([\s\S]*?)```/g, (_,c) =>
        `<pre><code>${escHtml(c.trim())}</code></pre>`)
      // inline code
      .replace(/`([^`]+)`/g, (_,c) => `<code>${escHtml(c)}</code>`)
      // headers
      .replace(/^### (.+)$/gm, "<h3>$1</h3>")
      .replace(/^## (.+)$/gm,  "<h2>$1</h2>")
      .replace(/^# (.+)$/gm,   "<h2>$1</h2>")
      // bold
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      // italic
      .replace(/\*(.+?)\*/g, "<em>$1</em>")
      // unordered list
      .replace(/^\s*[-•] (.+)$/gm, "<li>$1</li>")
      .replace(/(<li>.*<\/li>)/gs, "<ul>$1</ul>")
      // horizontal rule
      .replace(/^---+$/gm, "<hr>")
      // newlines → <br>
      .replace(/\n{2,}/g, "<br><br>")
      .replace(/\n/g, "<br>");
  }
};

function escHtml(t) {
  return t.replace(/&/g,"&amp;").replace(/</g,"&lt;")
          .replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}


/* ── AJAX helpers ────────────────────────────────────── */
async function postJSON(url, data) {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  return resp.json();
}

async function getJSON(url) {
  const resp = await fetch(url);
  return resp.json();
}


/* ═══════════════════════════════════════════════════════
   AI ASSISTANT
   ═══════════════════════════════════════════════════════ */
const AIAssistant = {
  dbType: window.AI_DB_TYPE || "oracle",
  isStreaming: false,
  currentBubble: null,
  currentText: "",

  init() {
    this.dbType = document.getElementById("ai-db-type")?.value || "oracle";
    this._bindDbCards();
    this._bindSendForm();
    this._bindSuggestions();
    this._bindRcaButtons();
    this._bindClear();
    this.scrollToBottom();
  },

  _bindDbCards() {
    document.querySelectorAll(".db-card").forEach(card => {
      card.addEventListener("click", async () => {
        const db = card.dataset.db;
        await postJSON("/ai-assistant/switch-db", { db_type: db });
        window.location.reload();
      });
    });
  },

  _bindSendForm() {
    const form  = document.getElementById("chat-form");
    const input = document.getElementById("chat-input");
    if (!form) return;
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const msg = input.value.trim();
      if (!msg || this.isStreaming) return;
      input.value = "";
      this.sendMessage(msg);
    });
  },

  _bindSuggestions() {
    document.querySelectorAll(".suggest-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const msg = btn.dataset.prompt;
        if (msg && !this.isStreaming) this.sendMessage(msg);
      });
    });
  },

  _bindRcaButtons() {
    document.querySelectorAll(".rca-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const msg = btn.dataset.prompt;
        if (msg && !this.isStreaming) this.sendMessage(msg);
      });
    });
    // Custom RCA
    const runBtn = document.getElementById("rca-run-btn");
    if (runBtn) {
      runBtn.addEventListener("click", () => {
        const txt = document.getElementById("rca-custom-input")?.value.trim();
        if (!txt) { Toast.error("Paste an error message first."); return; }
        const prompt = `Perform a thorough Root Cause Analysis for this ${this.dbType} database issue:\n\n${txt}\n\nStructure as:\n## 🔍 Likely Root Cause\n## 📋 Evidence to Confirm\n## 🚑 Immediate Actions\n## 🛡️ Preventive Measures\n## 🔧 SQL Diagnostics`;
        if (!this.isStreaming) this.sendMessage(prompt, txt.substring(0, 80) + "…");
      });
    }
  },

  _bindClear() {
    document.getElementById("clear-btn")?.addEventListener("click", async () => {
      await postJSON("/ai-assistant/clear", { db_type: this.dbType });
      document.getElementById("chat-messages").innerHTML = "";
      Toast.info("Chat history cleared.");
    });
  },

  async sendMessage(prompt, displayText = null) {
    // 1. Add user bubble
    this._addBubble("user", displayText || prompt);
    // 2. Post to record in session history
    await postJSON("/ai-assistant/send", { message: prompt });
    // 3. Stream response
    this._startStream(prompt);
  },

  _startStream(prompt) {
    this.isStreaming = true;
    this._setSendDisabled(true);
    this.currentText = "";
    this.currentBubble = this._addBubble("assistant", "");
    const indicator = document.createElement("span");
    indicator.className = "typing-indicator";
    indicator.textContent = "▌";
    this.currentBubble.appendChild(indicator);

    const url = `/ai-assistant/stream?message=${encodeURIComponent(prompt)}&db_type=${this.dbType}`;
    const es  = new EventSource(url);

    es.onmessage = (e) => {
      if (e.data === "[DONE]") {
        es.close();
        indicator.remove();
        this.currentBubble.innerHTML = MD.render(this.currentText);
        this.isStreaming = false;
        this._setSendDisabled(false);
        this.scrollToBottom();
        return;
      }
      const token = e.data.replace(/\\n/g, "\n");
      this.currentText += token;
      indicator.textContent = this.currentText.slice(-80) + " ▌";
      this.scrollToBottom();
    };

    es.onerror = () => {
      es.close();
      indicator.remove();
      if (this.currentText) {
        this.currentBubble.innerHTML = MD.render(this.currentText);
      } else {
        this.currentBubble.innerHTML = "⚠️ Connection error. Please try again.";
      }
      this.isStreaming = false;
      this._setSendDisabled(false);
    };
  },

  _addBubble(role, text) {
    const container = document.getElementById("chat-messages");
    const bubble    = document.createElement("div");
    bubble.className = `chat-bubble ${role}`;
    if (text) bubble.innerHTML = role === "assistant" ? MD.render(text) : escHtml(text);
    container.appendChild(bubble);
    this.scrollToBottom();
    return bubble;
  },

  _setSendDisabled(disabled) {
    const btn   = document.querySelector(".send-btn");
    const input = document.getElementById("chat-input");
    if (btn)   btn.disabled   = disabled;
    if (input) input.disabled = disabled;
  },

  scrollToBottom() {
    const c = document.getElementById("chat-messages");
    if (c) c.scrollTop = c.scrollHeight;
  },
};


/* ═══════════════════════════════════════════════════════
   DB EXPLORER — SQL Runner
   ═══════════════════════════════════════════════════════ */
const DBExplorer = {
  init() {
    document.getElementById("run-sql-btn")?.addEventListener("click", () => this.runSQL());
  },

  async runSQL() {
    const sql    = document.getElementById("sql-editor")?.value.trim();
    const dbType = document.getElementById("db-type-select")?.value || "oracle";
    if (!sql) { Toast.error("Enter a SQL query."); return; }

    const resultsDiv = document.getElementById("query-results");
    resultsDiv.innerHTML = `<div class="typing-indicator">Running query… <span class="spinner"></span></div>`;

    const data = await postJSON("/db-explorer/run", { sql, db_type: dbType });

    if (data.error) {
      resultsDiv.innerHTML = `<div class="alert alert-error">❌ ${escHtml(data.error)}</div>`;
      return;
    }
    if (data.message) {
      resultsDiv.innerHTML = `<div class="alert alert-success">✅ ${escHtml(data.message)}</div>`;
      return;
    }

    const cols = data.columns;
    const rows = data.rows;
    let html = `<div class="data-table-wrap"><table class="data-table"><thead><tr>`;
    cols.forEach(c => { html += `<th>${escHtml(String(c))}</th>`; });
    html += `</tr></thead><tbody>`;
    rows.forEach(row => {
      html += "<tr>";
      cols.forEach(c => {
        const v = row[c] ?? "";
        html += `<td>${escHtml(String(v))}</td>`;
      });
      html += "</tr>";
    });
    html += `</tbody></table></div>`;
    html += `<div style="font-size:11px;color:#9CA3AF;margin-top:6px">${rows.length} row(s)</div>`;
    resultsDiv.innerHTML = html;
  },
};


/* ═══════════════════════════════════════════════════════
   DB CONNECTIONS
   ═══════════════════════════════════════════════════════ */
const DBConnections = {
  init() {
    document.querySelectorAll(".activate-btn").forEach(btn => {
      btn.addEventListener("click", async () => {
        const id = btn.dataset.id;
        await postJSON(`/db-connections/activate/${id}`, {});
        Toast.success("Connection activated.");
        setTimeout(() => location.reload(), 600);
      });
    });

    document.getElementById("test-conn-btn")?.addEventListener("click", async () => {
      const dbType = document.getElementById("add-db-type")?.value || "oracle";
      const connStr = document.getElementById("add-conn-str")?.value.trim();
      if (!connStr) { Toast.error("Enter a connection string first."); return; }
      const r = await postJSON("/db-connections/test", {
        db_type: dbType, connection_string: connStr
      });
      r.ok ? Toast.success(r.message) : Toast.error(r.message);
    });
  },
};


/* ═══════════════════════════════════════════════════════
   DBA PLAYBOOKS — SSE progress
   ═══════════════════════════════════════════════════════ */
const Playbooks = {
  init() {
    document.querySelectorAll(".run-playbook-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const name   = btn.dataset.name;
        const dbType = document.getElementById("pb-db-type")?.value || "oracle";
        this.runPlaybook(name, dbType);
      });
    });
  },

  runPlaybook(name, dbType) {
    const output = document.getElementById("playbook-output");
    if (!output) return;
    output.innerHTML = "";

    const url = `/playbooks/run/stream?name=${encodeURIComponent(name)}&db_type=${dbType}`;
    const es  = new EventSource(url);
    let currentStep = null;

    es.onmessage = (e) => {
      if (e.data === "[DONE]") { es.close(); return; }

      if (e.data.startsWith("STEP:")) {
        const parts = e.data.split(":");
        const stepNum  = parts[1];
        const stepName = parts.slice(2).join(":");
        currentStep = document.createElement("div");
        currentStep.className = "card";
        currentStep.innerHTML = `<div class="card-title">Step ${stepNum}: ${escHtml(stepName)}</div><div class="step-result"></div>`;
        output.appendChild(currentStep);
      } else if (e.data.startsWith("RESULT:") && currentStep) {
        const result = e.data.replace("RESULT:", "").replace(/~NL~/g, "\n");
        currentStep.querySelector(".step-result").innerHTML =
          `<pre style="background:#0F1E3C;color:#E5E7EB;border-radius:6px;padding:10px;font-size:12px;overflow-x:auto">${escHtml(result)}</pre>`;
      } else if (e.data.startsWith("ERROR:") && currentStep) {
        const err = e.data.replace("ERROR:", "");
        currentStep.querySelector(".step-result").innerHTML =
          `<div class="alert alert-error">❌ ${escHtml(err)}</div>`;
      }
    };
  },
};


/* ═══════════════════════════════════════════════════════
   ASK DBA
   ═══════════════════════════════════════════════════════ */
const AskDBA = {
  isStreaming: false,

  init() {
    document.getElementById("discover-btn")?.addEventListener("click", () => this.discover());
    document.getElementById("connect-btn")?.addEventListener("click", () => this.connect());
    document.getElementById("disconnect-btn")?.addEventListener("click", () => this.disconnect());
    document.getElementById("askdba-send-btn")?.addEventListener("click", () => this.sendMessage());
    document.getElementById("askdba-clear-btn")?.addEventListener("click", () => this.clearChat());

    document.getElementById("askdba-input")?.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        if (!this.isStreaming) this.sendMessage();
      }
    });
  },

  async discover() {
    const q = document.getElementById("askdba-question")?.value.trim();
    if (!q) { Toast.error("Enter a question first."); return; }
    const r = await postJSON("/ask-dba/discover", { question: q });
    if (r.error) { Toast.error(r.error); return; }

    // Show connection form
    document.getElementById("db-infoel").innerHTML = `
      <div class="card" style="border-left:4px solid ${r.db_type==='oracle'?'#F97316':'#3B82F6'}">
        <div class="card-title">Found: ${escHtml(r.project)}</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:13px;margin-bottom:14px">
          <div>🏠 <strong>Host:</strong> ${escHtml(r.host)}</div>
          <div>🔌 <strong>Port:</strong> ${escHtml(r.port)}</div>
          <div>🗄️ <strong>DB:</strong> ${escHtml(r.db_name||r.service||'—')}</div>
          <div>👤 <strong>User:</strong> ${escHtml(r.db_user)}</div>
        </div>
        <input type="hidden" id="db-info-project" value="${escHtml(r.project)}">
        <input type="hidden" id="db-info-db-type" value="${escHtml(r.db_type)}">
        <input type="hidden" id="db-info-host" value="${escHtml(r.host)}">
        <input type="hidden" id="db-info-port" value="${escHtml(r.port)}">
        <input type="hidden" id="db-info-db-name" value="${escHtml(r.db_name)}">
        <input type="hidden" id="db-info-service" value="${escHtml(r.service)}">
        <input type="hidden" id="db-info-user" value="${escHtml(r.db_user)}">
        <input type="hidden" id="db-info-question" value="${escHtml(r.question)}">
        <div class="form-group">
          <label class="form-label">Database Password</label>
          <input type="password" id="askdba-password" class="form-input" placeholder="Enter database password">
        </div>
        <button class="btn btn-primary" id="connect-btn" onclick="AskDBA.connect()">Connect →</button>
      </div>`;
  },

  async connect() {
    const payload = {
      project:  document.getElementById("db-info-project")?.value,
      db_type:  document.getElementById("db-info-db-type")?.value,
      host:     document.getElementById("db-info-host")?.value,
      port:     document.getElementById("db-info-port")?.value,
      db_name:  document.getElementById("db-info-db-name")?.value,
      service:  document.getElementById("db-info-service")?.value,
      db_user:  document.getElementById("db-info-user")?.value,
      password: document.getElementById("askdba-password")?.value,
    };
    if (!payload.password) { Toast.error("Password required."); return; }
    const r = await postJSON("/ask-dba/connect", payload);
    if (r.error) { Toast.error(r.error); return; }
    Toast.success("Connected!");
    setTimeout(() => location.reload(), 600);
  },

  async disconnect() {
    await postJSON("/ask-dba/disconnect", {});
    location.reload();
  },

  async clearChat() {
    await postJSON("/ask-dba/clear", {});
    document.getElementById("askdba-messages").innerHTML = "";
  },

  sendMessage() {
    const input  = document.getElementById("askdba-input");
    const prompt = input?.value.trim();
    if (!prompt || this.isStreaming) return;
    input.value = "";
    this._addBubble("user", prompt);
    this._stream(prompt);
  },

  _stream(prompt) {
    this.isStreaming = true;
    const bubble = this._addBubble("assistant", "");
    const url = `/ask-dba/stream?message=${encodeURIComponent(prompt)}`;
    const es  = new EventSource(url);
    let text  = "";
    const indicator = document.createElement("span");
    indicator.textContent = "▌";
    bubble.appendChild(indicator);

    es.onmessage = (e) => {
      if (e.data === "[DONE]") {
        es.close();
        indicator.remove();
        bubble.innerHTML = MD.render(text);
        this.isStreaming = false;
        this._scrollBottom();
        return;
      }
      text += e.data.replace(/\\n/g, "\n");
      indicator.textContent = text.slice(-80) + " ▌";
      this._scrollBottom();
    };

    es.onerror = () => {
      es.close();
      indicator.remove();
      bubble.innerHTML = text ? MD.render(text) : "⚠️ Stream error.";
      this.isStreaming = false;
    };
  },

  _addBubble(role, text) {
    const c = document.getElementById("askdba-messages");
    const b = document.createElement("div");
    b.className = `chat-bubble ${role}`;
    b.innerHTML = role === "user" ? escHtml(text) : (text ? MD.render(text) : "");
    c.appendChild(b);
    this._scrollBottom();
    return b;
  },

  _scrollBottom() {
    const c = document.getElementById("askdba-messages");
    if (c) c.scrollTop = c.scrollHeight;
  },
};


/* ── Auto-dismiss flash messages ─────────────────────── */
document.querySelectorAll(".alert[data-auto-dismiss]").forEach(el => {
  setTimeout(() => el.remove(), 4000);
});

/* ── Init page-specific modules ──────────────────────── */
document.addEventListener("DOMContentLoaded", () => {
  const page = document.body.dataset.page;
  if (page === "ai-assistant")  AIAssistant.init();
  if (page === "db-explorer")   DBExplorer.init();
  if (page === "db-connections") DBConnections.init();
  if (page === "playbooks")     Playbooks.init();
  if (page === "ask-dba")       AskDBA.init();
});
