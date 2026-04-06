const state = {
  latest: null,
  pollHandle: null,
};

const els = {
  metrics: document.getElementById("metrics"),
  agentCount: document.getElementById("agent-count"),
  messageCount: document.getElementById("message-count"),
  agentList: document.getElementById("agent-list"),
  messageFeed: document.getElementById("message-feed"),
  workList: document.getElementById("work-list"),
  decisionList: document.getElementById("decision-list"),
  objectiveLine: document.getElementById("objective-line"),
  statusLine: document.getElementById("status-line"),
  refreshButton: document.getElementById("refresh-state"),
  seedDemoButton: document.getElementById("seed-demo"),
  cycleForm: document.getElementById("cycle-form"),
  processForm: document.getElementById("process-form"),
  messageForm: document.getElementById("message-form"),
  messageAgentSelect: document.getElementById("message-agent-select"),
};

async function apiGet(path) {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json();
}

async function apiPost(path, payload = {}) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const raw = await response.text();
    throw new Error(raw || `Request failed: ${response.status}`);
  }
  return response.json();
}

function setStatus(message) {
  els.statusLine.textContent = message;
}

function formatTime(value) {
  if (!value) return "";
  return new Date(value).toLocaleString();
}

function renderMetrics(data) {
  const metrics = [
    ["Active Agents", data.system_overview.active_agents],
    ["Total Agents", data.system_overview.total_agents],
    ["Queued Work", data.system_overview.queued_work_items],
    ["Queued Messages", data.system_overview.queued_messages],
  ];

  els.metrics.innerHTML = metrics
    .map(
      ([label, value]) => `
        <article class="metric-card">
          <div class="metric-label">${label}</div>
          <div class="metric-value">${value}</div>
        </article>
      `
    )
    .join("");
}

function renderAgents(data) {
  els.agentCount.textContent = `${data.agents.length} visible`;
  els.messageAgentSelect.innerHTML = data.agents
    .map(
      (agent) => `<option value="${agent.agent_id}">${agent.name} (${agent.role})</option>`
    )
    .join("");

  if (!data.agents.length) {
    els.agentList.innerHTML = `<div class="empty-state">No agents yet. Seed the demo swarm to see the dashboard come alive.</div>`;
    return;
  }

  els.agentList.innerHTML = data.agents
    .map(
      (agent) => `
        <article class="agent-card">
          <div class="agent-top">
            <div>
              <div class="agent-name">${agent.name}</div>
              <div class="agent-role">${agent.role}</div>
            </div>
            <span class="badge status">${agent.status}</span>
          </div>
          <div class="agent-mandate">${agent.mandate}</div>
          <div class="queue-badges">
            <span class="badge queue">${agent.queued_work_items} queued work</span>
            <span class="badge message">${agent.queued_messages} queued messages</span>
            <span class="badge status">creator: ${agent.creator_type}/${agent.creator_id}</span>
          </div>
        </article>
      `
    )
    .join("");
}

function renderMessages(data) {
  els.messageCount.textContent = `${data.messages.length} recent`;
  if (!data.messages.length) {
    els.messageFeed.innerHTML = `<div class="empty-state">No message traffic yet. Seed the demo or send an agent a message.</div>`;
    return;
  }

  els.messageFeed.innerHTML = data.messages
    .map(
      (message) => `
        <article class="message-card">
          <div class="message-top">
            <div class="message-route">${message.sender_label} -> ${message.recipient_label}</div>
            <span class="badge status">${message.status}</span>
          </div>
          <div class="message-meta">${message.subject} • ${formatTime(message.created_at)}</div>
          <div class="message-body">${message.body}</div>
        </article>
      `
    )
    .join("");
}

function renderWork(data) {
  if (!data.work_items.length) {
    els.workList.innerHTML = `<div class="empty-state">No work items yet.</div>`;
    return;
  }

  els.workList.innerHTML = data.work_items
    .map(
      (item) => `
        <article class="work-card">
          <div class="work-top">
            <div class="work-title">${item.title}</div>
            <span class="badge status">${item.status}</span>
          </div>
          <div class="work-meta">${item.owner_label} • requested by ${item.requester_label}</div>
          <div class="message-body">${item.description}</div>
        </article>
      `
    )
    .join("");
}

function renderDecisions(data) {
  if (!data.decisions.length) {
    els.decisionList.innerHTML = `<div class="empty-state">No decisions recorded yet.</div>`;
    return;
  }

  els.decisionList.innerHTML = data.decisions
    .map(
      (item) => `
        <article class="decision-card">
          <div class="work-top">
            <div class="work-title">${item.title}</div>
          </div>
          <div class="decision-meta">${item.agent_id} • ${formatTime(item.created_at)}</div>
          <div class="decision-summary">${item.summary}</div>
        </article>
      `
    )
    .join("");
}

function renderState(data) {
  state.latest = data;
  renderMetrics(data);
  renderAgents(data);
  renderMessages(data);
  renderWork(data);
  renderDecisions(data);

  if (data.objective) {
    els.objectiveLine.textContent = `Objective: ${data.objective.ultimate_objective}`;
  } else {
    els.objectiveLine.textContent = "No objective loaded yet.";
  }

  setStatus(`Last refresh: ${new Date().toLocaleTimeString()}`);
}

async function loadState() {
  const data = await apiGet("/api/state");
  renderState(data);
}

async function withAction(label, fn) {
  setStatus(label);
  try {
    const payload = await fn();
    if (payload.state) {
      renderState(payload.state);
    } else {
      renderState(payload);
    }
    setStatus(`${label} complete at ${new Date().toLocaleTimeString()}`);
  } catch (error) {
    console.error(error);
    setStatus(`Action failed: ${error.message}`);
  }
}

els.refreshButton.addEventListener("click", () => {
  withAction("Refreshing state", () => apiGet("/api/state"));
});

els.seedDemoButton.addEventListener("click", () => {
  withAction("Seeding demo swarm", () => apiPost("/api/demo/seed"));
});

els.cycleForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  withAction("Running CEO cycle", () =>
    apiPost("/api/run-cycle", {
      input: form.get("input"),
      max_agents: 25,
    })
  );
  event.currentTarget.reset();
});

els.processForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  withAction("Processing queue", () =>
    apiPost("/api/process-queue", {
      trigger: form.get("trigger"),
      max_agents: 25,
    })
  );
});

els.messageForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  withAction("Sending human message", () =>
    apiPost("/api/message", {
      recipient_agent_id: form.get("recipient_agent_id"),
      subject: form.get("subject"),
      body: form.get("body"),
      sender_type: "human",
      sender_id: "dashboard",
    })
  );
  event.currentTarget.reset();
});

async function boot() {
  await loadState();
  state.pollHandle = window.setInterval(() => {
    loadState().catch((error) => {
      console.error(error);
      setStatus(`Refresh failed: ${error.message}`);
    });
  }, 4000);
}

boot().catch((error) => {
  console.error(error);
  setStatus(`Startup failed: ${error.message}`);
});
