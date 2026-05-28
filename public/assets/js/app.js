// Moto Bhai India — v1 main controller. Pure vanilla, no framework.
import { api } from "/assets/js/api.js";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const RIDES_KEY = "mb_rides_v1";
const RIDES_MAX = 10;

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
  openMyRides: $("#open-my-rides"),
  ridesDrawer: $("#my-rides-drawer"),
  ridesList: $("#rides-list"),
  ridesSub: $("#my-rides-sub"),
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
    // Persist for "My Rides" + offline. Keep last 10 trips by trip_id.
    try {
      localStorage.setItem("mb_last_trip", JSON.stringify(trip));
      saveToRides(trip);
    } catch {}
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

// ─── My Rides ────────────────────────────────────────────────────────────
function loadRides() {
  try { return JSON.parse(localStorage.getItem(RIDES_KEY) || "[]"); } catch { return []; }
}

function saveToRides(trip) {
  if (!trip?.trip_id) return;
  const compact = {
    trip_id: trip.trip_id,
    share_url: trip.share_url,
    created_at: trip.created_at || new Date().toISOString(),
    summary: {
      from: trip.summary?.from,
      to: trip.summary?.to,
      total_km: trip.summary?.total_km,
      total_days: trip.summary?.total_days,
      max_day_km: trip.summary?.max_day_km,
      est_fuel_cost_inr: trip.summary?.est_fuel_cost_inr,
    },
  };
  const existing = loadRides().filter((r) => r.trip_id !== trip.trip_id);
  const next = [compact, ...existing].slice(0, RIDES_MAX);
  localStorage.setItem(RIDES_KEY, JSON.stringify(next));
}

function formatWhen(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return "";
  const diffMin = Math.round((Date.now() - d) / 60000);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin} min ago`;
  const hr = Math.round(diffMin / 60);
  if (hr < 24) return `${hr} hr ago`;
  const days = Math.round(hr / 24);
  if (days < 7) return `${days} day${days === 1 ? "" : "s"} ago`;
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

function renderRidesList() {
  const rides = loadRides();
  els.ridesSub.textContent = rides.length
    ? `${rides.length} ride${rides.length === 1 ? "" : "s"} saved on this device`
    : "No rides saved yet";
  els.ridesList.innerHTML = "";
  if (!rides.length) {
    const empty = document.createElement("li");
    empty.className = "rides-empty";
    empty.textContent = "Plan a ride and it'll show up here.";
    els.ridesList.appendChild(empty);
    return;
  }
  for (const r of rides) {
    const li = document.createElement("li");
    const a = document.createElement("a");
    a.className = "ride-row";
    a.href = r.share_url || "#";
    a.target = "_blank";
    a.rel = "noopener";
    const s = r.summary || {};
    a.innerHTML = `
      <div class="ride-row__route">${escape(s.from || "?")} → ${escape(s.to || "?")}</div>
      <div class="ride-row__meta">${s.total_days || "—"} days · ${Math.round(s.total_km || 0)} km${s.est_fuel_cost_inr ? " · ₹" + s.est_fuel_cost_inr.toLocaleString("en-IN") + " fuel" : ""}</div>
      <div class="ride-row__when">${formatWhen(r.created_at)}</div>
    `;
    li.appendChild(a);
    els.ridesList.appendChild(li);
  }
}

function openDrawer() {
  renderRidesList();
  els.ridesDrawer.hidden = false;
  document.body.style.overflow = "hidden";
  document.addEventListener("keydown", drawerKeyHandler);
}
function closeDrawer() {
  els.ridesDrawer.hidden = true;
  document.body.style.overflow = "";
  document.removeEventListener("keydown", drawerKeyHandler);
}
function drawerKeyHandler(e) { if (e.key === "Escape") closeDrawer(); }

els.openMyRides?.addEventListener("click", openDrawer);
els.ridesDrawer?.addEventListener("click", (e) => {
  if (e.target.dataset.dismiss !== undefined) closeDrawer();
});

// ─── Boot ────────────────────────────────────────────────────────────────
updateDays();
loadBikes();

// PWA registration (manifest only for now — service worker comes in Phase 2 week 2)
if ("serviceWorker" in navigator && location.protocol === "https:") {
  // Stub: SW shipping in a follow-up PR
}
