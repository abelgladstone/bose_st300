"use strict";

const $ = (id) => document.getElementById(id);

// Mount prefix injected by the server (e.g. "/bose" behind the proxy, "" at root).
// All API and SSE URLs are built from it so the app works under any subpath.
const BASE = window.BOSE_BASE || "";
const api = (path) => BASE + path;

// While a finger is down on a slider, incoming pushes for that control are ignored --
// otherwise the speaker's own echo fights the thumb and it jumps around.
const dragging = new Set();
let ranges = {};

async function post(path, body) {
  try {
    const res = await fetch(api(path), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || res.statusText);
    setStatus("");
    return res.json();
  } catch (err) {
    setStatus(err.message, true);
  }
}

function setStatus(message, isError = false) {
  const footer = $("footer");
  footer.textContent = message;
  footer.classList.toggle("error", isError);
}

/** Send at most one request per frame-ish while dragging, always sending the last value. */
function throttle(fn, ms = 120) {
  let timer = null;
  let pending = null;
  return (...args) => {
    pending = args;
    if (timer) return;
    timer = setTimeout(() => {
      timer = null;
      if (pending) fn(...pending);
      pending = null;
    }, ms);
  };
}

// Bipolar controls read +N / 0 / -N; a lone "40" hides that these swing both ways.
const BIPOLAR = new Set(["bass", "treble", "center", "surround"]);

function fmt(id, value) {
  const n = Number(value);
  if (!BIPOLAR.has(id)) return String(n);
  return n > 0 ? `+${n}` : String(n);
}

// Fill the track outward from the 0 point rather than from the left edge, so the
// thumb's side of centre shows whether the trim is positive or negative at a glance.
function paintFill(id) {
  const el = $(id);
  const min = Number(el.min);
  const max = Number(el.max);
  const val = Number(el.value);
  const pct = (x) => ((x - min) / (max - min)) * 100;
  if (BIPOLAR.has(id)) {
    const zero = pct(0);
    const here = pct(val);
    const [a, b] = here >= zero ? [zero, here] : [here, zero];
    el.style.setProperty("--fill-start", `${a}%`);
    el.style.setProperty("--fill-end", `${b}%`);
    el.classList.add("from-center");
  }
}

function bindSlider(id, onChange) {
  const el = $(id);
  const send = throttle(onChange);
  el.addEventListener("input", () => {
    dragging.add(id);
    $(`${id}-value`).textContent = fmt(id, el.value);
    paintFill(id);
    send(Number(el.value));
  });
  const release = () => {
    // Hold the lock briefly so the trailing echo doesn't yank the thumb back.
    setTimeout(() => dragging.delete(id), 400);
  };
  el.addEventListener("change", release);
  el.addEventListener("pointerup", release);
  el.addEventListener("pointercancel", release);
}

function applyRange(id, control) {
  const el = $(id);
  el.min = control.min_value;
  el.max = control.max_value;
  el.step = control.step;
  ranges[id] = control;
  if (BIPOLAR.has(id)) {
    if ($(`${id}-min`)) $(`${id}-min`).textContent = fmt(id, control.min_value);
    if ($(`${id}-max`)) $(`${id}-max`).textContent = fmt(id, control.max_value);
  }
  if (!dragging.has(id)) {
    el.value = control.value;
    $(`${id}-value`).textContent = fmt(id, control.value);
    paintFill(id);
  }
}

// The name is inline-editable; suppress live overwrites from state/SSE while editing.
let editingName = false;

function renderName(info) {
  const el = $("device-name");
  if (!el || editingName || !info?.name) return;
  el.textContent = info.name;
  document.title = info.name;
}

function setupRename() {
  const el = $("device-name");
  if (!el) return;

  const begin = () => {
    if (editingName) return;
    editingName = true;
    const original = el.textContent;
    el.contentEditable = "plaintext-only";
    el.classList.add("editing");
    el.focus();
    getSelection().selectAllChildren(el);

    const finish = async (save) => {
      el.removeEventListener("keydown", onKey);
      el.removeEventListener("blur", onBlur);
      el.contentEditable = "false";
      el.classList.remove("editing");
      const name = el.textContent.trim().replace(/\s+/g, " ");
      editingName = false;
      if (save && name && name !== original) {
        const res = await post("/api/name", { name });
        if (res?.name) {
          el.textContent = res.name;
          document.title = res.name;
        } else {
          el.textContent = original; // request failed; setStatus already showed why
        }
      } else {
        el.textContent = original;
      }
    };
    const onKey = (e) => {
      if (e.key === "Enter") { e.preventDefault(); el.blur(); }
      else if (e.key === "Escape") { e.preventDefault(); finish(false); }
    };
    const onBlur = () => finish(true);
    el.addEventListener("keydown", onKey);
    el.addEventListener("blur", onBlur);
  };

  el.addEventListener("click", begin);
  el.addEventListener("keydown", (e) => {
    if (!editingName && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); begin(); }
  });
}

// Friendly source names; the device's raw account strings (e.g. AIRPLAY2DEFAULTUSERNAME)
// are meaningless to a human.
function sourceLabel(np) {
  if (np.is_standby) return "Off";
  if (np.is_invalid) return "Unavailable";
  const bySource = {
    AIRPLAY: "AirPlay",
    SPOTIFY: "Spotify",
    BLUETOOTH: "Bluetooth",
    TUNEIN: "TuneIn",
    PRODUCT: np.source_account === "TV" ? "TV" : (np.source_account || "").replace(/_/g, " "),
  };
  return bySource[np.source] || (np.source_account || np.source || "—").replace(/_/g, " ");
}

function renderPower(np) {
  const standby = np.is_standby;
  document.body.classList.toggle("standby", standby);
  $("power-state").textContent = standby ? "Standby" : "On";
  $("conn").classList.toggle("off", standby);
  $("power").classList.toggle("on", !standby);
}

function renderNowPlaying(np) {
  const isTv = np.is_tv || np.source === "PRODUCT";
  renderPower(np);

  let title;
  if (np.is_standby) title = "Standby";
  else if (np.is_invalid) title = "Unavailable";
  else if (isTv) title = np.track || "TV audio";
  else if (np.track) title = np.track;
  else if (np.station) title = np.station;
  // Paused/idle streaming has no track metadata. Fall back to the friendly source name
  // (e.g. "AirPlay"), never the raw account string (AirPlay2DefaultUserName).
  else title = np.is_playing ? sourceLabel(np) : `${sourceLabel(np)} · paused`;

  $("track").textContent = title;

  // INVALID_SOURCE means the speaker accepted the selection but could not resolve it
  // upstream -- always the Bose cloud shutdown. Say so rather than showing a dead card.
  $("artist").textContent = np.is_invalid
    ? "Bose's servers shut down, so this content can't be loaded"
    : np.artist || np.album || "";

  $("source-badge").textContent = sourceLabel(np);

  const art = $("art");
  const hasArt = Boolean(np.art_url) && !np.is_standby;
  // Large hero image only when there's real cover art; TV/standby fall back to the
  // compact side-by-side layout so there's no giant empty square.
  $("now-playing").classList.toggle("has-art", hasArt);
  if (hasArt) {
    art.innerHTML = `<img src="${np.art_url}" alt="Album art">`;
  } else {
    const glyph = np.is_standby ? "⏻" : np.is_invalid ? "⚠" : isTv ? "📺" : "♪";
    art.innerHTML = `<div class="art-fallback">${glyph}</div>`;
  }

  // Standby / unavailable: nothing to control, so hide transport entirely.
  // TV audio: something is playing but the speaker ignores transport keys — show dimmed.
  $("transport").hidden = np.is_standby || np.is_invalid;
  $("transport").classList.toggle("disabled", isTv);

  $("playpause-icon").innerHTML = np.is_playing
    ? '<path d="M7 4v16M17 4v16" />'
    : '<path d="M6 4l14 8-14 8z" />';
}

function renderVolume(vol) {
  if (!dragging.has("volume")) {
    $("volume").value = vol.actual;
    $("volume-value").textContent = vol.actual;
  }
  $("mute").classList.toggle("on", vol.muted);
  $("mute-icon").innerHTML = vol.muted
    ? '<path d="M11 5 6 9H3v6h3l5 4z" /><path d="M22 9l-6 6M16 9l6 6" />'
    : '<path d="M11 5 6 9H3v6h3l5 4z" /><path d="M16 9c1 1 1 5 0 6" />';
}

function renderDsp(dsp) {
  document.querySelectorAll("#dsp button").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.mode === dsp.audio_mode);
    // Hide modes this device doesn't advertise rather than offering a dead button.
    if (dsp.supported_modes?.length) {
      btn.hidden = !dsp.supported_modes.includes(btn.dataset.mode);
    }
  });
  // On non-TV sources the speaker sits in AUDIO_MODE_DIRECT, which it neither lists
  // nor accepts. Neither button is lit then, so explain why instead of looking broken.
  const applicable = dsp.is_applicable !== false;
  $("dsp").classList.toggle("inactive", !applicable);
  $("dsp-hint").textContent = applicable
    ? "Dialog lifts voices out of the mix for TV."
    : "Speech mode applies to TV audio; this source is passed through directly.";
}

const SPEAKER_LABELS = { rear: "Surrounds", subwoofer01: "Bass module", subwoofer02: "Bass module 2" };

function renderSpeakers(speakers) {
  $("speakers").innerHTML = speakers.items
    .map((s) => {
      const label = SPEAKER_LABELS[s.name] || s.name;
      // available=false means the accessory isn't paired at all -- nothing to toggle.
      const disabled = s.available ? "" : "disabled";
      const state = !s.available ? "Not paired" : s.active ? "On" : "Off";
      return `<button class="speaker ${s.active ? "active" : ""}" data-speaker="${s.name}"
        aria-pressed="${s.active}" ${disabled}>
        <span class="dot"></span>${label} · ${state}</button>`;
    })
    .join("");

  $("speakers").querySelectorAll("button[data-speaker]:not([disabled])").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const turnOn = btn.getAttribute("aria-pressed") !== "true";
      const res = await post("/api/speaker", { name: btn.dataset.speaker, active: turnOn });
      // Re-render from the authoritative response so the chip can't drift from the device.
      if (res?.items) renderSpeakers({ items: res.items.map((i) => ({ ...i, available: true })) });
    });
  });
}

function renderSources(sources, nowPlaying) {
  const labels = { "PRODUCT/TV": "TV", "PRODUCT/HDMI_1": "HDMI 1", BLUETOOTH: "Bluetooth" };
  const currentKey = nowPlaying.source_account
    ? `${nowPlaying.source}/${nowPlaying.source_account}`
    : nowPlaying.source;

  $("sources").innerHTML = sources.selectable
    .map((s) => {
      const active = s.key === currentKey ? "active" : "";
      return `<button class="${active}" data-source="${s.source}" data-account="${s.source_account}">
        ${labels[s.key] || s.display_name || s.source}</button>`;
    })
    .join("");

  $("sources").querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", () =>
      post("/api/source", { source: btn.dataset.source, sourceAccount: btn.dataset.account })
    );
  });
}

let lastState = null;

// Run each section independently so one bad render can't blank the whole page.
function safe(label, fn) {
  try {
    fn();
  } catch (err) {
    console.error(`render ${label} failed:`, err);
  }
}

function render(state) {
  lastState = state;
  safe("name", () => renderName(state.info));
  safe("now_playing", () => renderNowPlaying(state.now_playing));
  safe("volume", () => renderVolume(state.volume));
  safe("dsp", () => renderDsp(state.dsp));
  safe("speakers", () => renderSpeakers(state.speakers));
  safe("sources", () => renderSources(state.sources, state.now_playing));
  safe("tone", () => {
    applyRange("bass", state.tone.bass);
    applyRange("treble", state.tone.treble);
  });
  safe("levels", () => {
    applyRange("center", state.levels.center);
    applyRange("surround", state.levels.surround);
  });
}

async function refresh() {
  try {
    const res = await fetch(api("/api/state"));
    if (!res.ok) throw new Error("could not reach the speaker");
    render(await res.json());
    setStatus("");
  } catch (err) {
    setStatus(err.message, true);
  }
}

function connectEvents() {
  const source = new EventSource(api("/api/events"));

  source.addEventListener("open", () => $("conn").classList.add("live"));
  source.addEventListener("error", () => $("conn").classList.remove("live"));

  source.addEventListener("volume", (e) => renderVolume(JSON.parse(e.data)));
  source.addEventListener("now_playing", (e) => {
    const np = JSON.parse(e.data);
    renderNowPlaying(np);
    if (lastState) renderSources(lastState.sources, np);
  });
  source.addEventListener("dsp", (e) => renderDsp(JSON.parse(e.data)));
  source.addEventListener("tone", (e) => {
    const tone = JSON.parse(e.data);
    applyRange("bass", tone.bass);
    applyRange("treble", tone.treble);
  });
  source.addEventListener("levels", (e) => {
    const levels = JSON.parse(e.data);
    applyRange("center", levels.center);
    applyRange("surround", levels.surround);
  });
  // The device pushes plenty we don't model; re-read rather than drift.
  source.addEventListener("refresh", refresh);
}

const SUN = '<circle cx="12" cy="12" r="5" /><path d="M12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4" />';
const MOON = '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />';

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  // Show the icon of the theme you'd switch TO.
  $("theme-icon").innerHTML = theme === "light" ? MOON : SUN;
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", theme === "light" ? "#eff1f5" : "#181825");
}

function setupTheme() {
  const stored = localStorage.getItem("theme");
  const initial =
    stored || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
  applyTheme(initial);
  $("theme-toggle").addEventListener("click", () => {
    const next = document.documentElement.getAttribute("data-theme") === "light" ? "dark" : "light";
    localStorage.setItem("theme", next);
    applyTheme(next);
  });
}

function setupAbout() {
  const modal = $("about-modal");
  const body = $("about-body");
  if (!modal) return;
  let loaded = false;

  const open = async () => {
    if (!loaded) {
      try {
        const about = await (await fetch(api("/api/about"))).json();
        body.innerHTML = about.release_notes
          .map(
            (r) => `
            <div class="release">
              <div class="release-head">
                <span class="release-version">v${r.version}</span>
                ${r.title ? `<span class="release-title">${r.title}</span>` : ""}
                <span class="release-date">${r.date || ""}</span>
              </div>
              <ul>${r.notes.map((n) => `<li>${n}</li>`).join("")}</ul>
            </div>`
          )
          .join("");
        loaded = true;
      } catch {
        body.textContent = "Could not load release notes.";
      }
    }
    modal.hidden = false;
  };
  const close = () => {
    modal.hidden = true;
  };

  $("about-btn").addEventListener("click", open);
  $("about-close").addEventListener("click", close);
  modal.addEventListener("click", (e) => {
    if (e.target === modal) close(); // click the backdrop
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !modal.hidden) close();
  });
}

function init() {
  setupTheme();
  setupAbout();
  bindSlider("volume", (value) => post("/api/volume", { value }));
  bindSlider("bass", (bass) => post("/api/tone", { bass }));
  bindSlider("treble", (treble) => post("/api/tone", { treble }));
  bindSlider("center", (center) => post("/api/levels", { center }));
  bindSlider("surround", (surround) => post("/api/levels", { surround }));

  $("mute").addEventListener("click", () => post("/api/key", { value: "MUTE" }));
  $("power").addEventListener("click", () => post("/api/key", { value: "POWER" }));

  document.querySelectorAll("#transport button").forEach((btn) => {
    btn.addEventListener("click", () => post("/api/key", { value: btn.dataset.key }));
  });
  document.querySelectorAll("#dsp button").forEach((btn) => {
    btn.addEventListener("click", () => post("/api/dsp", { audiomode: btn.dataset.mode }));
  });

  setupRename();
  refresh();
  connectEvents();

  // Poll as a backstop to the live feed: several apps (AirPlay, Spotify Connect, the
  // remote) can drive this speaker, and not every change arrives as a push. Skip a tick
  // while a slider is held or the tab is hidden so it never fights the user or wastes
  // requests in the background.
  setInterval(() => {
    if (document.hidden || dragging.size) return;
    refresh();
  }, 10000);

  // A phone that sleeps loses the SSE stream; resync whatever we missed on return.
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refresh();
  });
}

// Deferred to the load event: an EventSource opened during parsing counts as a
// pending resource, which leaves the tab's loading spinner running indefinitely.
if (document.readyState === "complete") {
  init();
} else {
  window.addEventListener("load", init);
}
