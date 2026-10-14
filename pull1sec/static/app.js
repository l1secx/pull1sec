/* Pull1sec front end — no framework, no build step. */

const I18N = {
  tr: {
    "brand.sub": "yerel video indirici",
    "intro.title": "Bir bağlantı yapıştır, videoyu al.",
    "intro.body":
      "YouTube, TikTok, Instagram, X, Facebook, Reddit, Vimeo, Twitch ve yt-dlp'nin tanıdığı 1800'den fazla site. Dosya bu makinede kalır.",
    "input.title": "İndirilecek video",
    "input.label": "Video bağlantısı",
    "input.paste": "Yapıştır",
    "input.analyze": "Analiz et",
    "input.analyzing": "Analiz ediliyor",
    "advanced.summary": "Giriş gerektiren gönderiler",
    "advanced.label": "Çerezleri tarayıcıdan al",
    "advanced.off": "Kapalı",
    "advanced.hint":
      "Özel hesaplar, yaş kısıtı veya bot kontrolü için. Tarayıcıda oturum açmış olman gerekir.",
    "preview.title": "Önizleme",
    "preview.live": "Canlı",
    "preview.video": "Video",
    "preview.audio": "Ses",
    "preview.quality": "Kalite",
    "preview.format": "Biçim",
    "preview.download": "İndir",
    "preview.best": "En iyi kalite",
    "preview.audioOnly": "Ses dosyası olarak indir",
    "preview.views": "görüntülenme",
    "activity.title": "Etkinlik",
    "activity.empty": "Henüz indirme yok.",
    "activity.clear": "Bitmişleri temizle",
    "job.cancel": "İptal",
    "job.save": "Kaydet",
    "job.saved": "Tekrar kaydet",
    "job.remove": "Kaldır",
    "job.queued": "sırada",
    "job.downloading": "indiriliyor",
    "job.processing": "işleniyor",
    "job.completed": "tamamlandı",
    "job.failed": "başarısız",
    "job.canceled": "iptal edildi",
    "job.merging": "Ses ve görüntü birleştiriliyor…",
    "job.converting_audio": "Ses dönüştürülüyor…",
    "job.postprocessing": "Son işlemler…",
    "job.processing.generic": "Dosya hazırlanıyor…",
    "job.canceling": "İptal ediliyor…",
    "job.speed": "hız",
    "job.eta": "kalan",
    "status.probing": "Bağlantı inceleniyor…",
    "status.ready": "{title} hazır. Kaliteyi seçip indir.",
    "status.invalid": "Geçerli bir video bağlantısı gir.",
    "status.pasted": "Bağlantı yapıştırıldı.",
    "status.pasteFailed": "Panoya erişilemedi. Bağlantıyı elle yapıştır.",
    "status.started": "İndirme başladı.",
    "footer.note": "Dosyalar bir saat sonra otomatik silinir.",
    "footer.api": "API",
    "footer.engine": "yt-dlp {version}",
  },
  en: {
    "brand.sub": "local video downloader",
    "intro.title": "Paste a link, get the video.",
    "intro.body":
      "YouTube, TikTok, Instagram, X, Facebook, Reddit, Vimeo, Twitch and the 1800+ sites yt-dlp knows. The file stays on this machine.",
    "input.title": "Video to download",
    "input.label": "Video link",
    "input.paste": "Paste",
    "input.analyze": "Analyze",
    "input.analyzing": "Analyzing",
    "advanced.summary": "Posts that need a login",
    "advanced.label": "Take cookies from browser",
    "advanced.off": "Off",
    "advanced.hint":
      "For private accounts, age gates or bot checks. You must be signed in in that browser.",
    "preview.title": "Preview",
    "preview.live": "Live",
    "preview.video": "Video",
    "preview.audio": "Audio",
    "preview.quality": "Quality",
    "preview.format": "Format",
    "preview.download": "Download",
    "preview.best": "Best available",
    "preview.audioOnly": "Download as audio",
    "preview.views": "views",
    "activity.title": "Activity",
    "activity.empty": "No downloads yet.",
    "activity.clear": "Clear finished",
    "job.cancel": "Cancel",
    "job.save": "Save",
    "job.saved": "Save again",
    "job.remove": "Remove",
    "job.queued": "queued",
    "job.downloading": "downloading",
    "job.processing": "processing",
    "job.completed": "done",
    "job.failed": "failed",
    "job.canceled": "canceled",
    "job.merging": "Merging audio and video…",
    "job.converting_audio": "Converting audio…",
    "job.postprocessing": "Finishing up…",
    "job.processing.generic": "Preparing file…",
    "job.canceling": "Canceling…",
    "job.speed": "speed",
    "job.eta": "left",
    "status.probing": "Reading the link…",
    "status.ready": "{title} is ready. Pick a quality and download.",
    "status.invalid": "Enter a valid video link.",
    "status.pasted": "Link pasted.",
    "status.pasteFailed": "Could not read the clipboard. Paste it manually.",
    "status.started": "Download started.",
    "footer.note": "Files are deleted automatically after an hour.",
    "footer.api": "API",
    "footer.engine": "yt-dlp {version}",
  },
};

const TERMINAL = new Set(["completed", "failed", "canceled"]);
const TERMINAL_SOURCE = { completed: "job.completed", failed: "job.failed", canceled: "job.canceled" };
const STORAGE = { lang: "pull1sec.lang", theme: "pull1sec.theme", jobs: "pull1sec.jobs" };

const state = {
  lang: "tr",
  media: null,
  mode: "video",
  jobs: new Map(),
  streams: new Map(),
};

const el = {
  form: document.getElementById("fetch-form"),
  url: document.getElementById("url"),
  paste: document.getElementById("paste-btn"),
  cookies: document.getElementById("cookies"),
  analyze: document.getElementById("analyze-btn"),
  analyzeLabel: document.querySelector("#analyze-btn span"),
  status: document.getElementById("status"),
  preview: document.getElementById("preview"),
  media: document.querySelector(".preview-media"),
  thumb: document.getElementById("preview-thumb"),
  platform: document.getElementById("preview-platform"),
  live: document.getElementById("preview-live"),
  name: document.getElementById("preview-name"),
  meta: document.getElementById("preview-meta"),
  quality: document.getElementById("quality"),
  qualityField: document.getElementById("quality-field"),
  audioFormat: document.getElementById("audio-format"),
  formatField: document.getElementById("format-field"),
  download: document.getElementById("download-btn"),
  jobList: document.getElementById("job-list"),
  jobTemplate: document.getElementById("job-template"),
  activityEmpty: document.getElementById("activity-empty"),
  clearFinished: document.getElementById("clear-finished"),
  themeToggle: document.getElementById("theme-toggle"),
  langToggle: document.getElementById("lang-toggle"),
  langLabel: document.getElementById("lang-label"),
  engine: document.getElementById("engine-version"),
  segments: Array.from(document.querySelectorAll(".seg")),
};

/* ------------------------------------------------------------------ i18n */

function t(key, vars) {
  const dict = I18N[state.lang] || I18N.en;
  let text = dict[key] ?? I18N.en[key] ?? key;
  if (vars) {
    for (const [name, value] of Object.entries(vars)) {
      text = text.replaceAll(`{${name}}`, String(value));
    }
  }
  return text;
}

function applyLang(lang) {
  state.lang = I18N[lang] ? lang : "en";
  document.documentElement.lang = state.lang;
  localStorage.setItem(STORAGE.lang, state.lang);
  el.langLabel.textContent = state.lang === "tr" ? "EN" : "TR";

  document.querySelectorAll("[data-i18n]").forEach((node) => {
    const text = I18N[state.lang][node.dataset.i18n];
    if (text != null) node.textContent = text;
  });
  document.querySelectorAll("[data-i18n-aria]").forEach((node) => {
    const text = I18N[state.lang][node.dataset.i18nAria];
    if (text != null) node.setAttribute("aria-label", text);
  });

  if (state.media) renderPreview();
  state.jobs.forEach((job) => renderJob(job));
}

/* ------------------------------------------------------------------ theme */

function effectiveTheme() {
  const explicit = document.documentElement.dataset.theme;
  if (explicit === "light" || explicit === "dark") return explicit;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem(STORAGE.theme, theme);
}

/* ------------------------------------------------------------------- api */

async function api(path, { method = "GET", body } = {}) {
  const response = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok || (payload && payload.ok === false)) {
    const message = payload?.error?.message || `HTTP ${response.status}`;
    const error = new Error(message);
    error.code = payload?.error?.code || "error";
    throw error;
  }
  return payload;
}

/* ------------------------------------------------------------ formatting */

function formatBytes(bytes) {
  if (!bytes || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${index === 0 ? Math.round(value) : value.toFixed(1)} ${units[index]}`;
}

function formatSpeed(bytesPerSecond) {
  return bytesPerSecond ? `${formatBytes(bytesPerSecond)}/s` : "";
}

function formatDuration(seconds) {
  if (!seconds || seconds < 0) return "";
  const total = Math.round(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return hours ? `${hours}:${pad(minutes)}:${pad(secs)}` : `${minutes}:${pad(secs)}`;
}

function formatCount(value) {
  if (value == null) return "";
  // Compact for big numbers so the meta line stays on one row.
  const options = value >= 10_000
    ? { notation: "compact", maximumFractionDigits: 1 }
    : undefined;
  return new Intl.NumberFormat(state.lang, options).format(value);
}

/* --------------------------------------------------------------- preview */

function renderPreview() {
  const media = state.media;
  if (!media) return;

  el.name.textContent = media.title;
  el.platform.textContent = media.platform;
  el.live.hidden = !media.is_live;

  if (media.thumbnail) {
    // Proxied first: CDN images often reject a request without a referer.
    el.thumb.onerror = () => {
      el.thumb.onerror = null;
      el.thumb.src = media.thumbnail;
    };
    el.thumb.src = `/api/thumbnail?url=${encodeURIComponent(media.thumbnail)}`;
    el.thumb.alt = media.title;
    el.media.classList.remove("is-empty");
  } else {
    el.thumb.onerror = null;
    el.thumb.removeAttribute("src");
    el.thumb.alt = "";
    el.media.classList.add("is-empty");
  }

  const meta = [];
  if (media.uploader) meta.push(media.uploader);
  if (media.duration) meta.push(formatDuration(media.duration));
  if (media.view_count != null) meta.push(`${formatCount(media.view_count)} ${t("preview.views")}`);
  if (media.upload_date) meta.push(formatUploadDate(media.upload_date));
  el.meta.replaceChildren(
    ...meta.map((text) => {
      const span = document.createElement("span");
      span.textContent = text;
      return span;
    }),
  );

  renderQualityOptions(media);
  renderAudioOptions(media);
  applyMode();

  el.preview.hidden = false;
  el.preview.classList.remove("is-new");
  void el.preview.offsetWidth;
  el.preview.classList.add("is-new");
}

function formatUploadDate(raw) {
  if (!/^\d{8}$/.test(raw)) return raw;
  const year = raw.slice(0, 4);
  const month = raw.slice(4, 6);
  const day = raw.slice(6, 8);
  return `${day}.${month}.${year}`;
}

function renderQualityOptions(media) {
  const previous = el.quality.value;
  const options = [];

  options.push({ value: "", label: t("preview.best") });
  media.qualities.forEach((quality) => {
    options.push({ value: String(quality.height), label: quality.label });
  });

  el.quality.replaceChildren(
    ...options.map((option) => {
      const node = document.createElement("option");
      node.value = option.value;
      node.textContent = option.label;
      return node;
    }),
  );
  if (options.some((option) => option.value === previous)) el.quality.value = previous;
}

function renderAudioOptions(media) {
  const formats = media.audio_formats?.length ? media.audio_formats : ["mp3", "m4a"];
  const previous = el.audioFormat.value;
  el.audioFormat.replaceChildren(
    ...formats.map((format) => {
      const node = document.createElement("option");
      node.value = format;
      node.textContent = format.toUpperCase();
      return node;
    }),
  );
  if (formats.includes(previous)) el.audioFormat.value = previous;
}

function applyMode() {
  const audio = state.mode === "audio";
  el.segments.forEach((button) => {
    button.setAttribute("aria-checked", String(button.dataset.mode === state.mode));
  });
  el.qualityField.hidden = audio;
  el.formatField.hidden = !audio;
  el.download.querySelector("span").textContent = audio ? t("preview.audioOnly") : t("preview.download");
}

/* ------------------------------------------------------------- status line */

function setStatus(message, { error = false } = {}) {
  el.status.textContent = message || "";
  el.status.classList.toggle("status--error", Boolean(error));
}

/* ------------------------------------------------------------------- jobs */

function jobFromPayload(raw) {
  state.jobs.set(raw.id, raw);
  return raw;
}

function upsertJob(raw, { isNew = false } = {}) {
  const existing = state.jobs.get(raw.id);
  const job = { ...(existing || {}), ...raw };
  state.jobs.set(job.id, job);
  renderJob(job, { isNew: isNew && !existing });
  return job;
}

function renderJob(job, { isNew = false } = {}) {
  let node = el.jobList.querySelector(`[data-job="${job.id}"]`);
  if (!node) {
    node = el.jobTemplate.content.firstElementChild.cloneNode(true);
    node.dataset.job = job.id;
    if (isNew) node.classList.add("is-new");
    node.querySelector(".job-remove").addEventListener("click", () => removeJob(job.id));
    node.querySelector(".job-cancel").addEventListener("click", () => cancelJob(job.id));
    el.jobList.prepend(node);
  }

  node.className = `job job--${job.status}`;
  node.querySelector(".job-platform").textContent = job.platform || "—";
  node.querySelector(".job-state").textContent = t(`job.${job.status}`);

  const title = job.title || job.url;
  node.querySelector(".job-title").textContent = title;

  const bar = node.querySelector(".bar");
  const fill = node.querySelector(".bar-fill");
  const showBar = !TERMINAL.has(job.status);
  bar.style.display = showBar ? "" : "none";
  fill.style.width = `${job.percent || 0}%`;
  fill.classList.toggle("is-indeterminate", job.status === "queued");
  bar.setAttribute("aria-valuenow", String(Math.round(job.percent || 0)));

  const detail = node.querySelector(".job-detail");
  detail.textContent = describeJob(job);

  const errorNode = node.querySelector(".job-error");
  if (job.status === "failed" && job.error) {
    errorNode.textContent = job.error;
    errorNode.hidden = false;
  } else {
    errorNode.hidden = true;
  }

  const cancel = node.querySelector(".job-cancel");
  cancel.hidden = TERMINAL.has(job.status);

  const save = node.querySelector(".job-save");
  if (job.status === "completed" && job.download_url) {
    const link = `${job.download_url}?v=${Math.round(job.finished_at || 0)}`;
    save.href = link;
    save.hidden = false;
    const label = save.dataset.saved === "1" ? t("job.saved") : t("job.save");
    save.textContent = label;
    save.onclick = () => {
      save.dataset.saved = "1";
      save.textContent = t("job.saved");
    };
  } else {
    save.hidden = true;
  }

  updateActivityEmpty();
}

function describeJob(job) {
  switch (job.status) {
    case "queued":
      return t("job.canceling") === job.message ? t("job.canceling") : t("job.queued");
    case "downloading": {
      const parts = [`${(job.percent || 0).toFixed(0)}%`];
      if (job.total_bytes) parts.push(`${formatBytes(job.downloaded_bytes)} / ${formatBytes(job.total_bytes)}`);
      else if (job.downloaded_bytes) parts.push(formatBytes(job.downloaded_bytes));
      const speed = formatSpeed(job.speed);
      if (speed) parts.push(speed);
      if (job.eta) parts.push(`${t("job.eta")} ${formatDuration(job.eta)}`);
      return parts.join(" · ");
    }
    case "processing":
      return t(`job.${job.message || "processing.generic"}`);
    case "completed":
      return job.filesize ? formatBytes(job.filesize) : t("job.completed");
    case "failed":
      return t("job.failed");
    case "canceled":
      return t("job.canceled");
    default:
      return "";
  }
}

function updateActivityEmpty() {
  el.activityEmpty.hidden = state.jobs.size > 0;
}

function rememberJobs() {
  const ids = Array.from(state.jobs.keys()).slice(0, 40);
  localStorage.setItem(STORAGE.jobs, JSON.stringify(ids));
}

async function removeJob(id) {
  closeStream(id);
  state.jobs.delete(id);
  const node = el.jobList.querySelector(`[data-job="${id}"]`);
  if (node) node.remove();
  updateActivityEmpty();
  rememberJobs();
  try {
    await api(`/api/jobs/${id}`, { method: "DELETE" });
  } catch {
    /* already gone on the server — nothing to do */
  }
}

async function cancelJob(id) {
  try {
    const job = await api(`/api/jobs/${id}/cancel`, { method: "POST" });
    upsertJob(job);
  } catch (error) {
    setStatus(error.message, { error: true });
  }
}

async function clearFinished() {
  const finished = Array.from(state.jobs.values()).filter((job) => TERMINAL.has(job.status));
  await Promise.allSettled(finished.map((job) => removeJob(job.id)));
}

/* ------------------------------------------------------------------- SSE */

function subscribe(jobId) {
  if (state.streams.has(jobId)) return;
  const source = new EventSource(`/api/jobs/${jobId}/events`);
  state.streams.set(jobId, source);

  const handle = (event) => {
    let payload;
    try {
      payload = JSON.parse(event.data);
    } catch {
      return;
    }
    upsertJob(payload);
    if (TERMINAL.has(payload.status)) closeStream(jobId);
  };

  source.addEventListener("job", handle);
  source.addEventListener("completed", handle);
  source.addEventListener("failed", handle);
  source.addEventListener("canceled", handle);
  source.addEventListener("error", async () => {
    // The server closes the stream when a job ends; verify once before retrying.
    try {
      const job = await api(`/api/jobs/${jobId}`);
      upsertJob(job);
      if (TERMINAL.has(job.status)) closeStream(jobId);
    } catch {
      closeStream(jobId);
    }
  });
}

function closeStream(jobId) {
  const source = state.streams.get(jobId);
  if (source) {
    source.close();
    state.streams.delete(jobId);
  }
  rememberJobs();
}

/* --------------------------------------------------------------- actions */

async function analyze(url) {
  setStatus(t("status.probing"));
  el.analyze.classList.add("is-busy");
  el.analyze.disabled = true;
  const label = el.analyzeLabel.textContent;
  el.analyzeLabel.textContent = t("input.analyzing");

  try {
    const payload = await api("/api/probe", {
      method: "POST",
      body: { url, cookies_from_browser: el.cookies.value || null },
    });
    state.media = payload.media;
    el.url.value = payload.media.webpage_url || url;
    renderPreview();
    setStatus(t("status.ready", { title: truncate(payload.media.title, 60) }));
  } catch (error) {
    state.media = null;
    el.preview.hidden = true;
    el.form.classList.add("input-invalid");
    setStatus(error.message, { error: true });
  } finally {
    el.analyze.classList.remove("is-busy");
    el.analyze.disabled = false;
    el.analyzeLabel.textContent = label;
  }
}

function truncate(text, limit) {
  if (!text) return "";
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
}

async function startDownload() {
  if (!state.media) return;
  const audio = state.mode === "audio";
  el.download.disabled = true;

  try {
    const payload = await api("/api/download", {
      method: "POST",
      body: {
        url: state.media.webpage_url || el.url.value.trim(),
        mode: state.mode,
        height: audio ? null : el.quality.value ? Number(el.quality.value) : null,
        audio_format: el.audioFormat.value || "mp3",
        cookies_from_browser: el.cookies.value || null,
      },
    });
    upsertJob(payload.job, { isNew: true });
    subscribe(payload.job.id);
    rememberJobs();
    setStatus(t("status.started"));
  } catch (error) {
    setStatus(error.message, { error: true });
  } finally {
    el.download.disabled = false;
  }
}

async function pasteFromClipboard() {
  try {
    const text = await navigator.clipboard.readText();
    if (!text) return;
    el.url.value = text.trim().split(/\s+/)[0];
    el.form.classList.remove("input-invalid");
    setStatus(t("status.pasted"));
  } catch {
    setStatus(t("status.pasteFailed"), { error: true });
  }
}

async function restoreJobs() {
  let ids = [];
  try {
    ids = JSON.parse(localStorage.getItem(STORAGE.jobs) || "[]");
  } catch {
    ids = [];
  }
  if (!Array.isArray(ids) || ids.length === 0) return;

  const results = await Promise.allSettled(ids.map((id) => api(`/api/jobs/${id}`)));
  results.forEach((result) => {
    if (result.status !== "fulfilled") return;
    const job = upsertJob(result.value);
    if (!TERMINAL.has(job.status)) subscribe(job.id);
  });
  rememberJobs();
}

async function loadMeta() {
  try {
    const [meta, health] = await Promise.all([api("/api/meta"), api("/api/health")]);

    // Built in one pass: prepending later would leave the first option selected.
    const off = document.createElement("option");
    off.value = "";
    off.dataset.i18n = "advanced.off";
    off.textContent = t("advanced.off");

    const browserOptions = meta.cookie_browsers.map((browser) => {
      const node = document.createElement("option");
      node.value = browser;
      node.textContent = browser[0].toUpperCase() + browser.slice(1);
      return node;
    });

    el.cookies.replaceChildren(off, ...browserOptions);
    el.cookies.value = "";

    if (health?.yt_dlp) el.engine.textContent = t("footer.engine", { version: health.yt_dlp });
  } catch {
    /* meta is decorative; the app still works without it */
  }
}

/* -------------------------------------------------------------------- init */

function init() {
  const storedLang = localStorage.getItem(STORAGE.lang);
  const browserLang = (navigator.language || "en").toLowerCase().startsWith("tr") ? "tr" : "en";
  applyLang(storedLang || browserLang);

  const storedTheme = localStorage.getItem(STORAGE.theme);
  if (storedTheme === "light" || storedTheme === "dark") document.documentElement.dataset.theme = storedTheme;

  el.themeToggle.addEventListener("click", () => setTheme(effectiveTheme() === "dark" ? "light" : "dark"));
  el.langToggle.addEventListener("click", () => applyLang(state.lang === "tr" ? "en" : "tr"));

  el.form.addEventListener("submit", (event) => {
    event.preventDefault();
    const url = el.url.value.trim();
    el.form.classList.remove("input-invalid");
    if (!url) {
      el.form.classList.add("input-invalid");
      setStatus(t("status.invalid"), { error: true });
      el.url.focus();
      return;
    }
    analyze(url);
  });

  el.url.addEventListener("input", () => el.form.classList.remove("input-invalid"));
  el.paste.addEventListener("click", pasteFromClipboard);
  el.download.addEventListener("click", startDownload);
  el.clearFinished.addEventListener("click", clearFinished);

  el.segments.forEach((button) => {
    button.addEventListener("click", () => {
      state.mode = button.dataset.mode;
      applyMode();
    });
  });

  loadMeta();
  restoreJobs();
}

init();
