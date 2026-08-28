const state = {
  equipment: [],
  workflows: [],
  dashboard: {},
  inventoryFilter: "ALL",
  powerstoreOptions: {},
  ppdmOptions: {},
  poller: null,
  statusPoller: null,
  status: { systems: [], sample_interval_seconds: 60, retention_days: 30 },
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
    throw new Error("Your session has expired. Please log in again.");
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
  if (route === "status") { loadStatus(); startStatusPolling(); }
  else { clearInterval(state.statusPoller); state.statusPoller = null; }
  window.scrollTo({ top: 0, behavior: "smooth" });
}

pageNames.status = ["MONITORING", "Status"];

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
    ["PowerStore", counts.POWERSTORE || 0, "Arrays cadastrados", "#365cf5"],
    ["Hosts", counts.HOST || 0, "Physical servers", "#667085"],
    ["Fibre Channel", (counts.BROCADE || 0) + (counts.CISCO_MDS || 0), "Fabric switches", "#805ad5"],
    ["PPDM", counts.PPDM || 0, "Protection managers", "#16a1ae"],
  ];
  $("#metrics").innerHTML = cards.map(([name, count, caption, color]) =>
    `<article class="metric" style="--metric-color:${color}"><span>${name}</span><strong>${count}</strong><small>${caption}</small></article>`
  ).join("");
  const readyTypes = ["POWERSTORE", "HOST", "PPDM"].filter((type) => counts[type] > 0).length + ((counts.BROCADE || 0) + (counts.CISCO_MDS || 0) > 0 ? 1 : 0);
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
  const types = Array.isArray(type) ? type : [type];
  return `<option value="">${placeholder}</option>` + state.equipment.filter((item) => types.includes(item.type))
    .map((item) => `<option value="${item.id}" data-type="${item.type}">${escapeHtml(item.name)}${types.length > 1 ? ` · ${item.type}` : ""}</option>`).join("");
}

function renderProvisionChoices() {
  const keep = (element) => element.value;
  const storage = $("#storageId"), ppdm = $("#ppdmId");
  const storageValue = keep(storage), ppdmValue = keep(ppdm);
  storage.innerHTML = optionList(["POWERSTORE", "POWERMAX", "POWERSTORE_NAS", "POWERSCALE", "UNITY"]); ppdm.innerHTML = optionList("PPDM");
  storage.value = storageValue; ppdm.value = ppdmValue;
  const choices = (type, cssName) => {
    const types = Array.isArray(type) ? type : [type];
    const items = state.equipment.filter((item) => types.includes(item.type));
    return items.length ? items.map((item) => `<label class="choice"><input type="checkbox" name="${cssName}" value="${item.id}" /><div><strong>${escapeHtml(item.name)}</strong><small>${item.wwns.length} WWN(s) · ${escapeHtml(item.type === "CISCO_MDS" ? `${item.settings.fabric || "A"} · VSAN ${item.settings.default_vsan || 1}` : item.settings.fabric || item.settings.os_type || "")}</small></div></label>`).join("") : `<div class="empty-state">Register ${type === "HOST" ? "a host" : "a switch"}.</div>`;
  };
  $("#hostChoices").innerHTML = choices("HOST", "hostChoice");
  $("#brocadeChoices").innerHTML = choices(["BROCADE", "CISCO_MDS"], "fabricChoice");
}

function updateResourceType() {
  const group = $("#resourceType").value === "VOLUME_GROUP";
  const powermax = $("#resourceType").value === "POWERMAX_STORAGE_GROUP";
  const nas = ["NAS_SHARE", "NAS_DATA"].includes($("#resourceType").value);
  $("#volumeGroupFields").classList.toggle("hidden", !group);
  $("#powermaxFields").classList.toggle("hidden", !powermax);
  $("#nasFields").classList.toggle("hidden", !nas);
  $("#volumeName").required = !group;
  $("#volumeSize").required = ["VOLUME", "POWERMAX_STORAGE_GROUP", "NAS_DATA"].includes($("#resourceType").value);
  $("#groupName").required = group;
  $("#groupMembers").required = group;
  $("#nasPath").required = nas;
  const hostless = nas;
  $("#zoningEnabled").checked = !hostless;
  $("#zoningEnabled").disabled = hostless;
  $("#zoningEnabled").closest(".inline-options").classList.toggle("disabled-section", hostless);
  $("#hostChoices").closest(".selection-columns").classList.toggle("disabled-section", hostless);
  if (nas && $("#backupMode").value === "NONE") {
    $("#backupMode").value = "EXISTING_POLICY";
    updateBackupMode();
  }
}

function updateStorageResourceDefaults() {
  const selected = $("#storageId").selectedOptions[0];
  if (selected?.dataset.type === "POWERMAX") $("#resourceType").value = "POWERMAX_STORAGE_GROUP";
  else if (["POWERSTORE_NAS", "POWERSCALE", "UNITY"].includes(selected?.dataset.type)) $("#resourceType").value = "NAS_SHARE";
  else if (["POWERMAX_STORAGE_GROUP", "NAS_SHARE", "NAS_DATA"].includes($("#resourceType").value)) $("#resourceType").value = "VOLUME";
  updateResourceType();
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
  $$(".powermax-setting").forEach((field) => field.classList.toggle("hidden", type !== "POWERMAX"));
  $$(".powerscale-setting").forEach((field) => field.classList.toggle("hidden", type !== "POWERSCALE"));
  $$(".unity-setting").forEach((field) => field.classList.toggle("hidden", type !== "UNITY"));
  $$(".cisco-setting").forEach((field) => field.classList.toggle("hidden", type !== "CISCO_MDS"));
  if (!$("#equipmentId").value) $("#equipmentPort").value = type === "PPDM" ? "8443" : type === "POWERSCALE" ? "8080" : type === "DATA_DOMAIN" ? "3009" : "443";
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
    $("#equipmentPowermaxHostId").value = item.settings.powermax_host_id || "";
    $("#equipmentSymmetrixId").value = item.settings.symmetrix_id || "";
    $("#equipmentApiVersion").value = item.settings.api_version || "100";
    $("#equipmentDefaultSrp").value = item.settings.default_srp_id || "";
    $("#equipmentDefaultSlo").value = item.settings.default_slo_id || "";
    $("#equipmentOnefsApiVersion").value = item.settings.api_version || "3";
    $("#equipmentUnityApiVersion").value = item.settings.api_version || "5.2";
    $("#equipmentDefaultPortGroup").value = item.settings.default_port_group_id || "";
    $("#equipmentCiscoApiVersion").value = item.settings.api_version || "1.2";
    $("#equipmentCiscoFabric").value = item.settings.fabric || "A";
    $("#equipmentCiscoVsan").value = item.settings.default_vsan || 1;
    $("#equipmentCiscoZoneset").value = item.settings.default_zoneset || "SANFLOW_CFG";
    $("#equipmentWwns").value = item.wwns.map((wwn) => `${wwn.value}, ${wwn.label || ""}, ${wwn.fabric}, ${wwn.role}`).join("\n");
    updateEquipmentFields();
  }
  $("#equipmentDialog").showModal();
}

function parseWwns(type) {
  const defaultRole = ["POWERSTORE", "POWERMAX"].includes(type) ? "TARGET" : ["BROCADE", "CISCO_MDS"].includes(type) ? "SWITCH" : "INITIATOR";
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
  } : type === "HOST" ? { os_type: $("#equipmentOs").value, powerstore_host_id: $("#equipmentHostId").value || null, powermax_host_id: $("#equipmentPowermaxHostId").value || null } : type === "POWERMAX" ? {
    symmetrix_id: $("#equipmentSymmetrixId").value || null,
    api_version: $("#equipmentApiVersion").value || "100",
    default_srp_id: $("#equipmentDefaultSrp").value || null,
    default_slo_id: $("#equipmentDefaultSlo").value || null,
    default_port_group_id: $("#equipmentDefaultPortGroup").value || null,
  } : type === "POWERSCALE" ? {
    api_version: $("#equipmentOnefsApiVersion").value || "3",
  } : type === "UNITY" ? {
    api_version: $("#equipmentUnityApiVersion").value || "5.2",
  } : type === "CISCO_MDS" ? {
    api_version: $("#equipmentCiscoApiVersion").value || "1.2",
    fabric: $("#equipmentCiscoFabric").value.toUpperCase() || "A",
    default_vsan: Number($("#equipmentCiscoVsan").value || 1),
    default_zoneset: $("#equipmentCiscoZoneset").value || "SANFLOW_CFG",
  } : {};
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
  if (button.dataset.action === "delete" && confirm(`Delete ${item.name} from inventory?`)) {
    try { await api(`/api/equipment/${item.id}`, { method: "DELETE" }); toast("Equipment removed."); await loadAll(); }
    catch (error) { toast(error.message, true); }
  }
}

function fillSelect(id, items, label, placeholder) {
  const element = $(id); element.innerHTML = `<option value="">${placeholder}</option>` + (items || []).map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(label(item))}</option>`).join("");
}

async function syncPowerStore() {
  const id = $("#storageId").value; if (!id) return toast("Select a PowerStore.", true);
  const button = $("#syncPowerStore"); button.disabled = true; button.textContent = "Syncing…";
  try {
    const type = $("#storageId").selectedOptions[0]?.dataset.type;
    const endpoint = type === "POWERMAX"
      ? "powermax"
      : type === "POWERSCALE"
        ? "powerscale"
        : type === "UNITY"
          ? "unity"
          : "powerstore";
    state.powerstoreOptions = await api(`/api/integrations/${endpoint}/${id}/options`);
    fillSelect("#applianceId", state.powerstoreOptions.appliances, (item) => item.name || item.service_tag || item.id, "Auto-select");
    fillSelect("#performancePolicy", state.powerstoreOptions.performance_policies, (item) => item.name || item.id, "Array default");
    fillSelect("#localProtectionPolicy", state.powerstoreOptions.protection_policies, (item) => item.name || item.id, "No local policy");
    fillSelect("#nasServerId", state.powerstoreOptions.nas_servers, (item) => item.name || item.id, "Automatic");
    fillSelect("#nasFileSystemId", state.powerstoreOptions.file_systems, (item) => item.name || item.id, "Automatic");
    fillSelect("#powermaxPortGroup", state.powerstoreOptions.port_groups, (item) => item.name || item.id, "Register it in PowerMax first");
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
  const id = $("#ppdmId").value; if (!id) return toast("Select a PPDM.", true);
  const button = $("#syncPpdm"); button.disabled = true; button.textContent = "Fetching…";
  try {
    const nas = ["NAS_SHARE", "NAS_DATA"].includes($("#resourceType").value);
    state.ppdmOptions = await api(`/api/integrations/ppdm/${id}/${nas ? "nas-options" : "options"}`);
    fillSelect("#existingPolicy", state.ppdmOptions.policies, (item) => item.name || item.id, "Select a policy");
    fillSelect("#dataDomain", state.ppdmOptions.data_domains, (item) => item.name || item.id, "Select a Data Domain");
    updateDdDependentOptions();
    fillSelect("#nasProtectionEngine", state.ppdmOptions.protection_engines, (item) => item.name || item.id, "Automatic");
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
  $("#nasEngineField").classList.toggle("hidden", !["NAS_SHARE", "NAS_DATA"].includes($("#resourceType").value));
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
  const resourceType = $("#resourceType").value;
  let members = [];
  if (resourceType === "VOLUME_GROUP") {
    try { members = JSON.parse($("#groupMembers").value || "[]"); }
    catch (_) { return toast("The member volume list is not valid JSON.", true); }
  }
  const body = {
    storage_id: Number($("#storageId").value), ppdm_id: $("#ppdmId").value ? Number($("#ppdmId").value) : null,
    host_ids: checkedValues("hostChoice"), fabric_ids: checkedValues("fabricChoice"), dry_run: $("#dryRun").checked,
    volume: {
      name: resourceType === "VOLUME_GROUP" ? null : $("#volumeName").value,
      size_gib: resourceType === "VOLUME_GROUP" ? null : Number($("#volumeSize").value), description: $("#volumeDescription").value,
      resource_type: resourceType, group_name: resourceType === "VOLUME_GROUP" ? $("#groupName").value : null,
      group_description: resourceType === "VOLUME_GROUP" ? $("#groupDescription").value || null : null,
      members, write_order_consistent: true,
      volume_count: resourceType === "POWERMAX_STORAGE_GROUP" ? Number($("#powermaxVolumeCount").value) : 1,
      volume_prefix: resourceType === "POWERMAX_STORAGE_GROUP" ? $("#powermaxVolumePrefix").value || null : null,
      srp_id: resourceType === "POWERMAX_STORAGE_GROUP" ? $("#powermaxSrp").value || null : null,
      slo_id: resourceType === "POWERMAX_STORAGE_GROUP" ? $("#powermaxSlo").value || null : null,
      emulation: resourceType === "POWERMAX_STORAGE_GROUP" ? $("#powermaxEmulation").value : "FBA",
      nas_protocol: resourceType.startsWith("NAS_") ? $("#nasProtocol").value : "NFS",
      nas_path: resourceType.startsWith("NAS_") ? $("#nasPath").value || null : null,
      nas_server_id: resourceType.startsWith("NAS_") ? $("#nasServerId").value || null : null,
      nas_file_system_id: resourceType.startsWith("NAS_") ? $("#nasFileSystemId").value || null : null,
      appliance_id: $("#applianceId").value || null, performance_policy_id: $("#performancePolicy").value || null,
      protection_policy_id: $("#localProtectionPolicy").value || null, logical_unit_number: $("#lunNumber").value ? Number($("#lunNumber").value) : null,
      powermax_port_group_id: resourceType === "POWERMAX_STORAGE_GROUP" ? $("#powermaxPortGroup").value || null : null,
      masking_view_prefix: resourceType === "POWERMAX_STORAGE_GROUP" ? $("#powermaxMaskingViewPrefix").value || null : null,
    },
    zoning: { enabled: $("#zoningEnabled").checked, config_name: $("#zoneConfig").value, naming_template: $("#zoneTemplate").value, activate: $("#activateConfig").checked, peer_zoning: $("#peerZoning").checked, vsan_id: Number($("#vsanId").value || 1) },
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
      nas_protection_engine_id: resourceType.startsWith("NAS_") ? $("#nasProtectionEngine").value || null : null,
    },
  };
  if (!body.dry_run && !confirm("LIVE mode: this flow will create a volume, mappings, zones, Fibre Channel zoning, and protection. Continue?")) return;
  const submit = $("#provisionForm button[type=submit]"); submit.disabled = true; submit.textContent = "Starting…";
  try {
    const workflow = await api("/api/workflows", { method: "POST", body });
    toast(`Workflow #${workflow.id} started.`); navigate("workflows"); await loadWorkflows(); openWorkflow(workflow.id); startPolling();
  } catch (error) { toast(error.message, true); }
  finally { submit.disabled = false; submit.textContent = "Run complete flow →"; }
}

function scalarMetric(value) {
  if (value === null || value === undefined || value === "") return null;
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "string") {
    const number = Number(value.replace(/,/g, ""));
    return Number.isFinite(number) ? number : value;
  }
  if (typeof value === "object" && !Array.isArray(value)) {
    for (const key of ["value", "current", "total", "used", "bytes", "size"]) {
      if (value[key] !== undefined) return scalarMetric(value[key]);
    }
  }
  return null;
}

function findMetric(value, names) {
  if (value === null || value === undefined) return null;
  const wanted = names.map((name) => String(name).toLowerCase().replace(/[^a-z0-9]/g, ""));
  if (typeof value === "object" && !Array.isArray(value)) {
    for (const [key, item] of Object.entries(value)) {
      if (wanted.includes(key.toLowerCase().replace(/[^a-z0-9]/g, ""))) return item;
    }
    for (const item of Object.values(value)) {
      const found = findMetric(item, names);
      if (found !== null && found !== undefined) return found;
    }
  }
  if (Array.isArray(value)) {
    for (const item of value) {
      const found = findMetric(item, names);
      if (found !== null && found !== undefined) return found;
    }
  }
  return null;
}

function formatBytes(value) {
  const number = scalarMetric(value);
  if (number === null || typeof number !== "number") return "N/A";
  const units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"];
  let size = number; let unit = 0;
  while (Math.abs(size) >= 1024 && unit < units.length - 1) { size /= 1024; unit += 1; }
  return `${size.toLocaleString("en-US", { maximumFractionDigits: 2 })} ${units[unit]}`;
}

function formatPercent(value) {
  const number = scalarMetric(value);
  if (number === null || typeof number !== "number") return "N/A";
  return `${number.toLocaleString("en-US", { maximumFractionDigits: 2 })}%`;
}

function metricText(metrics, byteNames, percentNames, suffix = "") {
  const bytes = findMetric(metrics, byteNames);
  if (bytes !== null && typeof scalarMetric(bytes) === "number") return formatBytes(bytes);
  const percent = findMetric(metrics, percentNames);
  if (percent !== null && typeof scalarMetric(percent) === "number") return formatPercent(percent);
  const value = findMetric(metrics, ["value", "current"]);
  return value === null ? "N/A" : `${scalarMetric(value) ?? value}${suffix}`;
}

function networkText(metrics) {
  const bits = scalarMetric(findMetric(metrics, ["rx_rate_bits_ps", "tx_rate_bits_ps", "network_rate_bits_ps"]));
  if (typeof bits === "number") return `${(bits / 1000000).toLocaleString("en-US", { maximumFractionDigits: 2 })} Mbps`;
  const bytes = scalarMetric(findMetric(metrics, ["throughput_bytes_per_second", "network_bytes_per_second"]));
  if (typeof bytes === "number") return `${((bytes * 8) / 1000000).toLocaleString("en-US", { maximumFractionDigits: 2 })} Mbps`;
  const mbps = scalarMetric(findMetric(metrics, ["throughput_mbps", "network_mbps"]));
  if (typeof mbps === "number") return `${mbps.toLocaleString("en-US", { maximumFractionDigits: 2 })} Mbps`;
  return metricText(metrics, [], ["network_utilization", "network_utilization_percent"]);
}

function statusPorts(metrics) {
  const ports = findMetric(metrics, ["ports", "fc_ports", "fibrechannel", "interfaces"]);
  return Array.isArray(ports) ? ports : [];
}

function portValue(port, keys) {
  for (const key of keys) {
    if (port[key] !== undefined && port[key] !== null && port[key] !== "") return port[key];
    if (port.statistics && port.statistics[key] !== undefined) return port.statistics[key];
  }
  return "—";
}

function renderStatusPortTable(metrics) {
  const ports = statusPorts(metrics);
  if (!ports.length) return `<p class="muted">No structured port data in this collection. See the raw details.</p>`;
  const rows = ports.slice(0, 200).map((port) => {
    const name = portValue(port, ["name", "interface", "port", "port_name", "portName"]);
    const status = portValue(port, ["status", "operational-status", "operational_status", "link_state", "linkState"]);
    const speed = portValue(port, ["speed", "speed_gbps", "speedGbps"]);
    const utilization = portValue(port, ["utilization", "utilization_percent", "txwait_percent_1m"]);
    const attenuation = portValue(port, ["attenuation", "rx_power", "tx_power", "rxPower", "txPower"]);
    const errors = portValue(port, ["errors", "rx_error", "tx_error", "rx_error_frames", "tx_error_frames"]);
    const credits = portValue(port, ["buffer_credits", "tx_b2b_credit_remain", "rx_b2b_credit_remain", "tx_b2b_credits", "rx_b2b_credits"]);
    return `<tr><td>${escapeHtml(name)}</td><td>${escapeHtml(status)}</td><td>${escapeHtml(speed)}</td><td>${escapeHtml(utilization)}</td><td>${escapeHtml(attenuation)}</td><td>${escapeHtml(errors)}</td><td>${escapeHtml(credits)}</td></tr>`;
  }).join("");
  return `<div class="table-scroll"><table class="status-table"><thead><tr><th>Port</th><th>Status</th><th>Speed</th><th>Usage / txwait</th><th>Attenuation / power</th><th>Errors</th><th>Buffer credits</th></tr></thead><tbody>${rows}</tbody></table></div>${ports.length > 200 ? `<small class="muted">Showing 200 of ${ports.length} ports; the complete payload is in the details.</small>` : ""}`;
}

function statusStateBadge(value) {
  const stateValue = String(value || "UNKNOWN").toUpperCase();
  const label = { OK: "OK", DEGRADED: "DEGRADED", ERROR: "ERROR", UNKNOWN: "NO DATA" }[stateValue] || stateValue;
  return `<span class="status-state ${escapeHtml(stateValue)}">${label}</span>`;
}

function renderStatusSystem(system) {
  const metrics = system.metrics || {};
  const ports = statusPorts(metrics);
  const network = networkText(metrics);
  return `<article class="status-system"><div class="status-system-head"><div><span class="type-badge ${escapeHtml(system.component_type)}">${escapeHtml(system.component_type)}</span><h4>${escapeHtml(system.component_name)}</h4><small>${escapeHtml(new Date(system.sampled_at).toLocaleString("en-US"))}</small></div>${statusStateBadge(system.state)}</div><div class="status-facts"><span><b>Capacity</b>${metricText(metrics, ["usable_capacity_bytes", "total_capacity_bytes", "capacity_bytes", "logical_capacity_bytes", "total_bytes"], ["capacity_utilization", "capacity_utilization_percent", "used_percent", "utilization_percent"])}</span><span><b>Usage</b>${metricText(metrics, ["used_bytes", "used_capacity_bytes", "physical_used_bytes"], ["used_percent", "capacity_utilization_percent", "licensed_utilization"])}</span><span><b>Network</b>${network}</span><span><b>Ports</b>${ports.length || "N/A"}</span></div>${ports.length ? `<div class="status-ports"><h5>Ports and counters</h5>${renderStatusPortTable(metrics)}</div>` : ""}<details class="status-details"><summary>All collected data</summary><pre>${escapeHtml(JSON.stringify(metrics, null, 2))}</pre></details>${system.error ? `<p class="form-error">${escapeHtml(system.error)}</p>` : ""}</article>`;
}

function renderStatus() {
  const systems = state.status.systems || [];
  const healthy = systems.filter((item) => item.state === "OK").length;
  const errors = systems.filter((item) => ["ERROR", "DEGRADED"].includes(item.state)).length;
  const cards = [["Components", systems.length, "Latest persisted state", "#365cf5"], ["Healthy", healthy, "OK samples", "#16a1ae"], ["Attention", errors, "Error or partial metric", "#e07a25"], ["Retention", `${state.status.retention_days || 30}d`, `Every ${state.status.sample_interval_seconds || 60}s`, "#805ad5"]];
  $("#statusSummary").innerHTML = cards.map(([name, count, caption, color]) => `<article class="metric" style="--metric-color:${color}"><span>${name}</span><strong>${count}</strong><small>${caption}</small></article>`).join("");
  $("#statusSystems").innerHTML = systems.length ? systems.map(renderStatusSystem).join("") : `<div class="empty-state">No samples available. Register monitorable equipment or click Collect now.</div>`;
  $("#statusLastUpdate").textContent = systems.length ? `Visual refresh every 15s · collection configured every ${state.status.sample_interval_seconds || 60}s · retention ${state.status.retention_days || 30} days` : "Waiting for the first collection.";
  const target = $("#statusHistoryTarget");
  const previous = target.value;
  target.innerHTML = `<option value="">Select a component</option>` + systems.map((item) => `<option value="${item.equipment_id}::${escapeHtml(item.component_key)}">${escapeHtml(item.component_name)} · ${escapeHtml(item.component_type)}</option>`).join("");
  if ([...target.options].some((option) => option.value === previous)) target.value = previous;
  if (target.value) loadStatusHistory();
}

async function loadStatus(options = {}) {
  try {
    if (options.collect) await api("/api/status/collect", { method: "POST" });
    state.status = await api("/api/status");
    renderStatus();
  } catch (error) { if (options.collect) toast(error.message, true); }
}

async function loadStatusHistory() {
  const target = $("#statusHistoryTarget").value;
  if (!target) { $("#statusHistory").innerHTML = `<p class="muted">Select a component to view samples.</p>`; return; }
  const separator = target.indexOf("::");
  const equipmentId = target.slice(0, separator);
  const componentKey = target.slice(separator + 2);
  const hours = $("#statusHistoryRange").value;
  try {
    const result = await api(`/api/status/history?equipment_id=${encodeURIComponent(equipmentId)}&component_key=${encodeURIComponent(componentKey)}&hours=${hours}`);
    const samples = result.samples || [];
    $("#statusHistory").innerHTML = samples.length ? `<div class="table-scroll"><table class="status-table history-table"><thead><tr><th>Sample</th><th>State</th><th>Capacity / usage</th><th>Ports</th><th>Error</th></tr></thead><tbody>${samples.map((sample) => `<tr><td>${escapeHtml(new Date(sample.sampled_at).toLocaleString("en-US"))}</td><td>${statusStateBadge(sample.state)}</td><td>${escapeHtml(metricText(sample.metrics || {}, ["used_bytes", "used_capacity_bytes", "capacity_bytes"], ["used_percent", "capacity_utilization_percent"]))}</td><td>${statusPorts(sample.metrics || {}).length || "—"}</td><td>${escapeHtml(sample.error || "—")}</td></tr>`).join("")}</tbody></table></div>` : `<p class="muted">No samples in the selected period.</p>`;
  } catch (error) { toast(error.message, true); }
}

function startStatusPolling() {
  clearInterval(state.statusPoller);
  state.statusPoller = setInterval(() => { if ($("#page-status")?.classList.contains("active")) loadStatus(); }, 15000);
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
    $$(".timeline-step").forEach((element, index) => {
      const details = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = "Technical details";
      const output = document.createElement("pre");
      output.textContent = JSON.stringify(workflow.steps[index].details || {}, null, 2);
      details.append(summary, output);
      element.querySelector("div")?.append(details);
    });
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
  $("#logoutButton").addEventListener("click", async () => { clearInterval(state.statusPoller); state.statusPoller = null; await api("/api/auth/logout", { method: "POST" }); showLogin(); });
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
  $("#resourceType").addEventListener("change", updateResourceType);
  $("#storageId").addEventListener("change", updateStorageResourceDefaults);
  $("#syncPpdm").addEventListener("click", syncPpdm);
  $("#dataDomain").addEventListener("change", updateDdDependentOptions);
  $("#backupMode").addEventListener("change", updateBackupMode);
  $("#existingPolicy").addEventListener("change", updatePolicySummary);
  $("#dryRun").addEventListener("change", () => { $("#submitHint").textContent = $("#dryRun").checked ? "The dry-run generates the plan without modifying infrastructure." : "LIVE mode: real changes will be executed."; });
  $("#provisionForm").addEventListener("submit", submitProvision);
  $("#refreshWorkflows").addEventListener("click", loadWorkflows);
  $("#collectStatus").addEventListener("click", async () => {
    const button = $("#collectStatus"); button.disabled = true; button.textContent = "Collecting...";
    await loadStatus({ collect: true }); button.disabled = false; button.textContent = "Collect now";
  });
  $("#refreshStatus").addEventListener("click", () => loadStatus());
  $("#statusHistoryTarget").addEventListener("change", loadStatusHistory);
  $("#statusHistoryRange").addEventListener("change", loadStatusHistory);
  document.addEventListener("click", (event) => { const target = event.target.closest(".workflow-open"); if (target) openWorkflow(Number(target.dataset.id)); });
}

async function bootstrap() {
  bindEvents(); updateBackupMode(); updateResourceType();
  try { const auth = await api("/api/auth/status"); if (auth.authenticated) { showApp(); await loadAll(); startPolling(); } else showLogin(); }
  catch (_) { showLogin(); }
}

document.addEventListener("DOMContentLoaded", bootstrap);
