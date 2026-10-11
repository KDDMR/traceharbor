const projectInput = document.querySelector("#project");
const refreshButton = document.querySelector("#refresh");
const issuesBody = document.querySelector("#issues");
const empty = document.querySelector("#empty");
const dialog = document.querySelector("#detail-dialog");
const detail = document.querySelector("#detail");

function project() {
  return projectInput.value.trim() || "demo-store";
}

function formatTime(value) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

async function request(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`Request failed: ${response.status}`);
  return response.json();
}

async function openIssue(fingerprint) {
  const item = await request(`/api/issues/${fingerprint}?project=${encodeURIComponent(project())}`);
  detail.textContent = JSON.stringify(item, null, 2);
  dialog.showModal();
}

function renderIssues(items) {
  issuesBody.replaceChildren();
  empty.hidden = items.length !== 0;
  for (const item of items) {
    const row = document.createElement("tr");
    row.tabIndex = 0;
    row.innerHTML = `
      <td><strong></strong><span class="fingerprint"></span></td>
      <td><span class="badge"></span></td>
      <td class="mono"></td>
      <td></td>`;
    row.querySelector("strong").textContent = item.title;
    row.querySelector(".fingerprint").textContent = item.fingerprint;
    const badge = row.querySelector(".badge");
    badge.textContent = item.level;
    badge.dataset.level = item.level;
    row.children[2].textContent = item.event_count;
    row.children[3].textContent = formatTime(item.last_seen);
    row.addEventListener("click", () => openIssue(item.fingerprint));
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter") openIssue(item.fingerprint);
    });
    issuesBody.append(row);
  }
}

async function loadDashboard() {
  refreshButton.disabled = true;
  try {
    const encoded = encodeURIComponent(project());
    const [issues, metrics] = await Promise.all([
      request(`/api/issues?project=${encoded}`),
      request(`/api/metrics?project=${encoded}`),
    ]);
    renderIssues(issues.items);
    document.querySelector("#event-count").textContent = metrics.event_count;
    document.querySelector("#issue-count").textContent = metrics.issue_count;
    document.querySelector("#error-count").textContent = metrics.error_count;
    document.querySelector("#duration").textContent = `${metrics.avg_duration_ms} ms`;
    document.querySelector("#updated").textContent = `Updated ${new Date().toLocaleTimeString()}`;
  } catch (error) {
    document.querySelector("#updated").textContent = error.message;
  } finally {
    refreshButton.disabled = false;
  }
}

refreshButton.addEventListener("click", loadDashboard);
projectInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") loadDashboard();
});
document.querySelector("#close-dialog").addEventListener("click", () => dialog.close());
loadDashboard();
