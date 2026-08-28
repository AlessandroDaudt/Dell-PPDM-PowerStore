const state = {
  equipment: [],
  workflows: [],
  dashboard: {},
  inventoryFilter: "ALL",
  powerstoreOptions: {},
  ppdmOptions: {},
  poller: null,
  defaultsApplied: false,
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
}[char]));

async function api(path, options = {}) {
  const config = { credentials: "same-origin", ...options, headers: { ...(options.headers || {}) } };
  if (options.body && typeof options.body !== "string") {
    config.headers["Content-Type"] = "application/json";
    config.body = JSON.stringify(options.body);
  }
  const response = await fetch(path, config);
  if (response.status === 401) {
    showLogin();
    throw new Error("Your session has expired. Sign in again.");
  }
  if (!response.ok) {
    let detail = `HTTP error ${response.status}`;
    try { const body = await response.json(); detail = body.detail || detail; } catch (_) { /* noop */ }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  if (response.status === 204) return null;
  return response.json();
}

function toast(message, error = false) {
  const element = $("#toast");
  element.textContent = message;
  element.className = `toast show${error ? " error" : ""}`;
  clearTimeout(element.timer);
  element.timer = setTimeout(() => { element.className = "toast"; }, 4200);
}

function showLogin() {
  $("#loginScreen").classList.remove("hidden");
  $("#appShell").classList.add("hidden");
}

function showApp() {
  $("#loginScreen").classList.add("hidden");
  $("#appShell").classList.remove("hidden");
}

const pageNames = {
  home: ["CONTROL PLANE", "Overview"], inventory: ["CONFIGURATION", "Inventory"],
  provision: ["ORCHESTRATION", "New LUN"], workflows: ["OBSERVABILITY", "Runs"],
  docs: ["OPERATION", "Documentation"],
};

function navigate(route) {
  $$(".page").forEach((page) => page.classList.toggle("active", page.id === `page-${route}`));
  $$(".nav-item").forEach((button) => button.classList.toggle("active", button.dataset.route === route));
  $("#pageEyebrow").textContent = pageNames[route][0];
  $("#pageTitle").textContent = pageNames[route][1];
  if (route === "workflows") loadWorkflows();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function statusBadge(status) {
  const labels = { COMPLETED: "COMPLETED", FAILED: "FAILED", RUNNING: "RUNNING", PENDING: "PENDING" };
  return `<span class="status-badge ${escapeHtml(status)}">${labels[status] || escapeHtml(status)}</span>`;
}

async function loadAll() {
  const [dashboard, equipment, workflows] = await Promise.all([
    api("/api/dashboard"), api("/api/equipment"), api("/api/workflows?limit=50"),
  ]);
  state.dashboard = dashboard;
  state.equipment = equipment;
  state.workflows = workflows;
  if (!state.defaultsApplied) {
    $("#dryRun").checked = dashboard.default_dry_run !== false;
    state.defaultsApplied = true;
  }
  renderDashboard();
  renderInventory();
  renderProvisionChoices();
  renderWorkflows();
}

function renderDashboard() {
  const counts = state.dashboard.equipment || {};
  const cards = [
    ["PowerStore", counts.POWERSTORE || 0, "Registered arrays", "#365cf5"],
    ["Hosts", counts.HOST || 0, "Physical servers", "#667085"],
    ["Brocade", counts.BROCADE || 0, "Fabric switches", "#805ad5"],
    ["PPDM", counts.PPDM || 0, "Protection managers", "#16a1ae"],
  ];
  $("#metrics").innerHTML = cards.map(([name, count, caption, color]) =>
    `<article class="metric" style="--metric-color:${color}"><span>${name}</span><strong>${count}</strong><small>${caption}</small></article>`
  ).join("");
  const readyTypes = ["POWERSTORE", "HOST", "BROCADE", "PPDM"].filter((type) => counts[type] > 0).length;
  const percent = readyTypes * 25;
  $("#readinessBar").style.width = `${percent}%`;
  $("#heroReadiness").textContent = percent === 100 ? "Ready to orchestrate" : `${readyTypes} of 4 domains ready`;
  $("#readinessText").textContent = percent === 100 ? "Minimum inventory complete. Start with a dry-run." : "Register the four domains to get started.";
  const recent = state.dashboard.recent_workflows || [];
  $("#recentWorkflows").className = recent.length ? "compact-list" : "compact-list empty-state";
  $("#recentWorkflows").innerHTML = recent.length ? recent.map((workflow) => `
    <button class="compact-item text-button workflow-open" data-id="${workflow.id}">
      ${statusBadge(workflow.status)}<span><strong>${escapeHtml(workflow.request.volume?.name || "LUN")}</strong><small>#${workflow.id} · ${workflow.dry_run ? "dry-run" : "live"}</small></span><span>Details →</span>
    </button>`).join("") : "No runs recorded.";
}

function renderInventory() {
  const filtered = state.equipment.filter((item) => state.inventoryFilter === "ALL" || item.type === state.inventoryFilter);
  const root = $("#inventoryGrid");
  if (!filtered.length) {
    root.innerHTML = `<div class="empty-state">No equipment matches this filter.</div>`;
    return;
  }
  root.innerHTML = filtered.map((item) => `
    <article class="equipment-card">
      <div class="equipment-card-head"><div><span class="type-badge ${item.type}">${item.type}</span><h4>${escapeHtml(item.name)}</h4><p>${escapeHtml(item.management_address || "No network endpoint")}${item.api_port ? `:${item.api_port}` : ""}</p></div><span title="TLS">${item.verify_ssl ? "🔒" : "⚠"}</span></div>
      <div class="wwn-list">${item.wwns.length ? item.wwns.slice(0, 5).map((wwn) => `<div class="wwn-row"><span>${escapeHtml(wwn.value)}</span><span>${escapeHtml(wwn.fabric)} · ${escapeHtml(wwn.role)}</span></div>`).join("") : `<span class="muted">No WWNs registered</span>`}${item.wwns.length > 5 ? `<small>+${item.wwns.length - 5} WWNs</small>` : ""}</div>
      <div class="card-actions"><button data-action="test" data-id="${item.id}">Test</button><button data-action="edit" data-id="${item.id}">Edit</button><button class="danger" data-action="delete" data-id="${item.id}">Delete</button></div>
    </article>`).join("");
}

function optionList(type, placeholder = "Select") {
  return `<option value="">${placeholder}</option>` + state.equipment.filter((item) => item.type === type)
    .map((item) => `<option value="${item.id}">${escapeHtml(item.name)}</option>`).join("");
}

function renderProvisionChoices() {
  const keep = (element) => element.value;
  const storage = $("#storageId"), ppdm = $("#ppdmId");
  const storageValue = keep(storage), ppdmValue = keep(ppdm);
  storage.innerHTML = optionList("POWERSTORE"); ppdm.innerHTML = optionList("PPDM");
  storage.value = storageValue; ppdm.value = ppdmValue;
  const choices = (type, cssName) => {
    const items = state.equipment.filter((item) => item.type === type);
    return items.length ? items.map((item) => `<label class="choice"><input type="checkbox" name="${cssName}" value="${item.id}" /><div><strong>${escapeHtml(item.name)}</strong><small>${item.wwns.length} WWN(s) · ${escapeHtml(item.settings.fabric || item.settings.os_type || "")}</small></div></label>`).join("") : `<div class="empty-state">Register ${type === "HOST" ? "a host" : "a switch"}.</div>`;
  };
  $("#hostChoices").innerHTML = choices("HOST", "hostChoice");
  $("#brocadeChoices").innerHTML = choices("BROCADE", "brocadeChoice");
}

function resetEquipmentForm() {
  $("#equipmentForm").reset();
  $("#equipmentId").value = "";
  $("#equipmentPort").value = "443";
  $("#equipmentFid").value = "128";
  $("#equipmentActiveConfig").value = "SANFLOW_CFG";
  $("#equipmentDialogTitle").textContent = "New equipment";
  $("#equipmentError").textContent = "";
  updateEquipmentFields();
}

function updateEquipmentFields() {
  const type = $("#equipmentType").value;
  $$(".network-field").forEach((field) => field.classList.toggle("hidden", type === "HOST"));
  $$(".brocade-setting").forEach((field) => field.classList.toggle("hidden", type !== "BROCADE"));
  $$(".host-setting").forEach((field) => field.classList.toggle("hidden", type !== "HOST"));
  if (!$("#equipmentId").value) $("#equipmentPort").value = type === "PPDM" ? "8443" : "443";
}

function openEquipment(item = null) {
  resetEquipmentForm();
  if (item) {
    $("#equipmentDialogTitle").textContent = `Edit ${item.name}`;
    $("#equipmentId").value = item.id;
    $("#equipmentType").value = item.type;
    $("#equipmentName").value = item.name;
    $("#equipmentAddress").value = item.management_address || "";
    $("#equipmentPort").value = item.api_port || "";
    $("#equipmentUsername").value = item.username || "";
    $("#equipmentVerifySsl").checked = item.verify_ssl;
    $("#equipmentFabric").value = item.settings.fabric || "A";
    $("#equipmentFid").value = item.settings.fid || 128;
    $("#equipmentActiveConfig").value = item.settings.active_config || "SANFLOW_CFG";
    $("#equipmentFos").value = item.settings.fos_generation || "9.1";
    $("#equipmentOs").value = item.settings.os_type || "Linux";
    $("#equipmentHostId").value = item.settings.powerstore_host_id || "";
    $("#equipmentWwns").value = item.wwns.map((wwn) => `${wwn.value}, ${wwn.label || ""}, ${wwn.fabric}, ${wwn.role}`).join("\n");
    updateEquipmentFields();
  }
  $("#equipmentDialog").showModal();
}

function parseWwns(type) {
  const defaultRole = type === "POWERSTORE" ? "TARGET" : type === "BROCADE" ? "SWITCH" : "INITIATOR";
  return $("#equipmentWwns").value.split("\n").map((line) => line.trim()).filter(Boolean).map((line) => {
    const [value, label = "", fabric = "A", role = defaultRole] = line.split(",").map((item) => item.trim());
    return { value, label, fabric: fabric.toUpperCase(), role: role.toUpperCase() };
  });
}

async function saveEquipment(event) {
  event.preventDefault();
  const type = $("#equipmentType").value;
  const settings = type === "BROCADE" ? {
    fabric: $("#equipmentFabric").value.toUpperCase(), fid: Number($("#equipmentFid").value),
    active_config: $("#equipmentActiveConfig").value, fos_generation: $("#equipmentFos").value,
  } : type === "HOST" ? { os_type: $("#equipmentOs").value, powerstore_host_id: $("#equipmentHostId").value || null } : {};
  const body = {
    type, name: $("#equipmentName").value, management_address: $("#equipmentAddress").value || null,
    api_port: $("#equipmentPort").value ? Number($("#equipmentPort").value) : null,
    username: $("#equipmentUsername").value || null, password: $("#equipmentPassword").value || null,
    verify_ssl: $("#equipmentVerifySsl").checked, settings, wwns: parseWwns(type),
  };
  const id = $("#equipmentId").value;
  try {
    await api(id ? `/api/equipment/${id}` : "/api/equipment", { method: id ? "PUT" : "POST", body });
    $("#equipmentDialog").close(); toast("Equipment saved successfully."); await loadAll();
  } catch (error) { $("#equipmentError").textContent = error.message; }
}

async function handleInventoryAction(event) {
  const button = event.target.closest("button[data-action]"); if (!button) return;
  const item = state.equipment.find((entry) => entry.id === Number(button.dataset.id)); if (!item) return;
  if (button.dataset.action === "edit") openEquipment(item);
  if (button.dataset.action === "test") {
    button.disabled = true; button.textContent = "Testing…";
    try { const result = await api(`/api/equipment/${item.id}/test`, { method: "POST" }); toast(`${item.name}: ${result.message || result.version || "connection valid"}`); }
    catch (error) { toast(error.message, true); }
    finally { button.disabled = false; button.textContent = "Test"; }
  }
  if (button.dataset.action === "delete" && confirm(`Delete ${item.name} from the inventory?`)) {
    try { await api(`/api/equipment/${item.id}`, { method: "DELETE" }); toast("Equipment removed."); await loadAll(); }
    catch (error) { toast(error.message, true); }
  }
}

function fillSelect(id, items, label, placeholder) {
  const element = $(id); element.innerHTML = `<option value="">${placeholder}</option>` + (items || []).map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(label(item))}</option>`).join("");
}

async function syncPowerStore() {
  const id = $("#storageId").value; if (!id) return toast("Select um PowerStore.", true);
  const button = $("#syncPowerStore"); button.disabled = true; button.textContent = "Syncing…";
  try {
    state.powerstoreOptions = await api(`/api/integrations/powerstore/${id}/options`);
    fillSelect("#applianceId", state.powerstoreOptions.appliances, (item) => item.name || item.service_tag || item.id, "Auto-select");
    fillSelect("#performancePolicy", state.powerstoreOptions.performance_policies, (item) => item.name || item.id, "Array default");
    fillSelect("#localProtectionPolicy", state.powerstoreOptions.protection_policies, (item) => item.name || item.id, "No local policy");
    toast("PowerStore options updated in real time.");
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; button.textContent = "↻ Sync options"; }
}

function updateDdDependentOptions() {
  const selected = (state.ppdmOptions.data_domains || []).find((item) => item.id === $("#dataDomain").value);
  const interfaces = selected?.details?.dataDomain?.preferredInterfaces || [];
  fillSelect("#ddInterface", interfaces.map((item) => ({ id: item.networkName, ...item })), (item) => `${item.networkName}${item.purposes ? ` · ${item.purposes.join(", ")}` : ""}`, "Automatic");
  const units = (state.ppdmOptions.storage_units || []).filter((unit) => !selected || unit.storageSystem?.id === selected.id || unit.storageSystemId === selected.id);
  fillSelect("#storageUnit", units, (item) => item.name || item.id, "Auto-provision");
}

async function syncPpdm() {
  const id = $("#ppdmId").value; if (!id) return toast("Select um PPDM.", true);
  const button = $("#syncPpdm"); button.disabled = true; button.textContent = "Fetching…";
  try {
    state.ppdmOptions = await api(`/api/integrations/ppdm/${id}/options`);
    fillSelect("#existingPolicy", state.ppdmOptions.policies, (item) => item.name || item.id, "Select a policy");
    fillSelect("#dataDomain", state.ppdmOptions.data_domains, (item) => item.name || item.id, "Select a Data Domain");
    updateDdDependentOptions();
    updateBackupMode();
    toast(`PPDM ${state.ppdmOptions.version}: Data Domains, storage units, and policies updated.`);
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; button.textContent = "↻ Fetch Data Domains and policies"; }
}

function updatePolicySummary() {
  const policies = state.ppdmOptions.policies || [];
  const selected = policies.find((item) => item.id === $("#existingPolicy").value);
  const root = $("#policySummary");
  const toggles = {
    SNAPSHOT: $("#snapshotEnabled"),
    REPLICATION: $("#replicationEnabled"),
    CLOUD_TIER: $("#cloudTierEnabled"),
  };
  if ($("#backupMode").value !== "EXISTING_POLICY" || !selected) {
    root.classList.add("hidden");
    return;
  }
  const objectives = selected.objectives || selected.stages || [];
  const types = objectives.map((item) => String(item.type || "").toUpperCase());
  Object.entries(toggles).forEach(([type, input]) => {
    input.checked = types.includes(type);
    input.disabled = true;
  });
  const targets = objectives
    .map((item) => item.target?.storageContainerId || item.target?.storageSystemId)
    .filter(Boolean);
  const schedules = objectives.flatMap((item) => item.operations || []).map((operation) => {
    const schedule = operation.schedule || {};
    return schedule.recurrence?.pattern?.type || schedule.frequency;
  }).filter(Boolean);
  const retentions = objectives.flatMap((item) => {
    if (item.retention) return [`${item.retention.interval} ${item.retention.unit}`];
    return (item.retentions || []).flatMap((entry) => (entry.time || []).map(
      (time) => `${time.unitValue} ${time.unitType} (${time.type})`,
    ));
  });
  root.innerHTML = `<strong>Policy read in real time</strong><span>Objectives: ${escapeHtml(types.join(", ") || "not provided")}</span><span>Schedules: ${escapeHtml([...new Set(schedules)].join(", ") || "not provided")}</span><span>Retentions: ${escapeHtml(retentions.join(", ") || "not provided")}</span><span>DD targets: ${escapeHtml([...new Set(targets)].join(", ") || "automatic")}</span>`;
  root.classList.remove("hidden");
}

function updateBackupMode() {
  const create = $("#backupMode").value === "CREATE_POLICY";
  const existing = $("#backupMode").value === "EXISTING_POLICY";
  const resetAdvancedSelections = create && $("#snapshotEnabled").disabled;
  $("#existingPolicyField").classList.toggle("hidden", !existing);
  ["#newPolicyField", "#dataDomainField", "#ddInterfaceField", "#storageUnitField"].forEach((id) => $(id).classList.toggle("hidden", !create));
  const policyOptionIds = [
    "#backupFrequency", "#backupStart", "#backupDuration", "#backupInterval",
    "#retentionInterval", "#retentionUnit", "#backupLevel", "#dataConsistency",
    "#dayOfMonth", "#weekdays", "#retentionLock", "#encryptedBackup",
    "#snapshotEnabled", "#replicationEnabled", "#cloudTierEnabled", "#rawOverrides",
  ];
  policyOptionIds.forEach((id) => { $(id).disabled = !create; });
  if (resetAdvancedSelections) {
    ["#snapshotEnabled", "#replicationEnabled", "#cloudTierEnabled"].forEach((id) => {
      $(id).checked = false;
    });
  }
  if (create && state.ppdmOptions.policy_api === "v3") {
    $("#encryptedBackup").checked = true;
    $("#encryptedBackup").disabled = true;
    $("#encryptedBackup").title = "The v3 contract does not expose encrypted in the policy object.";
  } else {
    $("#encryptedBackup").title = "";
  }
  updatePolicySummary();
}

function checkedValues(name) { return $$(`input[name="${name}"]:checked`).map((input) => Number(input.value)); }

async function submitProvision(event) {
  event.preventDefault();
  const mode = $("#backupMode").value;
  let rawOverrides = {};
  try { rawOverrides = $("#rawOverrides").value.trim() ? JSON.parse($("#rawOverrides").value) : {}; }
  catch (_) { return toast("The advanced payload is not valid JSON.", true); }
  const body = {
    storage_id: Number($("#storageId").value), ppdm_id: $("#ppdmId").value ? Number($("#ppdmId").value) : null,
    host_ids: checkedValues("hostChoice"), brocade_ids: checkedValues("brocadeChoice"), dry_run: $("#dryRun").checked,
    volume: {
      name: $("#volumeName").value, size_gib: Number($("#volumeSize").value), description: $("#volumeDescription").value,
      appliance_id: $("#applianceId").value || null, performance_policy_id: $("#performancePolicy").value || null,
      protection_policy_id: $("#localProtectionPolicy").value || null, logical_unit_number: $("#lunNumber").value ? Number($("#lunNumber").value) : null,
    },
    zoning: { enabled: $("#zoningEnabled").checked, config_name: $("#zoneConfig").value, naming_template: $("#zoneTemplate").value, activate: $("#activateConfig").checked, peer_zoning: $("#peerZoning").checked },
    backup: {
      mode, policy_id: mode === "EXISTING_POLICY" ? $("#existingPolicy").value || null : null,
      policy_name: mode === "CREATE_POLICY" ? $("#newPolicyName").value || null : null,
      data_domain_id: mode === "CREATE_POLICY" ? $("#dataDomain").value || null : null,
      data_domain_interface: $("#ddInterface").value || null, storage_unit_id: $("#storageUnit").value || null,
      frequency: $("#backupFrequency").value, interval: Number($("#backupInterval").value), start_time: $("#backupStart").value,
      duration_hours: Number($("#backupDuration").value), weekdays: $("#weekdays").value.split(",").map((v) => v.trim().toUpperCase()).filter(Boolean),
      day_of_month: Number($("#dayOfMonth").value), retention_interval: Number($("#retentionInterval").value), retention_unit: $("#retentionUnit").value,
      retention_lock: $("#retentionLock").checked, backup_level: $("#backupLevel").value, encrypted: $("#encryptedBackup").checked,
      data_consistency: $("#dataConsistency").value, snapshot_enabled: $("#snapshotEnabled").checked,
      replication_enabled: $("#replicationEnabled").checked, cloud_tier_enabled: $("#cloudTierEnabled").checked, raw_overrides: rawOverrides,
    },
  };
  if (!body.dry_run && !confirm("LIVE mode: this flow will create a volume, mappings, zones, and protection. Continue?")) return;
  const submit = $("#provisionForm button[type=submit]"); submit.disabled = true; submit.textContent = "Iniciando…";
  try {
    const workflow = await api("/api/workflows", { method: "POST", body });
    toast(`Workflow #${workflow.id} started.`); navigate("workflows"); await loadWorkflows(); openWorkflow(workflow.id); startPolling();
  } catch (error) { toast(error.message, true); }
  finally { submit.disabled = false; submit.textContent = "Run complete flow →"; }
}

async function loadWorkflows() {
  try { state.workflows = await api("/api/workflows?limit=100"); renderWorkflows(); }
  catch (error) { toast(error.message, true); }
}

function renderWorkflows() {
  const root = $("#workflowList");
  if (!state.workflows.length) return root.innerHTML = `<div class="empty-state">No workflows executed.</div>`;
  root.innerHTML = state.workflows.map((workflow) => `
    <article class="workflow-card"><strong>#${workflow.id}</strong><div><h4>${escapeHtml(workflow.request.volume?.name || "LUN")}</h4><p>${workflow.dry_run ? "DRY-RUN" : "LIVE"} · ${escapeHtml(workflow.current_step || "Completed")}</p></div><div class="step-mini">${workflow.steps.map((step) => `<i class="${step.status}" title="${escapeHtml(step.name)}"></i>`).join("")}</div><div>${statusBadge(workflow.status)} <button class="button compact ghost workflow-open" data-id="${workflow.id}">Details</button></div></article>`).join("");
}

async function openWorkflow(id) {
  try {
    const workflow = await api(`/api/workflows/${id}`);
    $("#workflowDialogTitle").textContent = `Workflow #${workflow.id} · ${workflow.request.volume?.name || "LUN"}`;
    $("#workflowDetail").innerHTML = `${workflow.error ? `<div class="error-box">${escapeHtml(workflow.error)}</div>` : ""}<div class="timeline">${workflow.steps.map((step) => `<article class="timeline-step"><i class="timeline-dot ${step.status}"></i><div><h4>${escapeHtml(step.name)} · ${escapeHtml(step.status)}</h4><p>${escapeHtml(step.message || "Waiting for execution")}</p></div></article>`).join("")}</div>`;
    $("#workflowDialog").showModal();
  } catch (error) { toast(error.message, true); }
}

function startPolling() {
  clearInterval(state.poller);
  state.poller = setInterval(async () => {
    if (!state.workflows.some((workflow) => ["PENDING", "RUNNING"].includes(workflow.status))) { clearInterval(state.poller); return; }
    await loadWorkflows();
  }, 3000);
}

function bindEvents() {
  $("#loginForm").addEventListener("submit", async (event) => {
    event.preventDefault(); $("#loginError").textContent = "";
    const form = new FormData(event.target);
    try { await api("/api/auth/login", { method: "POST", body: Object.fromEntries(form) }); showApp(); await loadAll(); }
    catch (error) { $("#loginError").textContent = error.message; }
  });
  $("#logoutButton").addEventListener("click", async () => { await api("/api/auth/logout", { method: "POST" }); showLogin(); });
  $$(".nav-item").forEach((button) => button.addEventListener("click", () => navigate(button.dataset.route)));
  $$('[data-go]').forEach((button) => button.addEventListener("click", () => navigate(button.dataset.go)));
  $("#addEquipmentButton").addEventListener("click", () => openEquipment());
  $("#equipmentType").addEventListener("change", updateEquipmentFields);
  $("#equipmentForm").addEventListener("submit", saveEquipment);
  $$('[data-close-dialog]').forEach((button) => button.addEventListener("click", () => $("#equipmentDialog").close()));
  $$('[data-close-workflow]').forEach((button) => button.addEventListener("click", () => $("#workflowDialog").close()));
  $("#inventoryGrid").addEventListener("click", handleInventoryAction);
  $$(".filter").forEach((button) => button.addEventListener("click", () => { state.inventoryFilter = button.dataset.filter; $$(".filter").forEach((item) => item.classList.toggle("active", item === button)); renderInventory(); }));
  $("#syncPowerStore").addEventListener("click", syncPowerStore);
  $("#syncPpdm").addEventListener("click", syncPpdm);
  $("#dataDomain").addEventListener("change", updateDdDependentOptions);
  $("#backupMode").addEventListener("change", updateBackupMode);
  $("#existingPolicy").addEventListener("change", updatePolicySummary);
  $("#dryRun").addEventListener("change", () => { $("#submitHint").textContent = $("#dryRun").checked ? "Dry-run generates the plan without modifying infrastructure." : "LIVE mode: real changes will be executed."; });
  $("#provisionForm").addEventListener("submit", submitProvision);
  $("#refreshWorkflows").addEventListener("click", loadWorkflows);
  document.addEventListener("click", (event) => { const target = event.target.closest(".workflow-open"); if (target) openWorkflow(Number(target.dataset.id)); });
}

async function bootstrap() {
  bindEvents(); updateBackupMode();
  try { const auth = await api("/api/auth/status"); if (auth.authenticated) { showApp(); await loadAll(); startPolling(); } else showLogin(); }
  catch (_) { showLogin(); }
}

document.addEventListener("DOMContentLoaded", bootstrap);
