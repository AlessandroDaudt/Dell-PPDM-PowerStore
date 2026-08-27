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
    throw new Error("Sua sessão expirou. Entre novamente.");
  }
  if (!response.ok) {
    let detail = `Erro HTTP ${response.status}`;
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
  home: ["CONTROL PLANE", "Visão geral"], inventory: ["CONFIGURAÇÃO", "Inventário"],
  provision: ["ORQUESTRAÇÃO", "Nova LUN"], workflows: ["OBSERVABILIDADE", "Execuções"],
  docs: ["OPERAÇÃO", "Documentação"],
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
  const labels = { COMPLETED: "CONCLUÍDO", FAILED: "FALHOU", RUNNING: "EM EXECUÇÃO", PENDING: "PENDENTE" };
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
    ["Hosts", counts.HOST || 0, "Servidores físicos", "#667085"],
    ["Brocade", counts.BROCADE || 0, "Switches de fabric", "#805ad5"],
    ["PPDM", counts.PPDM || 0, "Gerenciadores de proteção", "#16a1ae"],
  ];
  $("#metrics").innerHTML = cards.map(([name, count, caption, color]) =>
    `<article class="metric" style="--metric-color:${color}"><span>${name}</span><strong>${count}</strong><small>${caption}</small></article>`
  ).join("");
  const readyTypes = ["POWERSTORE", "HOST", "BROCADE", "PPDM"].filter((type) => counts[type] > 0).length;
  const percent = readyTypes * 25;
  $("#readinessBar").style.width = `${percent}%`;
  $("#heroReadiness").textContent = percent === 100 ? "Pronto para orquestrar" : `${readyTypes} de 4 domínios prontos`;
  $("#readinessText").textContent = percent === 100 ? "Inventário mínimo completo. Comece por um dry-run." : "Cadastre os quatro domínios para iniciar.";
  const recent = state.dashboard.recent_workflows || [];
  $("#recentWorkflows").className = recent.length ? "compact-list" : "compact-list empty-state";
  $("#recentWorkflows").innerHTML = recent.length ? recent.map((workflow) => `
    <button class="compact-item text-button workflow-open" data-id="${workflow.id}">
      ${statusBadge(workflow.status)}<span><strong>${escapeHtml(workflow.request.volume?.name || "LUN")}</strong><small>#${workflow.id} · ${workflow.dry_run ? "dry-run" : "live"}</small></span><span>Detalhes →</span>
    </button>`).join("") : "Nenhuma execução registrada.";
}

function renderInventory() {
  const filtered = state.equipment.filter((item) => state.inventoryFilter === "ALL" || item.type === state.inventoryFilter);
  const root = $("#inventoryGrid");
  if (!filtered.length) {
    root.innerHTML = `<div class="empty-state">Nenhum equipamento neste filtro.</div>`;
    return;
  }
  root.innerHTML = filtered.map((item) => `
    <article class="equipment-card">
      <div class="equipment-card-head"><div><span class="type-badge ${item.type}">${item.type}</span><h4>${escapeHtml(item.name)}</h4><p>${escapeHtml(item.management_address || "Sem endpoint de rede")}${item.api_port ? `:${item.api_port}` : ""}</p></div><span title="TLS">${item.verify_ssl ? "🔒" : "⚠"}</span></div>
      <div class="wwn-list">${item.wwns.length ? item.wwns.slice(0, 5).map((wwn) => `<div class="wwn-row"><span>${escapeHtml(wwn.value)}</span><span>${escapeHtml(wwn.fabric)} · ${escapeHtml(wwn.role)}</span></div>`).join("") : `<span class="muted">Nenhum WWN cadastrado</span>`}${item.wwns.length > 5 ? `<small>+${item.wwns.length - 5} WWNs</small>` : ""}</div>
      <div class="card-actions"><button data-action="test" data-id="${item.id}">Testar</button><button data-action="edit" data-id="${item.id}">Editar</button><button class="danger" data-action="delete" data-id="${item.id}">Excluir</button></div>
    </article>`).join("");
}

function optionList(type, placeholder = "Selecione") {
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
    const items = state.equipment.filter((item) => item.type === type);
    return items.length ? items.map((item) => `<label class="choice"><input type="checkbox" name="${cssName}" value="${item.id}" /><div><strong>${escapeHtml(item.name)}</strong><small>${item.wwns.length} WWN(s) · ${escapeHtml(item.settings.fabric || item.settings.os_type || "")}</small></div></label>`).join("") : `<div class="empty-state">Cadastre ${type === "HOST" ? "um host" : "um switch"}.</div>`;
  };
  $("#hostChoices").innerHTML = choices("HOST", "hostChoice");
  $("#brocadeChoices").innerHTML = choices("BROCADE", "brocadeChoice");
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
  const hostless = powermax || nas;
  $("#zoningEnabled").checked = !hostless;
  $("#zoningEnabled").disabled = hostless;
  $("#zoningEnabled").closest(".inline-options").classList.toggle("disabled-section", hostless);
  $("#hostChoices").closest(".selection-columns").classList.toggle("disabled-section", hostless);
  if (powermax && $("#backupMode").value !== "NONE") {
    $("#backupMode").value = "NONE";
    updateBackupMode();
  } else if (nas && $("#backupMode").value === "NONE") {
    $("#backupMode").value = "EXISTING_POLICY";
    updateBackupMode();
  }
}

function updateStorageResourceDefaults() {
  const selected = $("#storageId").selectedOptions[0];
  if (selected?.dataset.type === "POWERMAX") $("#resourceType").value = "POWERMAX_STORAGE_GROUP";
  else if (["POWERSTORE_NAS", "POWERSCALE"].includes(selected?.dataset.type)) $("#resourceType").value = "NAS_SHARE";
  else if (["POWERMAX_STORAGE_GROUP", "NAS_SHARE", "NAS_DATA"].includes($("#resourceType").value)) $("#resourceType").value = "VOLUME";
  updateResourceType();
}

function resetEquipmentForm() {
  $("#equipmentForm").reset();
  $("#equipmentId").value = "";
  $("#equipmentPort").value = "443";
  $("#equipmentFid").value = "128";
  $("#equipmentActiveConfig").value = "SANFLOW_CFG";
  $("#equipmentDialogTitle").textContent = "Novo equipamento";
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
  if (!$("#equipmentId").value) $("#equipmentPort").value = type === "PPDM" ? "8443" : type === "POWERSCALE" ? "8080" : "443";
}

function openEquipment(item = null) {
  resetEquipmentForm();
  if (item) {
    $("#equipmentDialogTitle").textContent = `Editar ${item.name}`;
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
    $("#equipmentSymmetrixId").value = item.settings.symmetrix_id || "";
    $("#equipmentApiVersion").value = item.settings.api_version || "100";
    $("#equipmentDefaultSrp").value = item.settings.default_srp_id || "";
    $("#equipmentDefaultSlo").value = item.settings.default_slo_id || "";
    $("#equipmentOnefsApiVersion").value = item.settings.api_version || "3";
    $("#equipmentUnityApiVersion").value = item.settings.api_version || "5.2";
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
  } : type === "HOST" ? { os_type: $("#equipmentOs").value, powerstore_host_id: $("#equipmentHostId").value || null } : type === "POWERMAX" ? {
    symmetrix_id: $("#equipmentSymmetrixId").value || null,
    api_version: $("#equipmentApiVersion").value || "100",
    default_srp_id: $("#equipmentDefaultSrp").value || null,
    default_slo_id: $("#equipmentDefaultSlo").value || null,
  } : type === "POWERSCALE" ? {
    api_version: $("#equipmentOnefsApiVersion").value || "3",
  } : type === "UNITY" ? {
    api_version: $("#equipmentUnityApiVersion").value || "5.2",
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
    $("#equipmentDialog").close(); toast("Equipamento salvo com sucesso."); await loadAll();
  } catch (error) { $("#equipmentError").textContent = error.message; }
}

async function handleInventoryAction(event) {
  const button = event.target.closest("button[data-action]"); if (!button) return;
  const item = state.equipment.find((entry) => entry.id === Number(button.dataset.id)); if (!item) return;
  if (button.dataset.action === "edit") openEquipment(item);
  if (button.dataset.action === "test") {
    button.disabled = true; button.textContent = "Testando…";
    try { const result = await api(`/api/equipment/${item.id}/test`, { method: "POST" }); toast(`${item.name}: ${result.message || result.version || "conexão válida"}`); }
    catch (error) { toast(error.message, true); }
    finally { button.disabled = false; button.textContent = "Testar"; }
  }
  if (button.dataset.action === "delete" && confirm(`Excluir ${item.name} do inventário?`)) {
    try { await api(`/api/equipment/${item.id}`, { method: "DELETE" }); toast("Equipamento removido."); await loadAll(); }
    catch (error) { toast(error.message, true); }
  }
}

function fillSelect(id, items, label, placeholder) {
  const element = $(id); element.innerHTML = `<option value="">${placeholder}</option>` + (items || []).map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(label(item))}</option>`).join("");
}

async function syncPowerStore() {
  const id = $("#storageId").value; if (!id) return toast("Selecione um PowerStore.", true);
  const button = $("#syncPowerStore"); button.disabled = true; button.textContent = "Sincronizando…";
  try {
    const type = $("#storageId").selectedOptions[0]?.dataset.type;
    const endpoint = type === "POWERSCALE" ? "powerscale" : type === "UNITY" ? "unity" : "powerstore";
    state.powerstoreOptions = await api(`/api/integrations/${endpoint}/${id}/options`);
    fillSelect("#applianceId", state.powerstoreOptions.appliances, (item) => item.name || item.service_tag || item.id, "Seleção automática");
    fillSelect("#performancePolicy", state.powerstoreOptions.performance_policies, (item) => item.name || item.id, "Padrão do array");
    fillSelect("#localProtectionPolicy", state.powerstoreOptions.protection_policies, (item) => item.name || item.id, "Sem política local");
    fillSelect("#nasServerId", state.powerstoreOptions.nas_servers, (item) => item.name || item.id, "Automático");
    fillSelect("#nasFileSystemId", state.powerstoreOptions.file_systems, (item) => item.name || item.id, "Automático");
    toast("Opções do PowerStore atualizadas em tempo real.");
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; button.textContent = "↻ Sincronizar opções"; }
}

function updateDdDependentOptions() {
  const selected = (state.ppdmOptions.data_domains || []).find((item) => item.id === $("#dataDomain").value);
  const interfaces = selected?.details?.dataDomain?.preferredInterfaces || [];
  fillSelect("#ddInterface", interfaces.map((item) => ({ id: item.networkName, ...item })), (item) => `${item.networkName}${item.purposes ? ` · ${item.purposes.join(", ")}` : ""}`, "Automática");
  const units = (state.ppdmOptions.storage_units || []).filter((unit) => !selected || unit.storageSystem?.id === selected.id || unit.storageSystemId === selected.id);
  fillSelect("#storageUnit", units, (item) => item.name || item.id, "Auto provisionar");
}

async function syncPpdm() {
  const id = $("#ppdmId").value; if (!id) return toast("Selecione um PPDM.", true);
  const button = $("#syncPpdm"); button.disabled = true; button.textContent = "Consultando…";
  try {
    const nas = ["NAS_SHARE", "NAS_DATA"].includes($("#resourceType").value);
    state.ppdmOptions = await api(`/api/integrations/ppdm/${id}/${nas ? "nas-options" : "options"}`);
    fillSelect("#existingPolicy", state.ppdmOptions.policies, (item) => item.name || item.id, "Selecione uma política");
    fillSelect("#dataDomain", state.ppdmOptions.data_domains, (item) => item.name || item.id, "Selecione um Data Domain");
    updateDdDependentOptions();
    fillSelect("#nasProtectionEngine", state.ppdmOptions.protection_engines, (item) => item.name || item.id, "Automático");
    updateBackupMode();
    toast(`PPDM ${state.ppdmOptions.version}: Data Domains, storage units e políticas atualizados.`);
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; button.textContent = "↻ Buscar Data Domains e rotinas"; }
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
  root.innerHTML = `<strong>Política lida em tempo real</strong><span>Objetivos: ${escapeHtml(types.join(", ") || "não informados")}</span><span>Rotinas: ${escapeHtml([...new Set(schedules)].join(", ") || "não informadas")}</span><span>Retenções: ${escapeHtml(retentions.join(", ") || "não informadas")}</span><span>Destinos DD: ${escapeHtml([...new Set(targets)].join(", ") || "automático")}</span>`;
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
    $("#encryptedBackup").title = "O contrato v3 não expõe encrypted no objeto de política.";
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
  catch (_) { return toast("O payload avançado não é um JSON válido.", true); }
  const resourceType = $("#resourceType").value;
  let members = [];
  if (resourceType === "VOLUME_GROUP") {
    try { members = JSON.parse($("#groupMembers").value || "[]"); }
    catch (_) { return toast("A lista de volumes membros não é um JSON válido.", true); }
  }
  const body = {
    storage_id: Number($("#storageId").value), ppdm_id: $("#ppdmId").value ? Number($("#ppdmId").value) : null,
    host_ids: checkedValues("hostChoice"), brocade_ids: checkedValues("brocadeChoice"), dry_run: $("#dryRun").checked,
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
      nas_protection_engine_id: resourceType.startsWith("NAS_") ? $("#nasProtectionEngine").value || null : null,
    },
  };
  if (!body.dry_run && !confirm("Modo LIVE: este fluxo criará volume, mappings, zones e proteção. Continuar?")) return;
  const submit = $("#provisionForm button[type=submit]"); submit.disabled = true; submit.textContent = "Iniciando…";
  try {
    const workflow = await api("/api/workflows", { method: "POST", body });
    toast(`Workflow #${workflow.id} iniciado.`); navigate("workflows"); await loadWorkflows(); openWorkflow(workflow.id); startPolling();
  } catch (error) { toast(error.message, true); }
  finally { submit.disabled = false; submit.textContent = "Executar fluxo completo →"; }
}

async function loadWorkflows() {
  try { state.workflows = await api("/api/workflows?limit=100"); renderWorkflows(); }
  catch (error) { toast(error.message, true); }
}

function renderWorkflows() {
  const root = $("#workflowList");
  if (!state.workflows.length) return root.innerHTML = `<div class="empty-state">Nenhum workflow executado.</div>`;
  root.innerHTML = state.workflows.map((workflow) => `
    <article class="workflow-card"><strong>#${workflow.id}</strong><div><h4>${escapeHtml(workflow.request.volume?.name || "LUN")}</h4><p>${workflow.dry_run ? "DRY-RUN" : "LIVE"} · ${escapeHtml(workflow.current_step || "Finalizado")}</p></div><div class="step-mini">${workflow.steps.map((step) => `<i class="${step.status}" title="${escapeHtml(step.name)}"></i>`).join("")}</div><div>${statusBadge(workflow.status)} <button class="button compact ghost workflow-open" data-id="${workflow.id}">Detalhes</button></div></article>`).join("");
}

async function openWorkflow(id) {
  try {
    const workflow = await api(`/api/workflows/${id}`);
    $("#workflowDialogTitle").textContent = `Workflow #${workflow.id} · ${workflow.request.volume?.name || "LUN"}`;
    $("#workflowDetail").innerHTML = `${workflow.error ? `<div class="error-box">${escapeHtml(workflow.error)}</div>` : ""}<div class="timeline">${workflow.steps.map((step) => `<article class="timeline-step"><i class="timeline-dot ${step.status}"></i><div><h4>${escapeHtml(step.name)} · ${escapeHtml(step.status)}</h4><p>${escapeHtml(step.message || "Aguardando execução")}</p></div></article>`).join("")}</div>`;
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
  $("#resourceType").addEventListener("change", updateResourceType);
  $("#storageId").addEventListener("change", updateStorageResourceDefaults);
  $("#syncPpdm").addEventListener("click", syncPpdm);
  $("#dataDomain").addEventListener("change", updateDdDependentOptions);
  $("#backupMode").addEventListener("change", updateBackupMode);
  $("#existingPolicy").addEventListener("change", updatePolicySummary);
  $("#dryRun").addEventListener("change", () => { $("#submitHint").textContent = $("#dryRun").checked ? "O dry-run gera o plano sem modificar a infraestrutura." : "Modo LIVE: mudanças reais serão executadas."; });
  $("#provisionForm").addEventListener("submit", submitProvision);
  $("#refreshWorkflows").addEventListener("click", loadWorkflows);
  document.addEventListener("click", (event) => { const target = event.target.closest(".workflow-open"); if (target) openWorkflow(Number(target.dataset.id)); });
}

async function bootstrap() {
  bindEvents(); updateBackupMode(); updateResourceType();
  try { const auth = await api("/api/auth/status"); if (auth.authenticated) { showApp(); await loadAll(); startPolling(); } else showLogin(); }
  catch (_) { showLogin(); }
}

document.addEventListener("DOMContentLoaded", bootstrap);
