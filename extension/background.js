const BRIDGE = "http://127.0.0.1:8765";
const ALARM_NAME = "linkedin-job-scan";

const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
const newRunId = () => (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`);
// LinkedIn adds these cursor values when opening the first result. They do not
// change the configured search, so they must not make a completed load fail.
const SEARCH_RUNTIME_PARAMS = new Set(["position", "pageNum"]);
const comparableUrl = (value) => {
  const parsed = new URL(value);
  parsed.hash = "";
  for (const parameter of SEARCH_RUNTIME_PARAMS) parsed.searchParams.delete(parameter);
  const parameters = [...parsed.searchParams.entries()]
    .sort(([name, content], [otherName, otherContent]) => (
      name.localeCompare(otherName) || content.localeCompare(otherContent)
    ));
  parsed.search = "";
  for (const [name, content] of parameters) parsed.searchParams.append(name, content);
  return parsed.href;
};
const sameUrl = (left, right) => {
  try {
    return comparableUrl(left) === comparableUrl(right);
  } catch {
    return left === right;
  }
};

async function bridgeFetch(path, options = {}) {
  // A stalled localhost request must not leave the MV3 worker permanently in
  // cycleRunning state. The next alarm can then retry and its failure is logged.
  const { timeoutMs = 10_000, ...fetchOptions } = options;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${BRIDGE}${path}`, {
      cache: "no-store",
      ...fetchOptions,
      signal: controller.signal,
      headers: { "Content-Type": "application/json", ...(fetchOptions.headers || {}) },
    });
    if (!response.ok) throw new Error(`Bridge HTTP ${response.status}`);
    return response.json();
  } finally {
    clearTimeout(timeout);
  }
}

function reportStatus(state, detail = {}) {
  // Telemetry must never hold the scan hostage. In particular, MV3 can keep a
  // localhost fetch pending while the browser profile is starting up.
  void bridgeFetch("/status", { method: "POST", body: JSON.stringify({ state, detail }) })
    .catch((error) => console.warn("No se pudo informar al bridge", state, error));
}

async function getSearchTab(url) {
  const tabs = await chrome.tabs.query({ url: ["https://www.linkedin.com/jobs/*"] });
  return tabs.length ? tabs[0] : chrome.tabs.create({ url, active: true });
}

function tabNavigationSnapshot(tab) {
  return {
    url: tab?.url || "",
    status: tab?.status || "unknown",
  };
}

async function waitForSearchNavigation(tabId, expectedUrl, diagnostics, timeoutMs = 45_000) {
  const tabMatches = (tab) => sameUrl(tab?.url || "", expectedUrl);
  const current = await chrome.tabs.get(tabId);
  diagnostics.before = tabNavigationSnapshot(current);
  if (tabMatches(current) && current.status === "complete") {
    diagnostics.matchedBy = "initial_check";
    diagnostics.completedAfterMs = 0;
    return { tab: current, diagnostics };
  }

  return new Promise((resolve, reject) => {
    let timeout;
    let pollTimer;
    let finished = false;
    const startedAt = Date.now();
    const observedUrls = new Set();
    const recordTab = (tab, source) => {
      diagnostics.last = tabNavigationSnapshot(tab);
      diagnostics.lastObservedBy = source;
      if (tab?.url) observedUrls.add(tab.url);
      diagnostics.observedUrls = [...observedUrls].slice(-4);
      return tabMatches(tab) && tab.status === "complete";
    };
    const finish = (error, tab, source) => {
      if (finished) return;
      finished = true;
      clearTimeout(timeout);
      clearTimeout(pollTimer);
      chrome.tabs.onUpdated.removeListener(onUpdated);
      diagnostics.completedAfterMs = Date.now() - startedAt;
      if (error) {
        error.navigationDiagnostics = diagnostics;
        reject(error);
      } else {
        diagnostics.matchedBy = source;
        resolve({ tab, diagnostics });
      }
    };
    const poll = async () => {
      if (finished) return;
      diagnostics.pollChecks += 1;
      try {
        const tab = await chrome.tabs.get(tabId);
        if (recordTab(tab, "poll")) {
          finish(null, tab, "poll");
          return;
        }
      } catch (error) {
        finish(error);
        return;
      }
      pollTimer = setTimeout(poll, 500);
    };
    const onUpdated = (updatedTabId, changeInfo, tab) => {
      if (updatedTabId !== tabId) return;
      diagnostics.updateEvents += 1;
      if (recordTab(tab, "onUpdated")) finish(null, tab, "onUpdated");
    };
    timeout = setTimeout(() => {
      const last = diagnostics.last || {};
      finish(new Error(
        `La navegacion de LinkedIn no termino para ${expectedUrl} `
        + `(actual: ${last.url || "sin URL"}; estado: ${last.status || "desconocido"})`,
      ));
    }, timeoutMs);
    chrome.tabs.onUpdated.addListener(onUpdated);
    void poll();
  });
}

async function collectFromTab(tabId, maxJobs) {
  let lastError;
  for (let attempt = 0; attempt < 8; attempt += 1) {
    try {
      return await chrome.tabs.sendMessage(tabId, { type: "extractLinkedInFirstPage", maxJobs });
    } catch (error) {
      lastError = error;
      await sleep(1000);
    }
  }
  throw lastError || new Error("El content script no respondió");
}

async function scanUrlAttempt(tab, url, maxJobs, navigationAttempt) {
  const navigationDiagnostics = {
    expectedUrl: url,
    navigationAttempt,
    pollChecks: 0,
    updateEvents: 0,
    observedUrls: [],
  };
  try {
    reportStatus("scan_navigating", { url, tabId: tab.id, navigationAttempt });
    const currentTab = await chrome.tabs.get(tab.id);
    if (!sameUrl(currentTab.url, url)) {
      // This browser is dedicated to LinkedIn and normally headless. Asking
      // Chromium to activate its tab can leave an extension promise pending.
      const updatedTab = await chrome.tabs.update(tab.id, { url });
      navigationDiagnostics.update = tabNavigationSnapshot(updatedTab);
    } else {
      navigationDiagnostics.update = { skipped: true };
    }
    const navigation = await waitForSearchNavigation(tab.id, url, navigationDiagnostics);
    const loadedTab = navigation.tab;
    reportStatus("scan_extracting", {
      url,
      tabId: tab.id,
      navigationAttempt,
      navigation: navigation.diagnostics,
    });
    const result = await collectFromTab(tab.id, maxJobs);
    const jobs = Array.isArray(result?.jobs) ? result.jobs : [];
    const referenceJobs = Array.isArray(result?.referenceJobs) ? result.referenceJobs : [];
    const state = ["complete", "partial", "blocked", "empty", "rate_limited", "failed"].includes(result?.state)
      ? result.state
      : "partial";
    const search = {
      // The configured URL is the audit key; pageUrl remains diagnostics only.
      url,
      state,
      jobs,
      // This uses a selector path independent from the production cards. It
      // is audit evidence only and never enters the delivery pipeline.
      referenceJobs,
      diagnostics: {
        tabUrl: loadedTab.url || "",
        navigation: navigation.diagnostics,
        ...(result?.diagnostics || {}),
      },
      error: String(result?.error || ""),
    };
    reportStatus("jobs_extracted", { url, state, count: jobs.length, ...search.diagnostics });
    return search;
  } catch (error) {
    const message = String(error?.message || error);
    let tabUrl = "";
    try {
      tabUrl = (await chrome.tabs.get(tab.id)).url || "";
    } catch {
      // Keep the navigation error as the useful diagnostic when the tab vanished.
    }
    const diagnostics = error?.navigationDiagnostics || navigationDiagnostics;
    diagnostics.tabUrl = tabUrl;
    reportStatus("search_failed", { url, error: message, navigation: diagnostics });
    return {
      url,
      state: "failed",
      jobs: [],
      diagnostics: { tabUrl, navigation: diagnostics },
      error: message,
    };
  }
}

async function scanUrl(tab, url, maxJobs) {
  const maxNavigationAttempts = 2;
  let latest;
  for (let navigationAttempt = 1; navigationAttempt <= maxNavigationAttempts; navigationAttempt += 1) {
    latest = await scanUrlAttempt(tab, url, maxJobs, navigationAttempt);
    if (latest.state !== "failed" || navigationAttempt === maxNavigationAttempts) return latest;
    // Retry only a failed navigation/content-script hand-off. Results marked
    // blocked or partial are evidence, not something to work around.
    await reportStatus("scan_retry", { url, navigationAttempt, error: latest.error });
    await sleep(5000);
  }
  return latest;
}

let cycleRunning = false;

function interSearchDelayMilliseconds(settings) {
  const minimum = Math.max(0, Number(settings.interSearchDelayMinSeconds) || 3);
  const maximum = Math.max(minimum, Number(settings.interSearchDelayMaxSeconds) || 6);
  return Math.round((minimum + Math.random() * (maximum - minimum)) * 1000);
}

async function runCycle(reason) {
  if (cycleRunning) return;
  cycleRunning = true;
  try {
    const settings = await bridgeFetch("/settings");
    if (!settings.enabled || !Array.isArray(settings.searchUrls) || !settings.searchUrls.length) {
      reportStatus("scan_skipped", { reason: "LinkedIn extension disabled or no URLs" });
      return;
    }
    const tab = await getSearchTab(settings.searchUrls[0]);
    const runId = newRunId();
    reportStatus("scan_started", { runId, reason, urls: settings.searchUrls.length, tabId: tab.id });
    const searches = [];
    for (const [index, url] of settings.searchUrls.entries()) {
      if (index > 0) {
        const delayMs = interSearchDelayMilliseconds(settings);
        await reportStatus("inter_search_delay", {
          runId,
          index,
          delaySeconds: delayMs / 1000,
        });
        await sleep(delayMs);
      }
      // Zero is the bridge protocol value for the complete visible inventory.
      searches.push(await scanUrl(tab, url, Number(settings.maxJobs) || 0));
    }
    const response = await bridgeFetch("/ingest", {
      method: "POST",
      body: JSON.stringify({ run_id: runId, reason, searches }),
      // The bridge persists and validates the browser inventories before
      // delivery. A bounded timeout cannot strand an MV3 service worker.
      timeoutMs: 15_000,
    });
    reportStatus("scan_finished", {
      runId,
      reason,
      searches: searches.length,
      complete: searches.filter((search) => search.state === "complete").length,
      received: response.received,
    });
  } catch (error) {
    reportStatus("scan_failed", { reason, error: String(error?.message || error) });
  } finally {
    cycleRunning = false;
  }
}

async function configureAlarm() {
  let refreshSeconds = 900;
  try {
    const settings = await bridgeFetch("/settings");
    refreshSeconds = settings.refreshSeconds || refreshSeconds;
  } catch (error) {
    console.warn("No se pudo leer la configuración del receptor", error);
  }
  await chrome.alarms.clear(ALARM_NAME);
  chrome.alarms.create(ALARM_NAME, { periodInMinutes: Math.max(1, Math.ceil(refreshSeconds / 60)) });
}

async function startExtensionCycle(reason) {
  await configureAlarm();
  await runCycle(reason);
}

chrome.runtime.onInstalled.addListener(() => { startExtensionCycle("installed"); });
chrome.runtime.onStartup.addListener(() => { startExtensionCycle("browser_startup"); });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === ALARM_NAME) runCycle("alarm");
});
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "scan_now") {
    runCycle("manual");
    sendResponse({ ok: true });
  }
});

// MV3 may restore the browser profile without firing onStartup for this
// extension. Start one guarded cycle whenever the worker is first loaded;
// cycleRunning prevents it from overlapping an alarm or popup-triggered scan.
startExtensionCycle("service_worker_bootstrap").catch((error) => {
  console.warn("No se pudo iniciar el ciclo de LinkedIn", error);
});
