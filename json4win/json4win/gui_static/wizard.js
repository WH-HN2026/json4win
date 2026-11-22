"use strict";

(function () {
  const state = {
    stage: 1,
    configDir: "",
    maxFiles: 5,
    maxPages: 2,
    hint: "",
    files: [],
    szablon: null,
    typy: {},
    previews: [],
    activePreviewIdx: 0,
    rawJsonValid: true,
    yamlText: "",
    validation: null,
    lastTest: null,
    busy: false,
    validateTimer: null,
  };

  const els = {
    configDirInfo: document.getElementById("config-dir-info"),
    btnReset: document.getElementById("btn-reset"),
    resetConfirm: document.getElementById("reset-confirm"),
    btnResetConfirm: document.getElementById("btn-reset-confirm"),
    btnResetCancel: document.getElementById("btn-reset-cancel"),
    globalError: document.getElementById("global-error"),
    globalErrorText: document.getElementById("global-error-text"),
    btnErrorClose: document.getElementById("btn-error-close"),
    stageStatus: document.getElementById("stage-status"),
    busy: document.getElementById("busy"),
    busyLabel: document.getElementById("busy-label"),
    busyTime: document.getElementById("busy-time"),
    stepMetas: [
      document.getElementById("step-meta-1"),
      document.getElementById("step-meta-2"),
      document.getElementById("step-meta-3"),
    ],
    stepBtns: [
      document.getElementById("step-btn-1"),
      document.getElementById("step-btn-2"),
      document.getElementById("step-btn-3"),
    ],
    stagePanels: [
      document.getElementById("stage-1"),
      document.getElementById("stage-2"),
      document.getElementById("stage-3"),
    ],
    // Stage 1
    maxPagesInput: document.getElementById("max-pages-input"),
    hintInput: document.getElementById("hint-input"),
    btnRerunOcr: document.getElementById("btn-rerun-ocr"),
    btnToStage2: document.getElementById("btn-to-stage-2"),
    dropzone: document.getElementById("wizard-dropzone"),
    fileInput: document.getElementById("wizard-file-input"),
    fileCounter: document.getElementById("file-counter"),
    ocrProgressWrap: document.getElementById("ocr-progress-wrap"),
    ocrProgressLabel: document.getElementById("ocr-progress-label"),
    ocrProgressCount: document.getElementById("ocr-progress-count"),
    ocrProgressFill: document.getElementById("ocr-progress-fill"),
    filesList: document.getElementById("wizard-files-list"),
    // Stage 2
    btnProposeSzablon: document.getElementById("btn-propose-szablon"),
    btnRefreshPreview: document.getElementById("btn-refresh-preview"),
    btnToStage3: document.getElementById("btn-to-stage-3"),
    leafCountTag: document.getElementById("leaf-count-tag"),
    btnAddRootField: document.getElementById("btn-add-root-field"),
    schemaTree: document.getElementById("schema-tree"),
    rawJsonStatus: document.getElementById("raw-json-status"),
    rawJsonError: document.getElementById("raw-json-error"),
    rawJsonEditor: document.getElementById("raw-json-editor"),
    previewTabs: document.getElementById("preview-tabs"),
    previewBody: document.getElementById("preview-body"),
    // Stage 3
    btnProposeYaml: document.getElementById("btn-propose-yaml"),
    btnTestPipeline: document.getElementById("btn-test-pipeline"),
    btnDownloadYaml: document.getElementById("btn-download-yaml"),
    btnSaveYaml: document.getElementById("btn-save-yaml"),
    overwriteBar: document.getElementById("overwrite-bar"),
    overwriteMessage: document.getElementById("overwrite-message"),
    btnConfirmOverwrite: document.getElementById("btn-confirm-overwrite"),
    btnCancelOverwrite: document.getElementById("btn-cancel-overwrite"),
    saveOkBar: document.getElementById("save-ok-bar"),
    yamlFilenameLabel: document.getElementById("yaml-filename-label"),
    yamlValidChip: document.getElementById("yaml-valid-chip"),
    yamlLinesCount: document.getElementById("yaml-lines-count"),
    yamlGutter: document.getElementById("yaml-gutter"),
    yamlEditor: document.getElementById("yaml-editor"),
    yamlValidationPanel: document.getElementById("yaml-validation-panel"),
    markerPatternTag: document.getElementById("marker-pattern-tag"),
    markerResults: document.getElementById("marker-results"),
    testSummaryTag: document.getElementById("test-summary-tag"),
    testResults: document.getElementById("test-results"),
    tabTest: document.getElementById("tab-test"),
    tabMarker: document.getElementById("tab-marker"),
    stage2Empty: document.getElementById("stage2-empty"),
    stage3Empty: document.getElementById("stage3-empty"),
  };

  const J = window.J4W;
  const renderPrettyJson = J.renderJson;
  const apiJson = J.api;
  const formatBytes = J.formatBytes;

  function showError(msg) {
    if (!msg) {
      els.globalError.classList.add("hidden");
      els.globalErrorText.textContent = "";
      return;
    }
    els.globalErrorText.textContent = J.shorten(msg, 400);
    els.globalError.title = msg;
    els.globalError.classList.remove("hidden");
  }

  // ---- Stage navigation ----

  // Furthest stage the session can show: 2 needs OCR text, 3 needs a valid shape (or a YAML draft).
  function maxStage() {
    if (!hasReadyOcr()) return state.yamlText ? 3 : state.szablon ? 2 : 1;
    if (!state.szablon || !state.rawJsonValid) return state.yamlText ? 3 : 2;
    return 3;
  }

  function setStage(num, force) {
    state.stage = Math.max(1, Math.min(force ? 3 : maxStage(), num));
    els.stagePanels.forEach(function (panel, idx) {
      panel.classList.toggle("hidden", idx + 1 !== state.stage);
    });
    const panel = els.stagePanels[state.stage - 1];
    const head = panel.querySelector(".page-head");
    panel.insertBefore(els.stageStatus, head.nextSibling);
    updateStepper();
    try {
      const url = new URL(window.location.href);
      url.searchParams.set("stage", String(state.stage));
      window.history.replaceState(null, "", url.pathname + url.search);
    } catch (_e) {
      // ignore history errors
    }
    if (state.stage === 3 && state.yamlText) {
      updateYamlGutter();
      if (!state.validation) {
        runValidateYaml(false);
      }
    }
  }

  function hasReadyOcr() {
    return state.files.some(function (f) {
      return f.pages && f.pages.length > 0;
    });
  }

  function updateStepper() {
    const done1 = hasReadyOcr();
    const done2 = Boolean(state.szablon && state.rawJsonValid);
    const done3 = Boolean(state.validation && state.validation.valid);
    const doneFlags = [done1, done2, done3];
    const max = maxStage();
    els.stepBtns.forEach(function (btn, idx) {
      const s = idx + 1;
      btn.classList.toggle("active", s === state.stage);
      btn.classList.toggle("done", doneFlags[idx] && s !== state.stage);
      btn.disabled = s > max && s !== state.stage;
      btn.title = btn.disabled ? "Najpierw ukończ poprzedni etap" : "";
    });
    const ready = state.files.filter(function (f) {
      return f.pages && f.pages.length;
    }).length;
    const failed = state.files.filter(function (f) {
      return f.status === "error";
    }).length;
    els.stepMetas[0].textContent = state.files.length
      ? ready + "/" + state.files.length + " odczytane" + (failed ? ", błędy: " + failed : "")
      : "brak plików";
    els.stepMetas[1].textContent = state.szablon
      ? leafPaths(state.szablon, "").length + " pól" + (state.rawJsonValid ? "" : ", błąd JSON")
      : "";
    els.stepMetas[2].textContent = state.validation
      ? (state.validation.valid ? "poprawny" : "błędy: " + (state.validation.errors || []).length) +
        (state.lastTest && state.lastTest.results ? ", test wykonany" : "")
      : state.yamlText
        ? "szkic"
        : "";
  }

  function setBusy(busy, label) {
    state.busy = busy;
    if (busy) {
      els.busyLabel.textContent = label || "Przetwarzanie";
      els.busyTime.setAttribute("data-since", String(Date.now()));
      els.busyTime.textContent = "0:00";
      els.busy.classList.remove("hidden");
    } else {
      els.busyTime.removeAttribute("data-since");
      els.busy.classList.add("hidden");
    }
    updateButtons();
  }

  function updateButtons() {
    const ready = hasReadyOcr();
    const hasFiles = state.files.length > 0;
    els.btnRerunOcr.disabled = state.busy || !hasFiles;
    els.btnToStage2.disabled = state.busy || !ready;
    els.btnProposeSzablon.disabled = state.busy || !ready;
    els.btnRefreshPreview.disabled = state.busy || !ready || !state.szablon || !state.rawJsonValid;
    els.btnToStage3.disabled = state.busy || !ready || !state.szablon || !state.rawJsonValid;
    els.btnProposeYaml.disabled = state.busy || !ready || !state.szablon || !state.rawJsonValid;
    const validYaml = Boolean(state.validation && state.validation.valid);
    els.btnTestPipeline.disabled = state.busy || !ready || !validYaml;
    els.btnSaveYaml.disabled = state.busy || !validYaml;
    els.btnDownloadYaml.disabled = !state.yamlText.trim();
    els.btnReset.disabled = state.busy;
    document.querySelectorAll(".btn-remove-file").forEach(function (b) {
      b.disabled = state.busy;
    });
    els.stage2Empty.classList.toggle("hidden", Boolean(state.szablon) || state.busy);
    els.stage3Empty.classList.toggle("hidden", Boolean(state.yamlText) || state.busy);
  }

  // ---- Stage 1: Files & OCR ----

  function fileMarker(f) {
    if (f.status === "done") return "mk-done";
    if (f.status === "ocr") return "mk-run";
    if (f.status === "error") return "mk-err";
    return "mk-wait";
  }

  function renderFiles() {
    els.fileCounter.textContent = state.files.length + "/" + state.maxFiles;
    els.filesList.innerHTML = "";
    els.filesList.classList.toggle("hidden", !state.files.length);
    if (!state.files.length) {
      updateStepper();
      updateButtons();
      return;
    }

    state.files.forEach(function (f) {
      const item = document.createElement("div");
      item.className = "wfile";

      const head = document.createElement("div");
      head.className = "wfile-head";

      const marker = document.createElement("span");
      marker.className = "mk " + fileMarker(f);

      const title = document.createElement("span");
      title.className = "wfile-name";
      title.textContent = f.filename;
      title.title = f.filename;

      const size = document.createElement("span");
      size.className = "wfile-meta";
      size.textContent = formatBytes(f.size);

      const tag = document.createElement("span");
      tag.className = "wfile-meta";
      if (f.status === "done") {
        tag.textContent = "OCR " + f.pages.length + "/" + (f.total_pages || f.pages.length) + " str.";
      } else if (f.status === "ocr") {
        tag.textContent = "OCR w toku";
      } else if (f.status === "error") {
        tag.textContent = "błąd OCR";
        tag.classList.add("is-err");
      } else {
        tag.textContent = "czeka na OCR";
      }

      const rmBtn = document.createElement("button");
      rmBtn.type = "button";
      rmBtn.className = "btn btn-quiet btn-remove-file";
      rmBtn.textContent = "Usuń";
      rmBtn.title = "Usuń przykład " + f.filename;
      rmBtn.disabled = state.busy;
      rmBtn.addEventListener("click", function () {
        removeFile(f.doc_id);
      });

      head.appendChild(marker);
      head.appendChild(title);
      head.appendChild(size);
      head.appendChild(tag);
      head.appendChild(rmBtn);
      item.appendChild(head);

      if (f.error) {
        const errDiv = document.createElement("div");
        errDiv.className = "wfile-err";
        errDiv.textContent = J.shorten(f.error, 240);
        errDiv.title = f.error;
        item.appendChild(errDiv);
      }

      (f.pages || []).forEach(function (p) {
        const det = document.createElement("details");
        det.className = "wfile-page";
        const sum = document.createElement("summary");
        const leftLabel = document.createElement("span");
        leftLabel.textContent = "Strona " + p.page;
        const rightLabel = document.createElement("span");
        rightLabel.className = "wfile-meta";
        rightLabel.textContent = p.chars + " zn.";
        sum.appendChild(leftLabel);
        sum.appendChild(rightLabel);
        const pre = document.createElement("pre");
        pre.className = "code ocr-text";
        pre.textContent = p.text || "(pusty tekst)";
        det.appendChild(sum);
        det.appendChild(pre);
        item.appendChild(det);
      });

      els.filesList.appendChild(item);
    });

    updateStepper();
    updateButtons();
  }

  function showOcrProgress(done, total, label) {
    if (total <= 0) {
      els.ocrProgressWrap.classList.add("hidden");
      return;
    }
    els.ocrProgressWrap.classList.remove("hidden");
    els.ocrProgressLabel.textContent = label;
    els.ocrProgressCount.textContent = done + "/" + total;
    els.ocrProgressFill.style.width = Math.round((done / total) * 100) + "%";
  }

  function getMaxPages() {
    const n = parseInt(els.maxPagesInput.value, 10);
    if (isNaN(n) || n < 1) return 1;
    if (n > 20) return 20;
    return n;
  }

  async function uploadAndOcr(fileList) {
    const incoming = Array.from(fileList || []);
    if (!incoming.length) return;
    showError("");

    const remaining = state.maxFiles - state.files.length;
    if (remaining <= 0) {
      showError("Osiągnięto limit " + state.maxFiles + " plików PDF.");
      return;
    }
    const batch = incoming.slice(0, remaining);
    if (incoming.length > remaining) {
      showError("Dodano pierwsze " + remaining + " plików (limit: " + state.maxFiles + ").");
    }

    setBusy(true, "Wgrywanie");
    const addedIds = [];
    for (const file of batch) {
      const url = "/api/wizard/upload?filename=" + encodeURIComponent(file.name);
      try {
        const res = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/pdf" },
          body: file,
        });
        const body = await res.json();
        if (!res.ok) {
          showError(file.name + ": " + (body.error || "błąd wgrywania"));
        } else {
          state.files.push(body);
          addedIds.push(body.doc_id);
        }
      } catch (err) {
        showError(file.name + ": " + err.message);
      }
    }
    renderFiles();

    if (addedIds.length) {
      setBusy(true, "OCR");
      await runOcrForIds(addedIds);
    }
    setBusy(false);
  }

  async function runOcrForIds(docIds) {
    const maxPages = getMaxPages();
    state.maxPages = maxPages;
    const total = docIds.length;
    let done = 0;
    let failed = 0;

    for (const docId of docIds) {
      const f = state.files.find(function (x) {
        return x.doc_id === docId;
      });
      if (!f) continue;
      f.status = "ocr";
      f.error = null;
      renderFiles();
      showOcrProgress(done, total, "OCR: " + f.filename);
      els.ocrProgressCount.textContent = done + "/" + total + " ";
      const t = document.createElement("span");
      t.setAttribute("data-since", String(Date.now()));
      t.textContent = "0:00";
      els.ocrProgressCount.appendChild(t);

      const res = await apiJson("/api/wizard/ocr", { doc_id: docId, max_pages: maxPages });
      if (!res.ok) {
        f.status = "error";
        f.error = res.body.error || "Błąd OCR";
      } else if (res.body.file) {
        Object.assign(f, res.body.file);
      }
      done += 1;
      if (f.status === "error") failed += 1;
      showOcrProgress(
        done,
        total,
        (done < total ? "OCR" : "OCR zakończony") + (failed ? " · błędy: " + failed : "")
      );
      renderFiles();
    }
  }

  async function removeFile(docId) {
    showError("");
    const res = await apiJson("/api/wizard/remove", { doc_id: docId });
    if (!res.ok) {
      showError(res.body.error || "Nie udało się usunąć pliku.");
      return;
    }
    applySnapshot(res.body);
  }

  // ---- Stage 2: Interactive Szablon Editor <-> Raw JSON ----

  function leafPaths(node, prefix) {
    const p = prefix || "";
    if (node === null) return [p];
    if (Array.isArray(node)) {
      return node.length ? leafPaths(node[0], p + "[]") : [];
    }
    if (typeof node === "object") {
      let out = [];
      Object.keys(node).forEach(function (k) {
        out = out.concat(leafPaths(node[k], p ? p + "." + k : k));
      });
      return out;
    }
    return [p];
  }

  function validateSzablonClient(node, path) {
    if (!path) {
      if (!node || typeof node !== "object" || Array.isArray(node)) {
        return "Szablon musi być obiektem JSON.";
      }
      if (!Object.keys(node).length) return "Szablon nie może być pustym obiektem.";
    }
    if (node === null) return null;
    if (Array.isArray(node)) {
      if (node.length !== 1) {
        return "Lista `" + path + "` musi mieć dokładnie 1 element wzorcowy (ma " + node.length + ").";
      }
      return validateSzablonClient(node[0], path + "[]");
    }
    if (typeof node === "object") {
      const keys = Object.keys(node);
      if (!keys.length) return "Pusty obiekt: `" + path + "`.";
      for (const k of keys) {
        if (!k.trim()) return "Pusty klucz w `" + (path || "root") + "`.";
        const err = validateSzablonClient(node[k], path ? path + "." + k : k);
        if (err) return err;
      }
      return null;
    }
    return "Liść `" + path + "` musi mieć wartość null (otrzymano: " + JSON.stringify(node) + ").";
  }

  function syncTypyWithSzablon() {
    if (!state.szablon) {
      state.typy = {};
      return;
    }
    const leaves = leafPaths(state.szablon, "");
    const next = {};
    leaves.forEach(function (p) {
      const cur = state.typy[p];
      next[p] = cur === "int" || cur === "float" || cur === "str" ? cur : "str";
    });
    state.typy = next;
  }

  function remapTypyPrefix(oldPrefix, newPrefix) {
    const next = {};
    Object.keys(state.typy).forEach(function (k) {
      if (k === oldPrefix) {
        next[newPrefix] = state.typy[k];
      } else if (k.startsWith(oldPrefix + ".") || k.startsWith(oldPrefix + "[]")) {
        next[newPrefix + k.slice(oldPrefix.length)] = state.typy[k];
      } else {
        next[k] = state.typy[k];
      }
    });
    state.typy = next;
  }

  function uniqueKey(obj, base) {
    if (!(base in obj)) return base;
    let i = 2;
    while (base + "_" + i in obj) i += 1;
    return base + "_" + i;
  }

  function rebuildObjWithOrder(obj, keys, mapFn) {
    const next = {};
    keys.forEach(function (k) {
      const entry = mapFn ? mapFn(k, obj[k]) : [k, obj[k]];
      if (entry) next[entry[0]] = entry[1];
    });
    Object.keys(obj).forEach(function (k) {
      delete obj[k];
    });
    Object.keys(next).forEach(function (k) {
      obj[k] = next[k];
    });
  }

  function nodeKind(val) {
    if (Array.isArray(val)) return "lista";
    if (val !== null && typeof val === "object") return "obiekt";
    return "pole";
  }

  function syncFromTree() {
    syncTypyWithSzablon();
    state.rawJsonValid = true;
    els.rawJsonEditor.value = state.szablon ? JSON.stringify(state.szablon, null, 2) : "";
    els.rawJsonError.classList.add("hidden");
    els.rawJsonError.textContent = "";
    els.rawJsonStatus.textContent = "OK";
    els.rawJsonStatus.className = "tag tag-blue";
    renderSchemaTree();
    updateStepper();
    updateButtons();
  }

  function renderSchemaTree() {
    els.schemaTree.innerHTML = "";
    if (!state.szablon) {
      els.leafCountTag.textContent = "0 pól";
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "Brak pól.";
      els.schemaTree.appendChild(empty);
      return;
    }

    const leaves = leafPaths(state.szablon, "");
    els.leafCountTag.textContent = leaves.length + " pól";

    function buildObjectList(obj, prefix) {
      const wrap = document.createElement("div");
      wrap.className = prefix ? "tree-children" : "tree-list";
      const keys = Object.keys(obj);

      keys.forEach(function (key, idx) {
        const val = obj[key];
        const kind = nodeKind(val);
        const fullPath = prefix ? prefix + "." + key : key;

        const item = document.createElement("div");
        const row = document.createElement("div");
        row.className = "field-row" + (kind !== "pole" ? " is-container" : "");

        const keyInput = document.createElement("input");
        keyInput.type = "text";
        keyInput.className = "input input-sm field-key-input";
        keyInput.value = key;
        keyInput.setAttribute("aria-label", "Nazwa pola");
        keyInput.addEventListener("change", function () {
          const nextKey = keyInput.value.trim();
          if (!nextKey || nextKey === key) {
            keyInput.value = key;
            return;
          }
          if (nextKey in obj) {
            keyInput.value = key;
            return;
          }
          const newPath = prefix ? prefix + "." + nextKey : nextKey;
          remapTypyPrefix(fullPath, newPath);
          rebuildObjWithOrder(obj, keys, function (k, v) {
            return [k === key ? nextKey : k, v];
          });
          syncFromTree();
        });

        const kindSel = document.createElement("select");
        kindSel.className = "select select-sm field-kind-select";
        kindSel.setAttribute("aria-label", "Rodzaj węzła");
        [
          ["pole", "pole"],
          ["obiekt", "obiekt"],
          ["lista", "lista"],
        ].forEach(function (pair) {
          const opt = document.createElement("option");
          opt.value = pair[0];
          opt.textContent = pair[1];
          if (pair[0] === kind) opt.selected = true;
          kindSel.appendChild(opt);
        });
        kindSel.addEventListener("change", function () {
          const nextKind = kindSel.value;
          if (nextKind === kind) return;
          if (nextKind === "pole") {
            obj[key] = null;
            state.typy[fullPath] = "str";
          } else if (nextKind === "obiekt") {
            if (kind === "lista" && Array.isArray(val) && val[0] && typeof val[0] === "object") {
              remapTypyPrefix(fullPath + "[]", fullPath);
              obj[key] = val[0];
            } else {
              obj[key] = { pole: null };
            }
          } else if (nextKind === "lista") {
            if (kind === "obiekt" && val && typeof val === "object") {
              remapTypyPrefix(fullPath, fullPath + "[]");
              obj[key] = [val];
            } else {
              obj[key] = [{ pole: null }];
            }
          }
          syncFromTree();
        });

        row.appendChild(keyInput);
        row.appendChild(kindSel);

        if (kind === "pole") {
          const typeSel = document.createElement("select");
          typeSel.className = "select select-sm field-type-select";
          typeSel.setAttribute("aria-label", "Typ liścia");
          ["str", "int", "float"].forEach(function (t) {
            const opt = document.createElement("option");
            opt.value = t;
            opt.textContent = t;
            if ((state.typy[fullPath] || "str") === t) opt.selected = true;
            typeSel.appendChild(opt);
          });
          typeSel.addEventListener("change", function () {
            state.typy[fullPath] = typeSel.value;
          });
          row.appendChild(typeSel);
        }

        const actions = document.createElement("div");
        actions.className = "field-actions";

        if (kind === "obiekt" || (kind === "lista" && val[0] && typeof val[0] === "object")) {
          const addChild = document.createElement("button");
          addChild.type = "button";
          addChild.className = "btn btn-quiet";
          addChild.textContent = "Dodaj";
          addChild.title = "Dodaj pole w " + fullPath;
          addChild.addEventListener("click", function () {
            const target = kind === "lista" ? val[0] : val;
            target[uniqueKey(target, "nowe_pole")] = null;
            syncFromTree();
          });
          actions.appendChild(addChild);
        }

        const upBtn = document.createElement("button");
        upBtn.type = "button";
        upBtn.className = "btn btn-quiet";
        upBtn.textContent = "Wyżej";
        upBtn.disabled = idx === 0;
        upBtn.addEventListener("click", function () {
          const reordered = keys.slice();
          const tmp = reordered[idx - 1];
          reordered[idx - 1] = reordered[idx];
          reordered[idx] = tmp;
          rebuildObjWithOrder(obj, reordered);
          syncFromTree();
        });

        const downBtn = document.createElement("button");
        downBtn.type = "button";
        downBtn.className = "btn btn-quiet";
        downBtn.textContent = "Niżej";
        downBtn.disabled = idx === keys.length - 1;
        downBtn.addEventListener("click", function () {
          const reordered = keys.slice();
          const tmp = reordered[idx + 1];
          reordered[idx + 1] = reordered[idx];
          reordered[idx] = tmp;
          rebuildObjWithOrder(obj, reordered);
          syncFromTree();
        });

        const delBtn = document.createElement("button");
        delBtn.type = "button";
        delBtn.className = "btn btn-quiet";
        delBtn.textContent = "Usuń";
        delBtn.disabled = keys.length <= 1;
        delBtn.addEventListener("click", function () {
          delete obj[key];
          syncFromTree();
        });

        actions.appendChild(upBtn);
        actions.appendChild(downBtn);
        actions.appendChild(delBtn);
        row.appendChild(actions);
        item.appendChild(row);

        if (kind === "obiekt") {
          item.appendChild(buildObjectList(val, fullPath));
        } else if (kind === "lista" && val[0] && typeof val[0] === "object" && !Array.isArray(val[0])) {
          item.appendChild(buildObjectList(val[0], fullPath + "[]"));
        }

        wrap.appendChild(item);
      });

      return wrap;
    }

    els.schemaTree.appendChild(buildObjectList(state.szablon, ""));
  }

  function handleRawJsonInput() {
    const text = els.rawJsonEditor.value;
    if (!text.trim()) {
      state.rawJsonValid = false;
      els.rawJsonError.textContent = "Szablon JSON jest pusty.";
      els.rawJsonError.classList.remove("hidden");
      els.rawJsonStatus.textContent = "błąd";
      els.rawJsonStatus.className = "tag tag-err";
      updateButtons();
      return;
    }
    let parsed;
    try {
      parsed = JSON.parse(text);
    } catch (err) {
      state.rawJsonValid = false;
      els.rawJsonError.textContent = "Błąd składni JSON: " + err.message;
      els.rawJsonError.classList.remove("hidden");
      els.rawJsonStatus.textContent = "błąd";
      els.rawJsonStatus.className = "tag tag-err";
      updateButtons();
      return;
    }
    const structErr = validateSzablonClient(parsed, "");
    if (structErr) {
      state.rawJsonValid = false;
      els.rawJsonError.textContent = structErr;
      els.rawJsonError.classList.remove("hidden");
      els.rawJsonStatus.textContent = "błąd";
      els.rawJsonStatus.className = "tag tag-err";
      updateButtons();
      return;
    }
    state.szablon = parsed;
    syncTypyWithSzablon();
    state.rawJsonValid = true;
    els.rawJsonError.classList.add("hidden");
    els.rawJsonError.textContent = "";
    els.rawJsonStatus.textContent = "OK";
    els.rawJsonStatus.className = "tag tag-blue";
    renderSchemaTree();
    updateStepper();
    updateButtons();
  }

  function renderPreviews() {
    els.previewTabs.innerHTML = "";
    els.previewBody.innerHTML = "";

    if (!state.previews.length) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "Brak podglądu.";
      els.previewBody.appendChild(empty);
      return;
    }
    if (state.activePreviewIdx >= state.previews.length) {
      state.activePreviewIdx = 0;
    }

    state.previews.forEach(function (item, idx) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "tab" + (idx === state.activePreviewIdx ? " active" : "");
      btn.textContent = item.filename;
      btn.addEventListener("click", function () {
        state.activePreviewIdx = idx;
        renderPreviews();
      });
      els.previewTabs.appendChild(btn);
    });

    const active = state.previews[state.activePreviewIdx];
    const pre = document.createElement("pre");
    pre.className = "json-view";
    pre.innerHTML = renderPrettyJson(active.data, 0);
    els.previewBody.appendChild(pre);
  }

  async function proposeSzablon() {
    showError("");
    setStage(2, true);
    setBusy(true, "LLM proponuje kształt JSON");
    const res = await apiJson("/api/wizard/propose-szablon", {
      hint: els.hintInput.value.trim(),
    });
    setBusy(false);
    if (!res.ok) {
      showError(res.body.error || "Nie udało się zaproponować kształtu JSON.");
      return;
    }
    state.szablon = res.body.szablon;
    state.typy = res.body.typy || {};
    state.previews = res.body.previews || [];
    state.activePreviewIdx = 0;
    syncFromTree();
    renderPreviews();
  }

  async function refreshPreview() {
    if (!state.szablon || !state.rawJsonValid) return;
    showError("");
    setBusy(true, "LLM wypełnia podgląd");
    const res = await apiJson("/api/wizard/preview", {
      szablon: state.szablon,
      typy: state.typy,
    });
    setBusy(false);
    if (!res.ok) {
      showError(res.body.error || "Nie udało się odświeżyć podglądu.");
      return;
    }
    state.previews = res.body.previews || [];
    renderPreviews();
  }

  // ---- Stage 3: Live YAML Editor, Validation, Marker, Test, Save ----

  function updateYamlGutter() {
    const lines = (els.yamlEditor.value || "").split("\n").length;
    els.yamlLinesCount.textContent = lines + " linii";
    const nums = [];
    for (let i = 1; i <= lines; i += 1) nums.push(String(i));
    els.yamlGutter.textContent = nums.join("\n");
    els.yamlGutter.scrollTop = els.yamlEditor.scrollTop;
  }

  function renderValidation(val) {
    state.validation = val;
    els.yamlValidationPanel.innerHTML = "";
    els.overwriteBar.classList.add("hidden");

    if (!val) {
      els.yamlValidChip.textContent = "walidacja";
      els.yamlValidChip.className = "tag";
      updateStepper();
      updateButtons();
      return;
    }

    els.yamlFilenameLabel.textContent = val.filename || "nowa_klasa.yaml";
    if (val.valid) {
      els.yamlValidChip.textContent = "poprawny";
      els.yamlValidChip.className = "tag tag-blue";
      const okRow = document.createElement("div");
      okRow.className = "val-row val-ok";
      okRow.textContent = "Poprawny" + (val.exists ? " · plik istnieje" : "");
      okRow.title = val.target_dir + "/" + val.filename;
      els.yamlValidationPanel.appendChild(okRow);
    } else {
      els.yamlValidChip.textContent = "błędy: " + (val.errors || []).length;
      els.yamlValidChip.className = "tag tag-err";
      (val.errors || []).forEach(function (err) {
        const row = document.createElement("div");
        row.className = "val-row val-err";
        const loc = err.line ? "L" + err.line + (err.column ? ":" + err.column : "") + "  " : "";
        row.textContent = loc + err.message;
        els.yamlValidationPanel.appendChild(row);
      });
    }

    (val.warnings || []).forEach(function (w) {
      const row = document.createElement("div");
      row.className = "val-row val-warn";
      row.textContent = w;
      els.yamlValidationPanel.appendChild(row);
    });

    renderMarker(val.marker);
    updateStepper();
    updateButtons();
  }

  function renderMarker(marker) {
    els.markerResults.innerHTML = "";
    if (!marker || !marker.pattern) {
      els.markerPatternTag.textContent = "brak";
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "Brak znacznika: czytanie do max_stron.";
      els.markerResults.appendChild(empty);
      return;
    }
    els.markerPatternTag.textContent = J.shorten(marker.pattern, 40);
    els.markerPatternTag.title = marker.pattern;
    if (marker.error) {
      const err = document.createElement("div");
      err.className = "note note-err";
      err.textContent = marker.error;
      els.markerResults.appendChild(err);
      return;
    }
    const list = marker.results || [];
    if (!list.length) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "Brak odczytanych stron OCR.";
      els.markerResults.appendChild(empty);
      return;
    }
    list.forEach(function (item) {
      const row = document.createElement("div");
      row.className = "marker-row";
      const head = document.createElement("div");
      head.className = "marker-row-head";

      const fn = document.createElement("span");
      fn.textContent = item.filename;

      const hit = document.createElement("span");
      if (item.matched) {
        hit.className = "tag tag-blue";
        hit.textContent = "str. " + item.first_match_page + ", stop po " + item.would_stop_after_page;
      } else {
        hit.className = "tag tag-warn";
        hit.textContent = "brak (" + item.pages_checked + " str.)";
      }

      head.appendChild(fn);
      head.appendChild(hit);
      row.appendChild(head);

      if (item.snippet) {
        const snip = document.createElement("div");
        snip.className = "marker-snippet";
        snip.textContent = "…" + item.snippet + "…";
        row.appendChild(snip);
      }
      els.markerResults.appendChild(row);
    });
  }

  function renderTestResults(payload) {
    state.lastTest = payload;
    els.testResults.innerHTML = "";
    if (!payload || !payload.results || !payload.results.length) {
      els.testSummaryTag.textContent = "brak";
      els.testSummaryTag.classList.remove("tag-blue", "tag-warn");
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "Test nie był uruchomiony.";
      els.testResults.appendChild(empty);
      return;
    }

    const matched = payload.results.filter(function (r) {
      return r.matched_draft && !r.error;
    }).length;
    els.testSummaryTag.textContent = matched + "/" + payload.results.length + " trafień";
    els.testSummaryTag.classList.remove("tag-blue", "tag-warn");
    els.testSummaryTag.classList.add(matched === payload.results.length ? "tag-blue" : "tag-warn");

    payload.results.forEach(function (r) {
      const card = document.createElement("div");
      card.className = "test-card";

      const head = document.createElement("div");
      head.className = "test-card-head";

      const title = document.createElement("span");
      title.className = "test-name";
      title.textContent = r.filename;
      title.title = r.filename;

      const badges = document.createElement("div");
      badges.className = "test-badges";

      const decTag = document.createElement("span");
      decTag.className = "tag " + (r.error ? "tag-err" : r.matched_draft ? "tag-blue" : "tag-warn");
      decTag.textContent = r.error ? "błąd" : "klasa: " + (r.decision || "inne");
      badges.appendChild(decTag);

      if (!r.error) {
        const pgTag = document.createElement("span");
        pgTag.className = "tag";
        pgTag.textContent = "str: " + r.pages_read;
        badges.appendChild(pgTag);

        const valTag = document.createElement("span");
        valTag.className = "tag " + (r.nulled && r.nulled.length ? "tag-warn" : "tag-blue");
        valTag.textContent =
          r.nulled && r.nulled.length
            ? "wyzerowane: " + r.nulled.length
            : "walidacja OK" + (r.retries ? " (popr.: " + r.retries + ")" : "");
        badges.appendChild(valTag);
      }

      head.appendChild(title);
      head.appendChild(badges);
      card.appendChild(head);

      const body = document.createElement("div");
      body.className = "test-card-body";

      if (r.error) {
        const errDiv = document.createElement("div");
        errDiv.className = "note note-err";
        errDiv.textContent = J.shorten(r.error, 300);
        errDiv.title = r.error;
        body.appendChild(errDiv);
      } else {
        if (r.nulled && r.nulled.length) {
          const note = document.createElement("div");
          note.className = "test-val-note";
          note.textContent = "Wyzerowane pola: " + r.nulled.join(", ");
          body.appendChild(note);
        }
        const pre = document.createElement("pre");
        pre.className = "json-view";
        pre.innerHTML = renderPrettyJson(r.data, 0);
        body.appendChild(pre);
      }

      card.appendChild(body);
      els.testResults.appendChild(card);
    });
  }

  async function proposeYaml() {
    if (!state.szablon || !state.rawJsonValid) return;
    showError("");
    els.saveOkBar.classList.add("hidden");
    setStage(3, true);
    setBusy(true, "LLM generuje YAML");
    const res = await apiJson("/api/wizard/propose-yaml", {
      szablon: state.szablon,
      typy: state.typy,
      hint: els.hintInput.value.trim(),
    });
    setBusy(false);
    if (!res.ok) {
      showError(res.body.error || "Nie udało się wygenerować YAML.");
      return;
    }
    state.yamlText = res.body.yaml_text || "";
    els.yamlEditor.value = state.yamlText;
    updateYamlGutter();
    renderValidation(res.body.validation);
    renderTestResults(null);
  }

  async function runValidateYaml(saveDraft) {
    state.yamlText = els.yamlEditor.value;
    const res = await apiJson("/api/wizard/validate", {
      yaml_text: state.yamlText,
      save_draft: saveDraft !== false,
    });
    if (!res.ok) {
      showError(res.body.error || "Błąd walidacji.");
      return;
    }
    renderValidation(res.body);
  }

  function scheduleValidate() {
    els.saveOkBar.classList.add("hidden");
    els.overwriteBar.classList.add("hidden");
    updateYamlGutter();
    state.yamlText = els.yamlEditor.value;
    updateButtons();
    if (state.validateTimer !== null) {
      window.clearTimeout(state.validateTimer);
    }
    state.validateTimer = window.setTimeout(function () {
      state.validateTimer = null;
      runValidateYaml(true);
    }, 250);
  }

  async function runPipelineTest() {
    showError("");
    setBusy(true, "Test: klasyfikacja, czytanie, ekstrakcja");
    const res = await apiJson("/api/wizard/test", {
      yaml_text: els.yamlEditor.value,
    });
    setBusy(false);
    if (!res.ok) {
      showError(res.body.error || "Test potoku nie powiódł się.");
      return;
    }
    renderTestResults(res.body);
    setRightTab("test");
  }

  async function saveYaml(overwrite) {
    showError("");
    els.saveOkBar.classList.add("hidden");
    els.overwriteBar.classList.add("hidden");
    setBusy(true, "Zapisywanie");
    const res = await apiJson("/api/wizard/save", {
      yaml_text: els.yamlEditor.value,
      overwrite: Boolean(overwrite),
    });
    setBusy(false);
    if (res.status === 409 && res.body.exists) {
      els.overwriteMessage.textContent = res.body.filename + " już istnieje. Nadpisać?";
      els.overwriteMessage.title = res.body.path || res.body.target_dir;
      els.overwriteBar.classList.remove("hidden");
      return;
    }
    if (!res.ok) {
      showError(res.body.error || "Nie udało się zapisać pliku.");
      return;
    }
    els.saveOkBar.textContent = "Zapisano: " + res.body.filename;
    els.saveOkBar.title = res.body.path;
    els.saveOkBar.classList.remove("hidden");
    await runValidateYaml(false);
  }

  function downloadYaml() {
    const text = els.yamlEditor.value;
    if (!text.trim()) return;
    const filename =
      (state.validation && state.validation.filename) || "nowa_klasa.yaml";
    const blob = new Blob([text], { type: "text/yaml;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  // ---- Init & State Restore ----

  function applySnapshot(snap) {
    state.configDir = snap.config_dir || "";
    state.maxFiles = snap.max_files || 5;
    state.maxPages = snap.max_pages || 2;
    state.hint = snap.hint || "";
    state.files = snap.files || [];
    state.szablon = snap.szablon || null;
    state.typy = snap.typy || {};
    state.previews = snap.previews || [];
    state.yamlText = snap.yaml_text || "";
    state.lastTest = snap.last_test || null;

    els.configDirInfo.textContent = "zapis: " + state.configDir;
    els.configDirInfo.title = "Katalog zapisu nowej klasy: " + state.configDir;
    els.maxPagesInput.value = String(state.maxPages);
    if (state.hint) els.hintInput.value = state.hint;

    renderFiles();

    if (state.szablon) {
      syncFromTree();
    } else {
      els.rawJsonEditor.value = "";
      renderSchemaTree();
    }
    renderPreviews();

    els.yamlEditor.value = state.yamlText;
    updateYamlGutter();
    renderTestResults(state.lastTest);
    if (state.yamlText) {
      runValidateYaml(false);
    } else {
      renderValidation(null);
    }
  }

  async function init() {
    const res = await apiJson("/api/wizard/state");
    if (res.ok) {
      applySnapshot(res.body);
    } else {
      showError(res.body.error || "Nie udało się załadować stanu kreatora.");
    }

    const params = new URLSearchParams(window.location.search);
    const reqStage = parseInt(params.get("stage") || "1", 10);
    setStage(reqStage === 2 || reqStage === 3 ? reqStage : 1);
    J.watchJob();
  }

  // ---- Wire up events ----

  els.stepBtns.forEach(function (btn, idx) {
    btn.addEventListener("click", function () {
      setStage(idx + 1);
    });
  });

  els.btnReset.addEventListener("click", function () {
    els.resetConfirm.classList.remove("hidden");
    els.btnResetCancel.focus();
  });
  els.btnResetCancel.addEventListener("click", function () {
    els.resetConfirm.classList.add("hidden");
  });
  els.btnResetConfirm.addEventListener("click", async function () {
    els.resetConfirm.classList.add("hidden");
    showError("");
    els.saveOkBar.classList.add("hidden");
    els.overwriteBar.classList.add("hidden");
    els.ocrProgressWrap.classList.add("hidden");
    const res = await apiJson("/api/wizard/reset", {});
    if (res.ok) {
      els.hintInput.value = "";
      applySnapshot(res.body);
      setStage(1);
    } else {
      showError(res.body.error || "Nie udało się zresetować sesji.");
    }
  });
  els.btnErrorClose.addEventListener("click", function () {
    showError("");
  });
  function setRightTab(which) {
    const marker = which === "marker";
    els.tabTest.classList.toggle("active", !marker);
    els.tabMarker.classList.toggle("active", marker);
    els.testResults.classList.toggle("hidden", marker);
    els.markerResults.classList.toggle("hidden", !marker);
    els.testSummaryTag.classList.toggle("hidden", marker);
    els.markerPatternTag.classList.toggle("hidden", !marker);
  }
  els.tabTest.addEventListener("click", function () {
    setRightTab("test");
  });
  els.tabMarker.addEventListener("click", function () {
    setRightTab("marker");
  });

  // Stage 1 events
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
    uploadAndOcr(els.fileInput.files);
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
    uploadAndOcr(ev.dataTransfer.files);
  });

  els.btnRerunOcr.addEventListener("click", async function () {
    showError("");
    setBusy(true, "OCR");
    await runOcrForIds(
      state.files.map(function (f) {
        return f.doc_id;
      })
    );
    setBusy(false);
  });

  els.btnToStage2.addEventListener("click", function () {
    if (state.szablon) {
      setStage(2);
    } else {
      proposeSzablon();
    }
  });

  // Stage 2 events
  els.btnProposeSzablon.addEventListener("click", proposeSzablon);
  els.btnRefreshPreview.addEventListener("click", refreshPreview);
  els.btnAddRootField.addEventListener("click", function () {
    if (!state.szablon) {
      state.szablon = { dokument: { pole: null } };
    } else {
      state.szablon[uniqueKey(state.szablon, "nowe_pole")] = null;
    }
    syncFromTree();
  });
  els.rawJsonEditor.addEventListener("input", handleRawJsonInput);
  els.btnToStage3.addEventListener("click", function () {
    if (state.yamlText) {
      setStage(3);
    } else {
      proposeYaml();
    }
  });

  // Stage 3 events
  els.btnProposeYaml.addEventListener("click", proposeYaml);
  els.btnTestPipeline.addEventListener("click", runPipelineTest);
  els.btnDownloadYaml.addEventListener("click", downloadYaml);
  els.btnSaveYaml.addEventListener("click", function () {
    saveYaml(false);
  });
  els.btnConfirmOverwrite.addEventListener("click", function () {
    saveYaml(true);
  });
  els.btnCancelOverwrite.addEventListener("click", function () {
    els.overwriteBar.classList.add("hidden");
  });
  els.yamlEditor.addEventListener("input", scheduleValidate);
  els.yamlEditor.addEventListener("scroll", function () {
    els.yamlGutter.scrollTop = els.yamlEditor.scrollTop;
  });

  init();
})();
