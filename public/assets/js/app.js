// Moto Bhai India — v1 main controller. Pure vanilla, no framework.
import { api } from "/assets/js/api.js";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const els = {
  form: $("#plan-form"),
  from: $("#from"),
  to: $("#to"),
  days: $("#days"),
  daysOut: $(".slider-out"),
  daysHint: $("#days-hint"),
  bikeTrack: $("#bike-track"),
  bikeOther: $("#bike-other"),
  bikeId: $("#bike_id"),
  bikeCustom: $("#bike_custom"),
  vibe: $$("input[name='vibe']"),
  cta: $("#cta"),
  err: $("#form-error"),
  itinerary: $("#itinerary"),
  itinTitle: $("#itinerary-title"),
  itinKm: $("#itinerary-km"),
  itinDays: $("#itinerary-days"),
  itinFuel: $("#itinerary-fuel"),
  daySwiper: $("#day-swiper"),
  btnPdf: $("#btn-pdf"),
  btnShare: $("#btn-share"),
  shareToast: $("#share-toast"),
  kmRing: $("#km-ring"),
  kmAvg: $("#km-avg"),
  kmFill: $(".km-ring__fill"),
};

const state = {
  bikes: [],
  selectedBikeId: null,
  estimatedKm: null,
  lastTrip: null,
};

// ─── Bike loading ────────────────────────────────────────────────────────
async function loadBikes() {
  try {
    const { motorcycles } = await api.motorcycles();
    state.bikes = motorcycles || [];
    // Sort: by touring_score desc, then by make
    state.bikes.sort((a, b) =>
      (b.touring_score ?? 0) - (a.touring_score ?? 0) ||
      a.make.localeCompare(b.make)
    );
    renderBikes();
    // Auto-select highest-scored as a sane default
    if (state.bikes.length) selectBike(state.bikes[0].bike_id);
  } catch (e) {
    console.warn("Bike load failed:", e);
    els.bikeTrack.innerHTML = `<p style="color:var(--text-2);padding:12px">Couldn't load bikes — pick "Other" and type yours.</p>`;
  }
}

function renderBikes() {
  els.bikeTrack.innerHTML = "";
  for (const b of state.bikes) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "bike-card";
    btn.dataset.value = b.bike_id;
    btn.setAttribute("role", "radio");
    btn.setAttribute("aria-checked", "false");
    btn.innerHTML = `
      <span class="bike-card__make">${escape(b.make)}</span>
      <span class="bike-card__model">${escape(b.model)}</span>
      <span class="bike-card__meta">${b.engine_cc}cc · ${b.mileage_kmpl} kmpl</span>
    `;
    btn.addEventListener("click", () => selectBike(b.bike_id));
    els.bikeTrack.appendChild(btn);
  }
}

function selectBike(id) {
  state.selectedBikeId = id;
  els.bikeId.value = id === "__other" ? "" : id;
  $$(".bike-card", els.bikeTrack).forEach((el) => {
    const on = el.dataset.value === id;
    el.classList.toggle("is-selected", on);
    el.setAttribute("aria-checked", on ? "true" : "false");
  });
  els.bikeOther.classList.toggle("is-selected", id === "__other");
  els.bikeCustom.hidden = id !== "__other";
  if (id === "__other") setTimeout(() => els.bikeCustom.focus(), 50);
}

els.bikeOther.addEventListener("click", () => selectBike("__other"));

// ─── Days slider + km-ring feedback ──────────────────────────────────────
function updateDays() {
  const d = parseInt(els.days.value, 10);
  els.daysOut.textContent = d;
  els.daysHint.textContent = `${d} day${d === 1 ? "" : "s"}`;
  recomputeRing();
}
els.days.addEventListener("input", updateDays);

function recomputeRing() {
  if (!state.estimatedKm) {
    els.kmRing.hidden = true;
    return;
  }
  const days = parseInt(els.days.value, 10);
  const perDay = Math.round(state.estimatedKm / days);
  els.kmRing.hidden = false;
  els.kmAvg.textContent = perDay;
  const pct = Math.min(100, (perDay / 350) * 100);
  els.kmFill.style.setProperty("--p", pct.toFixed(0));
  els.kmRing.classList.toggle("km-ring--over", perDay > 350);
}

// ─── Form submission ─────────────────────────────────────────────────────
els.form.addEventListener("submit", async (e) => {
  e.preventDefault();
  els.err.hidden = true;

  const payload = {
    from: els.from.value.trim(),
    to: els.to.value.trim(),
    days: parseInt(els.days.value, 10),
    bike_id: state.selectedBikeId === "__other" ? null : els.bikeId.value || null,
    bike_custom: state.selectedBikeId === "__other" ? els.bikeCustom.value.trim() : null,
    vibe: (els.vibe.find((r) => r.checked) || {}).value || "standard",
    budget_tier: "standard",
    loop: false,
  };

  if (!payload.from || !payload.to) {
    return showError("Please fill both From and To.");
  }
  if (!payload.bike_id && !payload.bike_custom) {
    return showError("Pick a bike or type your own.");
  }

  setLoading(true);
  api.log("plan_submitted", { from: payload.from, to: payload.to, days: payload.days });

  try {
    const trip = await api.plan(payload);
    state.lastTrip = trip;
    renderItinerary(trip);
    // Persist last trip locally for "My Rides" + offline
    try { localStorage.setItem("mb_last_trip", JSON.stringify(trip)); } catch {}
    api.log("plan_succeeded", { trip_id: trip.trip_id });
  } catch (err) {
    console.error(err);
    if (err.status === 422 && err.data?.detail?.suggested_days) {
      const sug = err.data.detail.suggested_days;
      showError(`Too long for ${payload.days} days. Try ${sug} days instead.`);
      els.days.value = sug;
      updateDays();
    } else {
      showError(err.message || "Something broke. Try again.");
    }
    api.log("plan_failed", { error: String(err.message), status: err.status });
  } finally {
    setLoading(false);
  }
});

function setLoading(on) {
  els.cta.disabled = on;
  els.cta.classList.toggle("is-loading", on);
  els.cta.querySelector(".cta__text").textContent = on ? "Planning…" : "Plan My Ride";
}

function showError(msg) {
  els.err.textContent = msg;
  els.err.hidden = false;
  els.err.scrollIntoView({ behavior: "smooth", block: "center" });
}

// ─── Itinerary render ────────────────────────────────────────────────────
function renderItinerary(trip) {
  els.form.hidden = true;
  els.itinerary.hidden = false;
  els.itinerary.scrollIntoView({ behavior: "smooth", block: "start" });

  const s = trip.summary || {};
  els.itinTitle.textContent = `${s.from} → ${s.to}`;
  els.itinKm.textContent = `${Math.round(s.total_km || 0)} km`;
  els.itinDays.textContent = `${s.total_days || trip.days_plan?.length || "—"} days`;
  els.itinFuel.textContent = s.est_fuel_cost_inr ? `₹${s.est_fuel_cost_inr.toLocaleString("en-IN")} fuel` : "";

  els.daySwiper.innerHTML = "";
  for (const day of trip.days_plan || []) {
    els.daySwiper.appendChild(renderDayCard(day));
  }
}

function renderDayCard(day) {
  const card = document.createElement("article");
  card.className = "day-card";
  card.setAttribute("role", "listitem");
  card.innerHTML = `
    <div class="day-card__day">Day ${day.day}</div>
    <div class="day-card__route">${escape(day.from)} → ${escape(day.to)}</div>
    <div class="day-card__map">Route map · ${Math.round(day.km)} km</div>
    <div class="day-card__stat">
      <span><strong>${Math.round(day.km)}</strong> km</span>
      <span><strong>${day.eta_hours ?? "—"}</strong> hrs</span>
      <span><strong>${day.fuel_stops?.length ?? 0}</strong> fuel stops</span>
    </div>
    ${day.hotel_suggestion ? `
      <div class="day-card__hotel">
        <div class="day-card__hotel-name">${escape(day.hotel_suggestion.name)}</div>
        <div style="color:var(--text-2);font-size:13px">${escape(day.hotel_suggestion.area || "")} · ${escape(day.hotel_suggestion.price_range_inr || "")}</div>
      </div>` : ""}
    ${day.bhai_tip ? `<div class="day-card__tip">${escape(day.bhai_tip)}</div>` : ""}
  `;
  return card;
}

els.btnPdf.addEventListener("click", async () => {
  if (!state.lastTrip) return;
  // PDF endpoint comes in PR #3. For now redirect to legacy until then.
  alert("PDF download coming back in the next update — your trip is saved.");
});

els.btnShare.addEventListener("click", async () => {
  if (!state.lastTrip?.share_url) return;
  const url = state.lastTrip.share_url;
  try {
    if (navigator.share) {
      await navigator.share({ title: "My Moto Bhai ride", url });
    } else {
      await navigator.clipboard.writeText(url);
      els.shareToast.hidden = false;
      setTimeout(() => (els.shareToast.hidden = true), 2400);
    }
    api.log("share_link_used", { trip_id: state.lastTrip.trip_id });
  } catch {}
});

// ─── Utils ───────────────────────────────────────────────────────────────
function escape(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ─── Boot ────────────────────────────────────────────────────────────────
updateDays();
loadBikes();

// PWA registration (manifest only for now — service worker comes in Phase 2 week 2)
if ("serviceWorker" in navigator && location.protocol === "https:") {
  // Stub: SW shipping in a follow-up PR
}
