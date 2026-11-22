"use strict";

/* Dokumenty view: cases and files (rail), upload, processing with live state, PDF + JSON viewer. */
(function () {
  const J = window.J4W;

  const state = {
    cases: [],
    job: null,
    selected: null,
    casesKey: "",
    selKey: "",
    raw: null,
    tab: "json",
    hasTrace: false,
    pollTimer: null,
    uploadCase: null,
    suggestedCase: "",
    feedbackTimer: null,
  };

  function $(id) {
    return document.getElementById(id);
  }

  const els = {
    rail: $("rail"),
    casesList: $("cases-list"),
    casesCount: $("cases-count"),
    dirsInfo: $("dirs-info"),
    btnRefresh: $("btn-refresh"),
    btnProcessAll: $("btn-process-all"),
    feedback: $("upload-feedback"),
    newCaseInput: $("new-case-input"),
    dropzone: $("dropzone"),
    fileInput: $("file-input"),
    viewerEmpty: $("viewer-empty"),
    emptyTitle: $("empty-title"),
    emptySummary: $("empty-summary"),
    bigDrop: $("big-drop"),
    bigDropCase: $("big-drop-case"),
    viewer: $("viewer-content"),
    btnBack: $("btn-back"),
    docCase: $("doc-case"),
    docName: $("doc-name"),
    docState: $("doc-state"),
    docBadge: $("doc-badge"),
    btnProcessOne: $("btn-process-one"),
    btnCopy: $("btn-copy-json"),
    btnDownload: $("btn-download-json"),
    docError: $("doc-error"),
    docErrorText: $("doc-error-text"),
    tabJson: $("tab-json"),
    tabTrace: $("tab-trace"),
    jsonMeta: $("json-meta"),
    jsonNotes: $("json-notes"),
    emptyBanner: $("empty-json-banner"),
    noResultBanner: $("no-result-banner"),
    runningBanner: $("running-banner"),
    runningText: $("running-text"),
    runningTime: $("running-time"),
    parseError: $("parse-error-banner"),
    jsonView: $("json-view"),
    traceView: $("trace-view"),
    pdfFrame: $("pdf-frame"),
    pdfOpen: $("pdf-open-link"),
  };

  // ---- helpers ----

  function caseLabel(name) {
    return name || "(katalog główny)";
  }

  function allFiles() {
    const out = [];
    state.cases.forEach(function (c) {
      c.files.forEach(function (f) {
        out.push(f);
      });
    });
    return out;
  }

  function findFile(rel) {
    return allFiles().find(function (f) {
      return f.rel_path === rel;
    });
  }

  function jobRunning() {
    return Boolean(state.job && state.job.running);
  }

  // One vocabulary for the list, the header and the summary.
  function fileState(f) {
    if (f.status === "waiting") return { mk: "mk-wait", word: "w kolejce" };
    if (f.status === "ocr") return { mk: "mk-run", word: "w toku", running: true };
    if (f.status === "error") return { mk: "mk-err", word: "błąd" };
    if (f.status === "done" || f.has_result) {
      if (f.is_empty_result) return { mk: "mk-empty", word: "pusty {}" };
      return { mk: "mk-done", word: "gotowe" };
    }
    return { mk: "mk-idle", word: "nowy" };
  }

  function fileSince(f) {
    const jobId = state.job ? state.job.id : 0;
    return J.since("file-" + jobId + "-" + f.rel_path);
  }

  function mk(cls) {
    const s = document.createElement("span");
    s.className = "mk " + cls;
    return s;
  }

  function showFeedback(message, kind) {
    window.clearTimeout(state.feedbackTimer);
    if (!message) {
      els.feedback.classList.add("hidden");
      return;
    }
    els.feedback.className = "note rail-note" + (kind === "err" ? " note-err" : kind === "busy" ? "" : " note-muted");
    els.feedback.textContent = message;
    els.feedback.classList.remove("hidden");
    if (kind === "ok") {
      state.feedbackTimer = window.setTimeout(function () {
        els.feedback.classList.add("hidden");
      }, 5000);
    }
  }

  function nextCaseName() {
    const names = new Set(
      state.cases.map(function (c) {
        return c.name;
      })
    );
    for (let i = 1; i < 1000; i += 1) {
      const name = "sprawa_" + String(i).padStart(2, "0");
      if (!names.has(name)) return name;
    }
    return "sprawa_nowa";
  }

  // ---- rail ----

  function renderCases() {
    const focusedRel =
      document.activeElement && document.activeElement.getAttribute
        ? document.activeElement.getAttribute("data-rel")
        : null;
    els.casesList.innerHTML = "";

    const files = allFiles();
    els.casesCount.textContent = state.cases.length ? String(state.cases.length) : "";

    if (!state.cases.length) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "Brak spraw.";
      els.casesList.appendChild(empty);
    }

    state.cases.forEach(function (c) {
      const group = document.createElement("div");
      group.className = "group";
      group.setAttribute("data-case", c.name);

      const head = document.createElement("div");
      head.className = "group-head";
      const name = document.createElement("span");
      name.className = "group-name ellipsis";
      name.textContent = caseLabel(c.name);
      name.title = caseLabel(c.name);
      const count = document.createElement("span");
      count.className = "group-count";
      count.textContent = String(c.files.length);
      const actions = document.createElement("div");
      actions.className = "group-actions";

      if (c.name !== "") {
        const add = document.createElement("button");
        add.type = "button";
        add.className = "btn btn-quiet btn-add-case";
        add.textContent = "Dodaj";
        add.title = "Dodaj pliki PDF do sprawy " + c.name;
        add.addEventListener("click", function () {
          pickFiles(c.name);
        });
        actions.appendChild(add);
      }
      const proc = document.createElement("button");
      proc.type = "button";
      proc.className = "btn btn-quiet btn-process-case";
      proc.textContent = "Przetwórz";
      proc.title = "Przetwórz wszystkie pliki sprawy";
      proc.disabled = jobRunning() || !c.files.length;
      proc.addEventListener("click", function () {
        startProcessing({ scope: "case", case: c.name });
      });
      actions.appendChild(proc);

      head.appendChild(name);
      head.appendChild(count);
      head.appendChild(actions);
      group.appendChild(head);

      if (!c.files.length) {
        const none = document.createElement("div");
        none.className = "empty";
        none.textContent = "Brak plików PDF.";
        group.appendChild(none);
      }

      c.files.forEach(function (f) {
        const st = fileState(f);
        const row = document.createElement("button");
        row.type = "button";
        row.className = "row file-item" + (state.selected === f.rel_path ? " selected" : "");
        row.setAttribute("data-rel", f.rel_path);
        row.setAttribute("role", "option");
        row.setAttribute("aria-selected", state.selected === f.rel_path ? "true" : "false");
        row.title = f.rel_path + " · " + st.word + (f.error ? "\n" + f.error : "");

        const nm = document.createElement("span");
        nm.className = "row-name";
        nm.textContent = f.name;
        const meta = document.createElement("span");
        meta.className = "row-meta";
        if (st.running) {
          meta.textContent = "w toku ";
          const t = document.createElement("span");
          t.setAttribute("data-since", String(fileSince(f)));
          meta.appendChild(t);
        } else if (st.mk === "mk-done" && f.doc_type) {
          meta.textContent = f.doc_type;
        } else {
          meta.textContent = st.word;
        }
        row.appendChild(mk(st.mk));
        row.appendChild(nm);
        row.appendChild(meta);
        row.addEventListener("click", function () {
          selectDocument(f.rel_path);
        });
        group.appendChild(row);
      });

      bindCaseDrop(group, c.name);
      els.casesList.appendChild(group);
    });

    if (focusedRel) {
      const again = els.casesList.querySelector('[data-rel="' + CSS.escape(focusedRel) + '"]');
      if (again) again.focus();
    }
    J.tick();
    renderEmptySummary(files);
  }

  function bindCaseDrop(group, caseName) {
    if (caseName === "") return;
    J.bindDrop(group, function (files) {
      uploadFiles(files, caseName);
    });
  }

  function renderEmptySummary(files) {
    if (!state.cases.length) {
      els.emptyTitle.textContent = "Dodaj pliki PDF";
      els.emptySummary.innerHTML = "";
      return;
    }
    const counts = {};
    const order = [];
    files.forEach(function (f) {
      const st = fileState(f);
      if (!counts[st.word]) {
        counts[st.word] = { n: 0, mk: st.mk };
        order.push(st.word);
      }
      counts[st.word].n += 1;
    });
    els.emptyTitle.textContent = "Wybierz dokument";
    els.emptySummary.innerHTML = "";
    order.forEach(function (w) {
      const s = document.createElement("span");
      s.className = "state";
      s.appendChild(mk(counts[w].mk));
      s.appendChild(document.createTextNode(counts[w].n + " " + w));
      els.emptySummary.appendChild(s);
    });
  }

  function updateJobButtons() {
    const running = jobRunning();
    els.btnProcessAll.disabled = running || !allFiles().length;
    els.btnProcessOne.disabled = running;
    document.querySelectorAll(".btn-process-case").forEach(function (b) {
      b.disabled = running || b.closest(".group").querySelectorAll(".file-item").length === 0;
    });
  }

  function suggestCaseName() {
    const cur = els.newCaseInput.value.trim();
    if (!cur || cur === state.suggestedCase) {
      state.suggestedCase = nextCaseName();
      els.newCaseInput.value = state.suggestedCase;
    }
    els.bigDropCase.textContent = els.newCaseInput.value.trim() || "?";
  }

  // ---- data ----

  async function refreshCases() {
    const res = await J.api("/api/cases");
    if (!res.ok) {
      showFeedback(res.body.error || "Nie udało się pobrać listy spraw.", "err");
      return;
    }
    const data = res.body;
    state.cases = data.cases || [];
    state.job = data.job || null;

    els.dirsInfo.innerHTML = "";
    [
      ["we: ", data.input_dir, "Katalog wejściowy"],
      ["wy: ", data.output_dir, "Katalog wyjściowy (JSON)"],
    ].forEach(function (p) {
      const d = document.createElement("div");
      d.textContent = p[0] + p[1];
      d.title = p[2] + ": " + p[1];
      els.dirsInfo.appendChild(d);
    });

    const key = JSON.stringify([state.cases, state.job && state.job.id, jobRunning()]);
    if (key !== state.casesKey) {
      state.casesKey = key;
      renderCases();
    }
    J.renderJob(state.job);
    updateJobButtons();
    suggestCaseName();

    if (state.selected) {
      const f = findFile(state.selected);
      if (!f) {
        clearSelection();
      } else {
        const sig = [f.status, f.has_result, f.is_empty_result, f.doc_type, f.error].join("|");
        if (sig !== state.selKey) {
          state.selKey = sig;
          await loadResult(state.selected);
        }
      }
    }
    if (jobRunning()) ensurePolling();
  }

  function ensurePolling() {
    if (state.pollTimer !== null) return;
    state.pollTimer = window.setInterval(async function () {
      await refreshCases();
      if (!jobRunning()) {
        window.clearInterval(state.pollTimer);
        state.pollTimer = null;
      }
    }, 800);
  }

  // ---- selection & viewer ----

  function setUrl(rel) {
    try {
      const url = new URL(window.location.href);
      if (rel) url.searchParams.set("doc", rel);
      else url.searchParams.delete("doc");
      window.history.replaceState(null, "", url.pathname + url.search);
    } catch (_e) {
      // ignore
    }
  }

  function markSelected() {
    els.casesList.querySelectorAll(".file-item").forEach(function (row) {
      const on = row.getAttribute("data-rel") === state.selected;
      row.classList.toggle("selected", on);
      row.setAttribute("aria-selected", on ? "true" : "false");
    });
  }

  function clearSelection() {
    state.selected = null;
    state.selKey = "";
    setUrl(null);
    markSelected();
    document.body.classList.remove("show-doc");
    els.viewer.classList.add("hidden");
    els.viewerEmpty.classList.remove("hidden");
    els.pdfFrame.removeAttribute("src");
  }

  async function selectDocument(rel) {
    const f = findFile(rel);
    if (!f) return;
    const changed = state.selected !== rel;
    state.selected = rel;
    state.selKey = [f.status, f.has_result, f.is_empty_result, f.doc_type, f.error].join("|");
    setUrl(rel);
    markSelected();
    document.body.classList.add("show-doc");
    els.viewerEmpty.classList.add("hidden");
    els.viewer.classList.remove("hidden");

    const parts = rel.split("/");
    els.docName.textContent = parts[parts.length - 1];
    els.docName.title = rel;
    els.docCase.textContent = parts.length > 1 ? parts.slice(0, -1).join(" / ") : caseLabel("");

    const pdfUrl = "/api/pdf?path=" + encodeURIComponent(rel);
    if (changed || !els.pdfFrame.getAttribute("src")) {
      els.pdfFrame.setAttribute("src", pdfUrl + "#navpanes=0");
      els.pdfOpen.setAttribute("href", pdfUrl);
    }
    if (changed) {
      state.tab = "json";
      els.jsonView.parentElement.scrollTop = 0;
    }
    await loadResult(rel);
  }

  function setTab(tab) {
    state.tab = tab === "trace" && state.hasTrace ? "trace" : "json";
    const isTrace = state.tab === "trace";
    els.tabJson.classList.toggle("active", !isTrace);
    els.tabTrace.classList.toggle("active", isTrace);
    els.tabJson.setAttribute("aria-selected", String(!isTrace));
    els.tabTrace.setAttribute("aria-selected", String(isTrace));
    els.traceView.classList.toggle("hidden", !isTrace);
    els.jsonNotes.classList.toggle("hidden", isTrace);
    els.jsonView.classList.toggle("hidden", isTrace || els.jsonView.getAttribute("data-empty") === "1");
  }

  function traceError(trace) {
    if (trace && typeof trace === "object" && trace.status === "error" && trace.error) {
      const e = trace.error;
      return (e.type ? e.type + ": " : "") + (e.message || "");
    }
    return null;
  }

  async function loadResult(rel) {
    const res = await J.api("/api/result?path=" + encodeURIComponent(rel));
    if (state.selected !== rel) return;
    const f = findFile(rel) || {};
    const st = fileState(f);

    // header state
    els.docState.innerHTML = "";
    els.docState.appendChild(mk(st.mk));
    const word = document.createElement("span");
    word.textContent = st.word;
    els.docState.appendChild(word);

    [els.emptyBanner, els.noResultBanner, els.runningBanner, els.parseError, els.docError].forEach(function (e) {
      e.classList.add("hidden");
    });
    els.btnDownload.classList.add("hidden");
    els.btnCopy.classList.add("hidden");
    els.docBadge.classList.add("hidden");
    els.jsonView.innerHTML = "";
    els.jsonView.setAttribute("data-empty", "1");
    state.raw = null;

    if (!res.ok) {
      els.parseError.textContent = res.body.error || "Nie udało się wczytać wyniku.";
      els.parseError.classList.remove("hidden");
      setTab("json");
      return;
    }
    const data = res.body;

    if (st.running || f.status === "waiting") {
      els.runningText.textContent = st.running ? "W toku" : "W kolejce";
      if (st.running) {
        els.runningTime.setAttribute("data-since", String(fileSince(f)));
      } else {
        els.runningTime.removeAttribute("data-since");
        els.runningTime.textContent = "";
      }
      els.runningBanner.classList.remove("hidden");
    }

    const errText = f.error || traceError(data.trace);
    if (errText && !st.running && f.status !== "waiting") {
      els.docErrorText.textContent = J.shorten(errText, 220);
      els.docError.title = errText;
      els.docError.classList.remove("hidden");
    }

    if (!data.exists) {
      els.jsonMeta.textContent = "brak pliku";
      if (!st.running && f.status !== "waiting") els.noResultBanner.classList.remove("hidden");
    } else {
      els.jsonMeta.textContent = data.json_filename;
      els.jsonMeta.title = data.json_filename;
      els.btnDownload.setAttribute("href", "/api/download?path=" + encodeURIComponent(rel));
      els.btnDownload.classList.remove("hidden");
      els.btnCopy.classList.remove("hidden");
      state.raw = data.raw_text || "";
      if (data.parse_error) {
        els.parseError.textContent = "Błąd JSON: " + data.parse_error;
        els.parseError.classList.remove("hidden");
        els.jsonView.textContent = data.raw_text || "";
      } else {
        if (data.is_empty && !errText) els.emptyBanner.classList.remove("hidden");
        if (data.doc_type) {
          els.docBadge.textContent = data.doc_type;
          els.docBadge.title = "Klucz główny wyniku";
          els.docBadge.classList.remove("hidden");
        }
        els.jsonView.innerHTML = J.renderJson(data.data, 0);
      }
      els.jsonView.setAttribute("data-empty", "0");
    }

    state.hasTrace = data.trace !== null && data.trace !== undefined;
    els.tabTrace.classList.toggle("hidden", !state.hasTrace);
    if (state.hasTrace) {
      els.tabTrace.title = (data.trace_filename || "") + ": skąd pochodzi każda wartość";
      els.traceView.textContent =
        typeof data.trace === "string" ? data.trace : JSON.stringify(data.trace, null, 2);
    } else {
      els.traceView.textContent = "";
    }
    setTab(state.tab);
    J.tick();
  }

  // ---- upload ----

  function pickFiles(caseName) {
    state.uploadCase = caseName;
    els.fileInput.click();
  }

  async function uploadFiles(fileList, caseName) {
    const files = Array.from(fileList || []);
    if (!files.length) return;
    let target = caseName;
    if (target === null || target === undefined) {
      target = els.newCaseInput.value.trim();
      if (!target) {
        showFeedback("Podaj nazwę sprawy.", "err");
        els.newCaseInput.focus();
        return;
      }
    }
    let uploaded = 0;
    let lastRel = null;
    const errors = [];
    for (const file of files) {
      showFeedback("Wgrywanie " + (uploaded + errors.length + 1) + "/" + files.length + ": " + file.name, "busy");
      const url =
        "/api/upload?case=" + encodeURIComponent(target) + "&filename=" + encodeURIComponent(file.name);
      const res = await J.uploadPdf(url, file);
      if (res.ok) {
        uploaded += 1;
        lastRel = res.body.rel_path;
      } else {
        errors.push(file.name + ": " + (res.body.error || "błąd"));
      }
    }
    await refreshCases();
    if (lastRel) await selectDocument(lastRel);
    if (errors.length) {
      showFeedback("Dodano: " + uploaded + ". " + errors.join("; "), "err");
    } else {
      showFeedback("Dodano " + uploaded + " PDF do: " + target, "ok");
    }
  }

  // ---- processing ----

  async function startProcessing(payload) {
    showFeedback("");
    const res = await J.api("/api/process", payload);
    if (!res.ok) {
      showFeedback(res.body.error || "Nie udało się uruchomić przetwarzania.", "err");
      return;
    }
    state.job = res.body;
    J.renderJob(res.body);
    await refreshCases();
    if (res.body.running) ensurePolling();
  }

  // ---- events ----

  els.btnRefresh.addEventListener("click", refreshCases);
  els.btnProcessAll.addEventListener("click", function () {
    startProcessing({ scope: "all" });
  });
  els.btnProcessOne.addEventListener("click", function () {
    if (state.selected) startProcessing({ scope: "file", path: state.selected });
  });
  els.btnBack.addEventListener("click", function () {
    const rel = state.selected;
    clearSelection();
    const row = rel && els.casesList.querySelector('[data-rel="' + CSS.escape(rel) + '"]');
    if (row) row.focus();
  });
  els.tabJson.addEventListener("click", function () {
    setTab("json");
  });
  els.tabTrace.addEventListener("click", function () {
    setTab("trace");
  });
  els.btnCopy.addEventListener("click", async function () {
    if (state.raw === null || !navigator.clipboard) return;
    try {
      await navigator.clipboard.writeText(state.raw);
      els.btnCopy.textContent = "Skopiowano";
      window.setTimeout(function () {
        els.btnCopy.textContent = "Kopiuj";
      }, 1200);
    } catch (_e) {
      els.btnCopy.textContent = "Brak dostępu";
    }
  });

  els.newCaseInput.addEventListener("input", function () {
    els.bigDropCase.textContent = els.newCaseInput.value.trim() || "?";
  });
  els.fileInput.addEventListener("change", function () {
    const target = state.uploadCase;
    state.uploadCase = null;
    uploadFiles(els.fileInput.files, target);
    els.fileInput.value = "";
  });
  J.bindDrop(els.dropzone, function (files) {
    uploadFiles(files, null);
  }, function () {
    pickFiles(null);
  });
  J.bindDrop(els.bigDrop, function (files) {
    uploadFiles(files, null);
  }, function () {
    pickFiles(null);
  });

  // Arrow keys move through the file list; Escape goes back on narrow screens.
  els.rail.addEventListener("keydown", function (ev) {
    const row = ev.target.closest ? ev.target.closest(".file-item") : null;
    if (!row || (ev.key !== "ArrowDown" && ev.key !== "ArrowUp")) return;
    ev.preventDefault();
    const rows = Array.from(els.casesList.querySelectorAll(".file-item"));
    const idx = rows.indexOf(row) + (ev.key === "ArrowDown" ? 1 : -1);
    if (idx >= 0 && idx < rows.length) {
      rows[idx].focus();
      selectDocument(rows[idx].getAttribute("data-rel"));
    }
  });
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape" && document.body.classList.contains("show-doc") && window.innerWidth <= 900) {
      els.btnBack.click();
    }
  });

  // ---- init ----

  (async function init() {
    await refreshCases();
    const wanted = new URLSearchParams(window.location.search).get("doc");
    if (wanted && findFile(wanted)) await selectDocument(wanted);
    else if (wanted) setUrl(null);
  })();
})();
