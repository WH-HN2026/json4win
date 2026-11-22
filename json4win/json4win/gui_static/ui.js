"use strict";

/* Shared helpers for every view: escaping, JSON viewer, API calls, elapsed timers and the
   global job indicator in the header (it shows the processing job on every view). */
window.J4W = (function () {
  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function punct(s) {
    return '<span class="json-punct">' + s + "</span>";
  }

  function renderJson(value, indent) {
    const level = indent || 0;
    const pad = "  ".repeat(level);
    const childPad = "  ".repeat(level + 1);
    if (value === null) return '<span class="json-null">null</span>';
    if (typeof value === "string") {
      return '<span class="json-string">' + escapeHtml(JSON.stringify(value)) + "</span>";
    }
    if (typeof value === "number") return '<span class="json-number">' + String(value) + "</span>";
    if (typeof value === "boolean") return '<span class="json-bool">' + String(value) + "</span>";
    if (Array.isArray(value)) {
      if (!value.length) return punct("[]");
      const items = value.map(function (item, idx) {
        return childPad + renderJson(item, level + 1) + (idx < value.length - 1 ? punct(",") : "");
      });
      return punct("[") + "\n" + items.join("\n") + "\n" + pad + punct("]");
    }
    if (typeof value === "object") {
      const keys = Object.keys(value);
      if (!keys.length) return punct("{}");
      const entries = keys.map(function (key, idx) {
        const val = value[key];
        const line =
          childPad +
          '<span class="json-key">' +
          escapeHtml(JSON.stringify(key)) +
          "</span>" +
          punct(": ") +
          renderJson(val, level + 1) +
          (idx < keys.length - 1 ? punct(",") : "");
        return val === null ? '<span class="json-null-entry">' + line + "</span>" : line;
      });
      return punct("{") + "\n" + entries.join("\n") + "\n" + pad + punct("}");
    }
    return escapeHtml(String(value));
  }

  async function api(url, payload) {
    let res;
    try {
      res = await fetch(url, {
        method: payload === undefined ? "GET" : "POST",
        cache: "no-store",
        headers: payload === undefined ? {} : { "Content-Type": "application/json" },
        body: payload === undefined ? undefined : JSON.stringify(payload),
      });
    } catch (err) {
      return { ok: false, status: 0, body: { error: "Brak połączenia z serwerem." } };
    }
    const body = await res.json().catch(function () {
      return { error: "Niepoprawna odpowiedź serwera (HTTP " + res.status + ")." };
    });
    return { ok: res.ok, status: res.status, body: body };
  }

  async function uploadPdf(url, file) {
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/pdf" },
        body: file,
      });
      const body = await res.json().catch(function () {
        return { error: "HTTP " + res.status };
      });
      return { ok: res.ok, status: res.status, body: body };
    } catch (err) {
      return { ok: false, status: 0, body: { error: "Brak połączenia z serwerem." } };
    }
  }

  function formatBytes(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  function formatElapsed(ms) {
    const s = Math.max(0, Math.floor(ms / 1000));
    const m = Math.floor(s / 60);
    return m + ":" + String(s % 60).padStart(2, "0");
  }

  function shorten(text, max) {
    const t = String(text || "");
    return t.length > max ? t.slice(0, max - 1) + "…" : t;
  }

  // Every element with data-since="<epoch ms>" shows the elapsed time, refreshed once a second.
  function tick() {
    const now = Date.now();
    document.querySelectorAll("[data-since]").forEach(function (el) {
      const since = Number(el.getAttribute("data-since"));
      if (since) el.textContent = formatElapsed(now - since);
    });
  }
  window.setInterval(tick, 1000);

  // Start time of a job (or of a file inside a job), first seen by this browser tab.
  function since(key) {
    const k = "j4w-since-" + key;
    let v = null;
    try {
      v = window.sessionStorage.getItem(k);
    } catch (_e) {
      v = null;
    }
    if (!v) {
      v = String(Date.now());
      try {
        window.sessionStorage.setItem(k, v);
      } catch (_e) {
        // storage unavailable: timer restarts on reload
      }
    }
    return Number(v);
  }

  // ---- Global job indicator (header) ----
  const jobEls = {
    pill: document.getElementById("job-pill"),
    mk: document.getElementById("job-mk"),
    label: document.getElementById("job-label"),
    count: document.getElementById("job-count"),
    time: document.getElementById("job-time"),
    line: document.getElementById("jobline-fill"),
  };

  function renderJob(job) {
    if (!jobEls.pill) return;
    const pill = jobEls.pill;
    pill.classList.remove("running", "done", "has-errors");
    if (!job || !job.id || !job.total) {
      pill.classList.add("hidden");
      jobEls.line.style.width = "0";
      return;
    }
    pill.classList.remove("hidden");
    const count = job.completed + "/" + job.total;
    jobEls.count.textContent = count;
    if (job.running) {
      pill.classList.add("running");
      jobEls.mk.className = "mk mk-run";
      jobEls.label.textContent = "Przetwarzanie";
      jobEls.time.setAttribute("data-since", String(since("job-" + job.id)));
      jobEls.time.classList.remove("hidden");
      jobEls.line.style.width = Math.max(3, Math.round((job.completed / job.total) * 100)) + "%";
      pill.title = "Przetwarzanie w toku: " + count;
    } else {
      jobEls.time.removeAttribute("data-since");
      jobEls.time.classList.add("hidden");
      jobEls.line.style.width = "0";
      if (job.failed > 0) {
        pill.classList.add("has-errors");
        jobEls.mk.className = "mk mk-err";
        jobEls.label.textContent = "Błędy: " + job.failed;
        pill.title = "Zakończono z błędami: " + job.failed;
      } else {
        pill.classList.add("done");
        jobEls.mk.className = "mk mk-done";
        jobEls.label.textContent = "Gotowe";
        pill.title = "Przetwarzanie zakończone";
      }
    }
    tick();
  }

  // Views without their own polling (the wizard) watch the job through /api/status.
  let watchTimer = null;
  async function watchJob() {
    const res = await api("/api/status");
    if (!res.ok) return;
    renderJob(res.body);
    if (res.body.running && watchTimer === null) {
      watchTimer = window.setInterval(async function () {
        const r = await api("/api/status");
        if (!r.ok) return;
        renderJob(r.body);
        if (!r.body.running) {
          window.clearInterval(watchTimer);
          watchTimer = null;
        }
      }, 1500);
    }
  }

  // A file dropped outside a drop zone must not make the browser open it instead of the app.
  window.addEventListener("dragover", function (ev) {
    ev.preventDefault();
  });
  window.addEventListener("drop", function (ev) {
    ev.preventDefault();
  });

  // Drag & drop + click-to-pick on a drop zone backed by an <input type=file>.
  function bindDrop(zone, onFiles, pick) {
    zone.addEventListener("dragover", function (ev) {
      ev.preventDefault();
      zone.classList.add("dragover");
    });
    zone.addEventListener("dragleave", function (ev) {
      if (!zone.contains(ev.relatedTarget)) zone.classList.remove("dragover");
    });
    zone.addEventListener("drop", function (ev) {
      ev.preventDefault();
      ev.stopPropagation();
      zone.classList.remove("dragover");
      onFiles(ev.dataTransfer.files);
    });
    if (pick) {
      zone.addEventListener("click", pick);
      zone.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          pick();
        }
      });
    }
  }

  return {
    escapeHtml: escapeHtml,
    renderJson: renderJson,
    api: api,
    uploadPdf: uploadPdf,
    formatBytes: formatBytes,
    formatElapsed: formatElapsed,
    shorten: shorten,
    since: since,
    tick: tick,
    renderJob: renderJob,
    watchJob: watchJob,
    bindDrop: bindDrop,
  };
})();
