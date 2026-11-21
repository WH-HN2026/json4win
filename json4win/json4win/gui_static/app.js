"use strict";

(function () {
  const state = {
    cases: [],
    selectedPath: null,
    lastRawJson: null,
    pollTimer: null,
    jobRunning: false,
  };

  const els = {
    dirsInfo: document.getElementById("dirs-info"),
    jobPill: document.getElementById("job-pill"),
    jobText: document.getElementById("job-text"),
    btnProcessAll: document.getElementById("btn-process-all"),
    caseSelect: document.getElementById("case-select"),
    newCaseWrap: document.getElementById("new-case-wrap"),
    newCaseInput: document.getElementById("new-case-input"),
    dropzone: document.getElementById("dropzone"),
    fileInput: document.getElementById("file-input"),
    uploadFeedback: document.getElementById("upload-feedback"),
    btnRefresh: document.getElementById("btn-refresh"),
    casesList: document.getElementById("cases-list"),
    viewerEmpty: document.getElementById("viewer-empty"),
    viewerContent: document.getElementById("viewer-content"),
    docPath: document.getElementById("doc-path"),
    docBadge: document.getElementById("doc-badge"),
    btnProcessOne: document.getElementById("btn-process-one"),
    btnCopyJson: document.getElementById("btn-copy-json"),
    btnDownloadJson: document.getElementById("btn-download-json"),
    pdfFrame: document.getElementById("pdf-frame"),
    pdfOpenLink: document.getElementById("pdf-open-link"),
    jsonMeta: document.getElementById("json-meta"),
    emptyJsonBanner: document.getElementById("empty-json-banner"),
    noResultBanner: document.getElementById("no-result-banner"),
    parseErrorBanner: document.getElementById("parse-error-banner"),
    jsonView: document.getElementById("json-view"),
    traceSection: document.getElementById("trace-section"),
    traceFilename: document.getElementById("trace-filename"),
    traceView: document.getElementById("trace-view"),
  };

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function renderPrettyJson(value, indent) {
    const level = indent || 0;
    const pad = "  ".repeat(level);
    const childPad = "  ".repeat(level + 1);

    if (value === null) {
      return '<span class="json-null">null</span>';
    }
    if (typeof value === "string") {
      return '<span class="json-string">' + escapeHtml(JSON.stringify(value)) + "</span>";
    }
    if (typeof value === "number") {
      return '<span class="json-number">' + String(value) + "</span>";
    }
    if (typeof value === "boolean") {
      return '<span class="json-bool">' + String(value) + "</span>";
    }
    if (Array.isArray(value)) {
      if (value.length === 0) {
        return '<span class="json-punct">[]</span>';
      }
      const items = value.map(function (item, idx) {
        const comma = idx < value.length - 1 ? '<span class="json-punct">,</span>' : "";
        return childPad + renderPrettyJson(item, level + 1) + comma;
      });
      return (
        '<span class="json-punct">[</span>\n' +
        items.join("\n") +
        "\n" +
        pad +
        '<span class="json-punct">]</span>'
      );
    }
    if (typeof value === "object") {
      const keys = Object.keys(value);
      if (keys.length === 0) {
        return '<span class="json-punct">{}</span>';
      }
      const entries = keys.map(function (key, idx) {
        const val = value[key];
        const comma = idx < keys.length - 1 ? '<span class="json-punct">,</span>' : "";
        const keyHtml =
          '<span class="json-key">' + escapeHtml(JSON.stringify(key)) + "</span>";
        const valHtml = renderPrettyJson(val, level + 1);
        const line =
          childPad +
          keyHtml +
          '<span class="json-punct">: </span>' +
          valHtml +
          comma;
        if (val === null) {
          return '<span class="json-null-entry">' + line + "</span>";
        }
        return line;
      });
      return (
        '<span class="json-punct">{</span>\n' +
        entries.join("\n") +
        "\n" +
        pad +
        '<span class="json-punct">}</span>'
      );
    }
    return escapeHtml(String(value));
  }

  function statusPresentation(file) {
    if (file.status === "waiting") {
      return { text: "oczekuje", cls: "status-waiting" };
    }
    if (file.status === "ocr") {
      return { text: "OCR…", cls: "status-ocr" };
    }
    if (file.status === "error") {
      return { text: "błąd", cls: "status-error" };
    }
    if (file.status === "done" || file.has_result) {
      if (file.is_empty_result) {
        return { text: "pusty JSON", cls: "status-empty" };
      }
      return { text: file.doc_type || "gotowe", cls: "status-done" };
    }
    return { text: "nowy", cls: "status-idle" };
  }

  function showUploadFeedback(message, isError) {
    els.uploadFeedback.textContent = message;
    els.uploadFeedback.classList.remove("hidden", "ok", "error");
    els.uploadFeedback.classList.add(isError ? "error" : "ok");
  }

  function updateCaseSelect() {
    const prev = els.caseSelect.value;
    const namedCases = state.cases.filter(function (c) {
      return c.name !== "";
    });
    els.caseSelect.innerHTML = "";

    const newOpt = document.createElement("option");
    newOpt.value = "__new__";
    newOpt.textContent = "+ Nowa sprawa...";
    els.caseSelect.appendChild(newOpt);

    namedCases.forEach(function (c) {
      const opt = document.createElement("option");
      opt.value = c.name;
      opt.textContent = c.name;
      els.caseSelect.appendChild(opt);
    });

    const exists = namedCases.some(function (c) {
      return c.name === prev;
    });
    if (exists) {
      els.caseSelect.value = prev;
    } else if (prev === "__new__" || namedCases.length === 0) {
      els.caseSelect.value = "__new__";
    } else {
      els.caseSelect.value = namedCases[0].name;
    }
    toggleNewCaseInput();
  }

  function toggleNewCaseInput() {
    const isNew = els.caseSelect.value === "__new__";
    els.newCaseWrap.classList.toggle("hidden", !isNew);
  }

  function updateJobBanner(job) {
    state.jobRunning = Boolean(job && job.running);
    els.btnProcessAll.disabled = state.jobRunning;
    els.btnProcessOne.disabled = state.jobRunning;

    document.querySelectorAll(".btn-process-case").forEach(function (btn) {
      btn.disabled = state.jobRunning;
    });

    if (!job || job.id === 0) {
      els.jobPill.classList.add("hidden");
      return;
    }

    els.jobPill.classList.remove("hidden", "running", "done", "has-errors");
    if (job.running) {
      els.jobPill.classList.add("running");
      els.jobText.textContent =
        "Przetwarzanie: " + job.completed + " / " + job.total;
    } else if (job.failed > 0) {
      els.jobPill.classList.add("has-errors");
      els.jobText.textContent =
        "Zakończono: " + job.completed + " / " + job.total + " (błędy: " + job.failed + ")";
    } else {
      els.jobPill.classList.add("done");
      els.jobText.textContent = "Gotowe: " + job.completed + " / " + job.total;
    }
  }

  function renderCases() {
    els.casesList.innerHTML = "";
    if (!state.cases.length) {
      const empty = document.createElement("div");
      empty.className = "empty-hint";
      empty.textContent = "Brak spraw w katalogu wejściowym. Wgraj pliki PDF powyżej.";
      els.casesList.appendChild(empty);
      return;
    }

    state.cases.forEach(function (c) {
      const card = document.createElement("div");
      card.className = "case-card";

      const header = document.createElement("div");
      header.className = "case-header";

      const title = document.createElement("div");
      title.className = "case-title";
      title.title = c.name || "(katalog główny)";
      title.textContent = c.name || "(katalog główny)";

      const count = document.createElement("span");
      count.className = "case-count";
      count.textContent = "(" + c.files.length + ")";
      title.appendChild(count);

      const procBtn = document.createElement("button");
      procBtn.type = "button";
      procBtn.className = "btn btn-secondary btn-sm btn-process-case";
      procBtn.textContent = "Przetwórz";
      procBtn.disabled = state.jobRunning || c.files.length === 0;
      procBtn.addEventListener("click", function () {
        startProcessing({ scope: "case", case: c.name });
      });

      header.appendChild(title);
      header.appendChild(procBtn);
      card.appendChild(header);

      if (!c.files.length) {
        const noFiles = document.createElement("div");
        noFiles.className = "empty-hint";
        noFiles.style.padding = "8px 10px";
        noFiles.textContent = "Brak plików PDF";
        card.appendChild(noFiles);
      } else {
        const ul = document.createElement("ul");
        ul.className = "file-list";

        c.files.forEach(function (file) {
          const li = document.createElement("li");
          li.className = "file-item";
          if (state.selectedPath === file.rel_path) {
            li.classList.add("selected");
          }

          const nameSpan = document.createElement("span");
          nameSpan.className = "file-name";
          nameSpan.textContent = file.name;
          nameSpan.title = file.rel_path;

          const st = statusPresentation(file);
          const tag = document.createElement("span");
          tag.className = "status-tag " + st.cls;
          tag.textContent = st.text;
          if (file.error) {
            tag.title = file.error;
          }

          li.appendChild(nameSpan);
          li.appendChild(tag);
          li.addEventListener("click", function () {
            selectDocument(file.rel_path);
          });
          ul.appendChild(li);
        });
        card.appendChild(ul);
      }

      els.casesList.appendChild(card);
    });
  }

  async function refreshCases(reloadSelected) {
    const res = await fetch("/api/cases", { cache: "no-store" });
    if (!res.ok) {
      throw new Error("Nie udało się pobrać listy spraw.");
    }
    const data = await res.json();
    state.cases = data.cases || [];
    els.dirsInfo.textContent =
      "Wejście: " + data.input_dir + "  |  Wyjście: " + data.output_dir;

    updateCaseSelect();
    renderCases();
    updateJobBanner(data.job);

    if (data.job && data.job.running) {
      ensurePolling();
    }
    if (reloadSelected && state.selectedPath) {
      await loadResult(state.selectedPath);
    }
  }

  async function selectDocument(relPath) {
    const changed = state.selectedPath !== relPath;
    state.selectedPath = relPath;
    renderCases();

    els.viewerEmpty.classList.add("hidden");
    els.viewerContent.classList.remove("hidden");
    els.docPath.textContent = relPath;

    const encoded = encodeURIComponent(relPath);
    const pdfUrl = "/api/pdf?path=" + encoded;
    if (changed || els.pdfFrame.getAttribute("src") !== pdfUrl) {
      els.pdfFrame.setAttribute("src", pdfUrl);
      els.pdfOpenLink.setAttribute("href", pdfUrl);
    }

    await loadResult(relPath);
  }

  async function loadResult(relPath) {
    const encoded = encodeURIComponent(relPath);
    const res = await fetch("/api/result?path=" + encoded, { cache: "no-store" });
    if (!res.ok) {
      return;
    }
    const data = await res.json();
    if (state.selectedPath !== relPath) {
      return;
    }

    els.docBadge.classList.add("hidden");
    els.docBadge.classList.remove("badge-ok", "badge-muted");
    els.emptyJsonBanner.classList.add("hidden");
    els.noResultBanner.classList.add("hidden");
    els.parseErrorBanner.classList.add("hidden");
    els.jsonView.classList.add("hidden");
    els.btnDownloadJson.classList.add("hidden");
    els.btnCopyJson.classList.add("hidden");
    els.traceSection.classList.add("hidden");
    state.lastRawJson = null;

    if (!data.exists) {
      els.jsonMeta.textContent = "brak pliku";
      els.noResultBanner.classList.remove("hidden");
    } else {
      els.jsonMeta.textContent = data.json_filename;
      els.btnDownloadJson.setAttribute("href", "/api/download?path=" + encoded);
      els.btnDownloadJson.classList.remove("hidden");
      els.btnCopyJson.classList.remove("hidden");
      state.lastRawJson = data.raw_text || "";

      if (data.parse_error) {
        els.parseErrorBanner.textContent =
          "Błąd parsowania JSON: " + data.parse_error;
        els.parseErrorBanner.classList.remove("hidden");
        els.jsonView.textContent = data.raw_text || "";
        els.jsonView.classList.remove("hidden");
      } else {
        if (data.is_empty) {
          els.emptyJsonBanner.classList.remove("hidden");
          els.docBadge.textContent = "nie rozpoznano (pusty JSON)";
          els.docBadge.classList.add("badge-muted");
          els.docBadge.classList.remove("hidden");
        } else if (data.doc_type) {
          els.docBadge.textContent = data.doc_type;
          els.docBadge.classList.add("badge-ok");
          els.docBadge.classList.remove("hidden");
        }
        els.jsonView.innerHTML = renderPrettyJson(data.data, 0);
        els.jsonView.classList.remove("hidden");
      }
    }

    if (data.trace !== null && data.trace !== undefined) {
      els.traceFilename.textContent = data.trace_filename || "";
      els.traceView.textContent =
        typeof data.trace === "string"
          ? data.trace
          : JSON.stringify(data.trace, null, 2);
      els.traceSection.classList.remove("hidden");
    }
  }

  async function uploadFiles(fileList) {
    const files = Array.from(fileList || []);
    if (!files.length) {
      return;
    }

    let targetCase = els.caseSelect.value;
    if (targetCase === "__new__") {
      targetCase = els.newCaseInput.value.trim();
      if (!targetCase) {
        showUploadFeedback("Podaj nazwę nowej sprawy przed wgraniem plików.", true);
        els.newCaseInput.focus();
        return;
      }
    }

    let uploaded = 0;
    const errors = [];
    let lastRelPath = null;

    for (const file of files) {
      const url =
        "/api/upload?case=" +
        encodeURIComponent(targetCase) +
        "&filename=" +
        encodeURIComponent(file.name);
      try {
        const res = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/pdf" },
          body: file,
        });
        const body = await res.json();
        if (!res.ok) {
          errors.push(file.name + ": " + (body.error || "błąd wgrywania"));
        } else {
          uploaded += 1;
          lastRelPath = body.rel_path;
        }
      } catch (err) {
        errors.push(file.name + ": " + err.message);
      }
    }

    await refreshCases(false);
    if (uploaded > 0) {
      els.caseSelect.value = targetCase;
      toggleNewCaseInput();
      if (lastRelPath && !state.selectedPath) {
        await selectDocument(lastRelPath);
      }
    }

    if (errors.length) {
      showUploadFeedback(
        "Wgrano: " + uploaded + ". Błędy: " + errors.join("; "),
        true
      );
    } else {
      showUploadFeedback(
        "Wgrano plików: " + uploaded + " do sprawy „" + targetCase + "”.",
        false
      );
    }
  }

  async function startProcessing(payload) {
    try {
      const res = await fetch("/api/process", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await res.json();
      if (!res.ok) {
        showUploadFeedback(body.error || "Nie udało się uruchomić przetwarzania.", true);
        return;
      }
      updateJobBanner(body);
      await refreshCases(true);
      if (body.running) {
        ensurePolling();
      }
    } catch (err) {
      showUploadFeedback("Błąd połączenia z serwerem: " + err.message, true);
    }
  }

  function ensurePolling() {
    if (state.pollTimer !== null) {
      return;
    }
    state.pollTimer = window.setInterval(async function () {
      try {
        const res = await fetch("/api/status", { cache: "no-store" });
        if (!res.ok) {
          return;
        }
        const job = await res.json();
        updateJobBanner(job);
        await refreshCases(true);
        if (!job.running) {
          window.clearInterval(state.pollTimer);
          state.pollTimer = null;
        }
      } catch (_err) {
        // Keep polling transiently; local server may just be busy.
      }
    }, 500);
  }

  // Wire up events
  els.caseSelect.addEventListener("change", toggleNewCaseInput);
  els.btnRefresh.addEventListener("click", function () {
    refreshCases(true);
  });
  els.btnProcessAll.addEventListener("click", function () {
    startProcessing({ scope: "all" });
  });
  els.btnProcessOne.addEventListener("click", function () {
    if (state.selectedPath) {
      startProcessing({ scope: "file", path: state.selectedPath });
    }
  });
  els.btnCopyJson.addEventListener("click", async function () {
    if (!state.lastRawJson || !navigator.clipboard) {
      return;
    }
    try {
      await navigator.clipboard.writeText(state.lastRawJson);
      const prev = els.btnCopyJson.textContent;
      els.btnCopyJson.textContent = "Skopiowano";
      window.setTimeout(function () {
        els.btnCopyJson.textContent = prev;
      }, 1200);
    } catch (_err) {
      // Clipboard API unavailable
    }
  });

  els.dropzone.addEventListener("click", function () {
    els.fileInput.click();
  });
  els.dropzone.addEventListener("keydown", function (ev) {
    if (ev.key === "Enter" || ev.key === " ") {
      ev.preventDefault();
      els.fileInput.click();
    }
  });
  els.fileInput.addEventListener("change", function () {
    uploadFiles(els.fileInput.files);
    els.fileInput.value = "";
  });
  els.dropzone.addEventListener("dragover", function (ev) {
    ev.preventDefault();
    els.dropzone.classList.add("dragover");
  });
  els.dropzone.addEventListener("dragleave", function () {
    els.dropzone.classList.remove("dragover");
  });
  els.dropzone.addEventListener("drop", function (ev) {
    ev.preventDefault();
    els.dropzone.classList.remove("dragover");
    uploadFiles(ev.dataTransfer.files);
  });

  // Initial load
  refreshCases(false).catch(function (err) {
    els.casesList.textContent = "Błąd ładowania: " + err.message;
  });
})();
