const token = document.querySelector("meta[name='iteraforge-token']").content;
let tabs = [];
let activeTab = null;
let activeTabRuntime = null;
let activeTabScripts = [];
let activeTabStyle = null;
let activeTabCleanup = null;

async function api(path, options = {}) {
  const headers = {"x-iteraforge-token": token, ...(options.headers || {})};
  if (options.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  const response = await fetch(path, {...options, headers});
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

function showView(id) {
  document.querySelectorAll(".view").forEach(view => view.classList.remove("active"));
  document.querySelectorAll(".nav-item").forEach(item => item.classList.toggle("active", item.dataset.view === id));
  document.getElementById(id).classList.add("active");
}

function toast(message) {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 2400);
}

async function loadTabs() {
  const data = await api("/api/tabs");
  tabs = data.tabs.filter(tab => !tab.invalid);
  const nav = document.getElementById("tab-nav");
  nav.innerHTML = "";
  const select = document.getElementById("existing-tab");
  select.innerHTML = "";
  for (const tab of tabs) {
    const button = document.createElement("button");
    button.className = "nav-item";
    button.textContent = tab.title;
    button.dataset.tabId = tab.id;
    button.addEventListener("click", () => openTab(tab.id));
    nav.append(button);
    const option = document.createElement("option");
    option.value = tab.id;
    option.textContent = tab.title;
    select.append(option);
  }
}

async function openTab(tabId) {
  activeTab = tabs.find(tab => tab.id === tabId);
  if (!activeTab) return;
  showView("tab-view");
  document.getElementById("tab-title").textContent = activeTab.title;
  const payload = await api(`/api/tabs/${tabId}/render`);
  mountTab(payload);
}

function mountTab(payload) {
  cleanupActiveTab();
  const mount = document.getElementById("tab-mount");
  mount.replaceChildren();
  const host = document.createElement("div");
  host.className = "direct-tab-host";
  const style = document.createElement("style");
  style.dataset.iteraforgeTabStyle = payload.manifest?.id || "";
  style.textContent = payload.css || "";
  const container = document.createElement("div");
  container.className = "tab-document";
  container.innerHTML = payload.html_body || "";
  document.head.append(style);
  activeTabStyle = style;
  host.append(container);
  mount.append(host);
  activeTabRuntime = createTabRuntime(payload.runtime_token);
  window.IteraForgeRuntime = activeTabRuntime;
  window.IteraForgeTabRoot = container;
  window.IteraForgeTabManifest = payload.manifest;
  window.IteraForgeBaseApi = api;
  bindDeclarativeTab(container, activeTabRuntime);
  executeEntrypointScripts(container, payload);
  executeTabScript(payload, container);
  captureTabCleanup();
}

function cleanupActiveTab() {
  if (typeof activeTabCleanup === "function") {
    try {
      activeTabCleanup();
    } catch (error) {
      console.error(error);
    }
  }
  for (const script of activeTabScripts) script.remove();
  activeTabScripts = [];
  if (activeTabStyle) activeTabStyle.remove();
  activeTabStyle = null;
  activeTabCleanup = null;
  delete window.IteraForgeRuntime;
  delete window.IteraForgeTabRoot;
  delete window.IteraForgeTabManifest;
  delete window.IteraForgeBaseApi;
  delete window.IteraForgeTabCleanup;
}

function executeEntrypointScripts(container, payload) {
  for (const script of [...container.querySelectorAll("script")]) {
    executeScriptElement(script, payload);
  }
}

function executeTabScript(payload, container) {
  if (!payload.js?.trim() || entrypointLoadsAppJs(container)) return;
  const script = document.createElement("script");
  script.textContent = `${payload.js}\n//# sourceURL=iteraforge-tab-${payload.manifest?.id || "unknown"}.js`;
  script.addEventListener("error", event => {
    console.error("Tab script failed", event.error || event.message);
    toast("Tab script failed");
  });
  document.body.append(script);
  activeTabScripts.push(script);
  captureTabCleanup();
}

function executeScriptElement(original, payload) {
  const script = document.createElement("script");
  for (const attr of original.attributes) {
    if (attr.name.toLowerCase() === "src") continue;
    script.setAttribute(attr.name, attr.value);
  }
  if (original.src || original.getAttribute("src")) {
    const originalSrc = original.getAttribute("src");
    script.dataset.iteraforgeOriginalSrc = originalSrc || "";
    script.src = tabAssetUrl(originalSrc, payload);
    script.async = false;
  } else {
    script.textContent = original.textContent;
  }
  script.addEventListener("load", captureTabCleanup);
  script.addEventListener("error", event => {
    console.error("Tab script failed", event.error || event.message);
    toast("Tab script failed");
  });
  original.replaceWith(script);
  activeTabScripts.push(script);
}

function tabAssetUrl(src, payload) {
  if (!src) return "";
  const trimmed = src.trim();
  if (/^(?:[a-z][a-z0-9+.-]*:|\/\/|\/)/i.test(trimmed)) return trimmed;
  const asset = new URL(trimmed, "http://iteraforge.local/");
  const normalized = asset.pathname.replace(/^\/+/, "");
  const params = new URLSearchParams(asset.search);
  if (payload.asset_version) params.set("v", payload.asset_version);
  const query = params.toString();
  return `/tabs/${encodeURIComponent(payload.manifest.id)}/${normalized}${query ? `?${query}` : ""}`;
}

function entrypointLoadsAppJs(container) {
  return [...container.querySelectorAll("script[src]")].some(script => {
    const src = script.dataset.iteraforgeOriginalSrc || script.getAttribute("src") || "";
    if (/^(?:[a-z][a-z0-9+.-]*:|\/\/|\/)/i.test(src.trim())) return false;
    return new URL(src.trim(), "http://iteraforge.local/").pathname.replace(/^\/+/, "") === "app.js";
  });
}

function captureTabCleanup() {
  activeTabCleanup = typeof window.IteraForgeTabCleanup === "function" ? window.IteraForgeTabCleanup : activeTabCleanup;
}

function createTabRuntime(runtimeToken) {
  async function runtimeRequest(path, options = {}) {
    const headers = {Authorization: `Bearer ${runtimeToken}`, ...(options.headers || {})};
    if (options.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
    const response = await fetch(path, {...options, headers});
    if (!response.ok) throw new Error(await response.text());
    return response.json();
  }
  const postJson = (path, payload) => runtimeRequest(path, {method: "POST", body: JSON.stringify(payload || {})});
  return {
    listRecords: collection => runtimeRequest(`/api/runtime/records/${encodeURIComponent(collection)}`).then(data => data.records),
    createRecord: (collection, data) => runtimeRequest(`/api/runtime/records/${encodeURIComponent(collection)}`, {method: "POST", body: JSON.stringify({data})}),
    updateRecord: (collection, id, data) => runtimeRequest(`/api/runtime/records/${encodeURIComponent(collection)}/${encodeURIComponent(id)}`, {method: "PUT", body: JSON.stringify({data})}),
    deleteRecord: (collection, id) => runtimeRequest(`/api/runtime/records/${encodeURIComponent(collection)}/${encodeURIComponent(id)}`, {method: "DELETE"}),
    query: query => runtimeRequest("/api/runtime/query", {method: "POST", body: JSON.stringify(query)}),
    connectors: {
      capabilities: () => runtimeRequest("/api/runtime/connectors/capabilities"),
      web: {
        request: payload => postJson("/api/runtime/connectors/web", payload),
      },
      shell: {
        run: payload => postJson("/api/runtime/connectors/shell", payload),
      },
      ai: {
        prompt: payload => postJson("/api/runtime/connectors/ai", payload),
      },
      cache: {
        get: payload => postJson("/api/runtime/connectors/cache/get", payload),
        set: payload => postJson("/api/runtime/connectors/cache/set", payload),
        delete: payload => postJson("/api/runtime/connectors/cache/delete", payload),
        clear: payload => postJson("/api/runtime/connectors/cache/clear", payload),
      },
    },
  };
}

function bindDeclarativeTab(root, runtime) {
  root.addEventListener("submit", async event => {
    const form = event.target.closest("form[data-action][data-collection]");
    if (!form) return;
    event.preventDefault();
    const collection = form.dataset.collection;
    const data = Object.fromEntries(new FormData(form).entries());
    try {
      if (form.dataset.action === "create") {
        await runtime.createRecord(collection, data);
        form.reset();
      } else if (form.dataset.action === "update") {
        const id = form.dataset.recordId || data.id;
        if (id) await runtime.updateRecord(collection, id, data);
      }
      await refreshDeclarativeLists(root, runtime);
    } catch (error) {
      toast("Tab action failed");
      console.error(error);
    }
  });
  root.addEventListener("click", async event => {
    const button = event.target.closest("[data-action='delete'][data-collection][data-record-id]");
    if (!button) return;
    try {
      await runtime.deleteRecord(button.dataset.collection, button.dataset.recordId);
      await refreshDeclarativeLists(root, runtime);
    } catch (error) {
      toast("Tab action failed");
      console.error(error);
    }
  });
  refreshDeclarativeLists(root, runtime);
}

async function refreshDeclarativeLists(root, runtime) {
  const lists = [...root.querySelectorAll("[data-render-list]")].filter(list => {
    const parentList = list.parentElement?.closest("[data-render-list]");
    return !parentList || !root.contains(parentList);
  });
  await Promise.all(lists.map(async list => {
    const collection = list.dataset.renderList;
    const filters = listFilters(list);
    const records = Object.keys(filters).length
      ? await runtime.query({collection, filters})
      : await runtime.listRecords(collection);
    await renderRecordList(list, collection, records, runtime);
  }));
}

async function renderRecordList(list, collection, records, runtime) {
  const template = list.querySelector("template[data-record-template]");
  const empty = list.querySelector("[data-empty-state]");
  const rendered = list.querySelector("[data-rendered-records]") || document.createElement("div");
  rendered.dataset.renderedRecords = "";
  rendered.replaceChildren();
  if (!rendered.parentElement) list.append(rendered);
  if (empty) empty.hidden = records.length > 0;
  for (const record of records) {
    if (template) {
      const wrapper = document.createElement("div");
      wrapper.innerHTML = fillTemplate(template.innerHTML, record);
      for (const child of [...wrapper.childNodes]) rendered.append(child);
    } else {
      rendered.append(defaultRecordElement(collection, record));
    }
  }
  await refreshDeclarativeLists(rendered, runtime);
}

function fillTemplate(template, record) {
  return template.replace(/\{\{\s*([a-zA-Z0-9_.-]+)\s*\}\}|\{\s*([a-zA-Z0-9_.-]+)\s*\}/g, (_match, doubleKey, singleKey) => {
    const key = doubleKey || singleKey;
    if (key === "id") return escapeHtml(record.id);
    if (key.startsWith("data.")) return escapeHtml(record.data[key.slice(5)] ?? "");
    return escapeHtml(record[key] ?? "");
  });
}

function listFilters(list) {
  const filters = {};
  for (const [key, value] of Object.entries(list.dataset)) {
    if (!key.startsWith("filter")) continue;
    const field = key.slice("filter".length);
    if (!field) continue;
    const normalized = field.charAt(0).toLowerCase() + field.slice(1);
    filters[normalized] = value;
  }
  return filters;
}

function defaultRecordElement(collection, record) {
  const article = document.createElement("article");
  article.className = "record";
  const body = document.createElement("pre");
  body.textContent = JSON.stringify(record.data, null, 2);
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = "Delete";
  button.dataset.action = "delete";
  button.dataset.collection = collection;
  button.dataset.recordId = record.id;
  article.append(body, button);
  return article;
}

async function loadJobs() {
  const data = await api("/api/tasks");
  document.getElementById("jobs").innerHTML = data.jobs.map(job => `
    <article class="job" data-job-id="${escapeHtml(job.id)}">
      <strong>${escapeHtml(job.mode)} ${escapeHtml(job.tab_id || "")}</strong>
      <div>Status: ${escapeHtml(job.status)} | Repairs: ${job.repair_attempts || 0}</div>
      <div>${escapeHtml(job.prompt || "")}</div>
      ${job.changed_files?.length ? `<div>Files: ${job.changed_files.map(escapeHtml).join(", ")}</div>` : ""}
      ${job.validation_errors?.length ? `<pre class="errors">${escapeHtml(job.validation_errors.join("\\n"))}</pre>` : ""}
      ${job.validation_warnings?.length ? `<pre class="warnings">${escapeHtml(job.validation_warnings.join("\\n"))}</pre>` : ""}
      ${job.output?.length ? `<pre>${escapeHtml(job.output.join(""))}</pre>` : ""}
      ${["queued", "running"].includes(job.status) ? `<button class="secondary cancel-job" data-job-id="${escapeHtml(job.id)}" type="button">Cancel</button>` : ""}
    </article>`).join("") || "No jobs yet.";
}

async function loadActivity() {
  const data = await api("/api/activity");
  document.getElementById("activity-list").innerHTML = data.activity.map(event => `
    <article class="event">
      <strong>${escapeHtml(event.kind)}</strong>
      <div>${escapeHtml(event.timestamp)} ${event.tab_id ? " | " + escapeHtml(event.tab_id) : ""}</div>
      <div>${escapeHtml(event.summary)}</div>
      <pre>${escapeHtml(JSON.stringify(event.details || {}, null, 2))}</pre>
    </article>`).join("") || "No activity yet.";
}

async function loadSettings() {
  const data = await api("/api/settings");
  const form = document.getElementById("settings-form");
  for (const [key, value] of Object.entries(data)) {
    const input = form.elements[key];
    if (!input || key === "api_key") continue;
    if (input.type === "checkbox") input.checked = Boolean(value);
    else if (Array.isArray(value)) input.value = value.join(" ");
    else input.value = value ?? "";
  }
  document.getElementById("settings-status").innerHTML = `
    <div>OpenCode config path: <code>${escapeHtml(data.opencode_config_path || "")}</code></div>
    <div>API credential configured: <strong>${data.api_key_configured ? "yes" : "no"}</strong></div>
    <div>Imported OpenCode authentication: <strong>${data.opencode_auth_configured ? "yes" : "no"}</strong></div>`;
  await loadProviders(data.agent_provider);
}

async function loadProviders(activeProvider) {
  const data = await api("/api/settings/providers");
  const select = document.getElementById("agent-provider");
  select.innerHTML = "";
  for (const provider of data.providers) {
    const option = document.createElement("option");
    option.value = provider.id;
    option.textContent = provider.title;
    option.selected = provider.id === activeProvider;
    select.append(option);
  }
  document.getElementById("provider-status").innerHTML = data.providers.map(provider => `
    <article class="event">
      <strong>${escapeHtml(provider.title)}</strong>
      <div>CLI: ${provider.available ? "available" : "missing"} | Config: ${provider.configured ? provider.config_source : "not found"}</div>
      <code>${escapeHtml(provider.config_path)}</code>
    </article>`).join("") || "No providers registered.";
}

async function loadTabStore() {
  const data = await api("/api/tab-store");
  document.getElementById("tab-store-list").innerHTML = data.tabs.map(tab => `
    <article class="event">
      <strong>${escapeHtml(tab.title || tab.template_id)}</strong>
      <div>${escapeHtml(tab.description || "")}</div>
      ${tab.invalid ? `<pre class="errors">${escapeHtml(tab.error || "Invalid template")}</pre>` : `<button class="install-template" data-template-id="${escapeHtml(tab.template_id)}" type="button">Install</button>`}
    </article>`).join("") || "No community tabs are bundled yet.";
}

document.getElementById("nav").addEventListener("click", event => {
  const button = event.target.closest("button[data-view]");
  if (button) showView(button.dataset.view);
});
document.getElementById("task-mode").addEventListener("change", event => {
  document.getElementById("existing-tab-label").hidden = event.target.value !== "modify";
});
document.getElementById("task-form").addEventListener("submit", async event => {
  event.preventDefault();
  const formEl = event.currentTarget;
  const submitButton = formEl.querySelector("button[type='submit']");
  const originalText = submitButton.textContent;
  submitButton.disabled = true;
  submitButton.textContent = "Submitting...";
  const form = new FormData(formEl);
  const body = {mode: form.get("mode"), prompt: form.get("prompt")};
  if (body.mode === "modify") body.tab_id = form.get("tab_id");
  try {
    const result = await api("/api/tasks", {method: "POST", body: JSON.stringify(body)});
    await loadJobs();
    if (result.duplicate) {
      toast("That task is already queued or running");
      highlightJob(result.existing_job_id || result.id);
    } else {
      formEl.reset();
      document.getElementById("existing-tab-label").hidden = formEl.elements.mode.value !== "modify";
      toast("Task queued");
      highlightJob(result.id);
    }
  } catch (error) {
    toast("Task submission failed");
    console.error(error);
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = originalText;
  }
});
document.getElementById("settings-form").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const body = {};
  for (const element of form.elements) {
    if (!element.name || element.tagName === "BUTTON") continue;
    if (element.type === "checkbox") body[element.name] = element.checked;
    else if (element.name === "safe_args") body[element.name] = element.value.split(" ").filter(Boolean);
    else if (element.type === "number") body[element.name] = element.value ? Number(element.value) : null;
    else if (element.value) body[element.name] = element.value;
  }
  await api("/api/settings", {method: "PUT", body: JSON.stringify(body)});
  form.elements.api_key.value = "";
  toast("Settings saved");
  await loadSettings();
});
document.getElementById("import-opencode").addEventListener("click", async () => {
  const result = await api("/api/settings/import-opencode", {method: "POST", body: JSON.stringify({overwrite: false})});
  toast(result.imported ? "OpenCode config imported" : "No new OpenCode config imported");
  await loadSettings();
});
document.getElementById("import-providers").addEventListener("click", async () => {
  await api("/api/settings/providers/import", {method: "POST", body: JSON.stringify({overwrite: false})});
  toast("Provider configs imported");
  await loadSettings();
});
document.getElementById("refresh-tab-store").addEventListener("click", loadTabStore);
document.getElementById("tab-store-list").addEventListener("click", async event => {
  const button = event.target.closest(".install-template");
  if (!button) return;
  button.disabled = true;
  try {
    const result = await api(`/api/tab-store/${encodeURIComponent(button.dataset.templateId)}/install`, {method: "POST", body: JSON.stringify({})});
    toast("Tab installed");
    await loadTabs();
    await openTab(result.tab_id);
  } catch (error) {
    toast("Install failed");
    console.error(error);
  } finally {
    button.disabled = false;
  }
});
document.getElementById("refresh-jobs").addEventListener("click", loadJobs);
document.getElementById("refresh-activity").addEventListener("click", loadActivity);
document.getElementById("reload-tab").addEventListener("click", () => activeTab && openTab(activeTab.id));
document.getElementById("jobs").addEventListener("click", async event => {
  const button = event.target.closest(".cancel-job");
  if (!button) return;
  button.disabled = true;
  try {
    await api(`/api/tasks/${button.dataset.jobId}/cancel`, {method: "POST"});
    toast("Job cancellation requested");
    await loadJobs();
  } catch (error) {
    toast("Cancel failed");
    console.error(error);
  }
});

function highlightJob(jobId) {
  if (!jobId) return;
  const el = document.querySelector(`[data-job-id="${CSS.escape(jobId)}"]`);
  if (!el) return;
  el.classList.add("highlight");
  el.scrollIntoView({block: "nearest"});
  setTimeout(() => el.classList.remove("highlight"), 1800);
}

function listenEvents() {
  const source = new EventSource("/api/events");
  source.addEventListener("message", async event => {
    const payload = JSON.parse(event.data);
    if (payload.type === "tabs-changed") {
      await loadTabs();
      if (activeTab && activeTab.id === payload.tab_id) toast("Tab update available; reload when ready.");
      else toast("Tabs updated");
    }
    if (payload.type === "job-changed") await loadJobs();
  });
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[char]));
}

loadTabs();
loadJobs();
loadActivity();
loadSettings();
loadTabStore();
listenEvents();
