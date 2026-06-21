// store_hours_timezone.js
document.addEventListener("DOMContentLoaded", function () {
  console.log("===== STORE HOURS INIT =====");

  const fields = document.querySelectorAll(".operating-hours-field");
  console.log("Fields found:", fields.length);

  // ── helpers ──────────────────────────────────────────────────────────────
  function utcHHMM_to_localHHMM(utcHHMM) {
    const [h, m] = utcHHMM.split(":").map(Number);
    const d = new Date();
    d.setUTCHours(h, m, 0, 0);
    return (
      String(d.getHours()).padStart(2, "0") + ":" +
      String(d.getMinutes()).padStart(2, "0")
    );
  }

  function localHHMM_to_utcHHMMSS(localHHMM) {
    const [h, m] = localHHMM.split(":").map(Number);
    const d = new Date();
    d.setHours(h, m, 0, 0);           // local setters
    return (
      String(d.getUTCHours()).padStart(2, "0") + ":" +
      String(d.getUTCMinutes()).padStart(2, "0") + ":00"
    );
  }

  function to12h(hhmm) {
    let [h, m] = hhmm.split(":").map(Number);
    const ampm = h >= 12 ? "PM" : "AM";
    h = h % 12 || 12;
    return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")} ${ampm}`;
  }

  // ── For each field: hide it, build a clock-picker UI beside it ───────────
  fields.forEach(field => {
    // 1. Convert stored UTC value → local HH:MM for the hidden input
    if (field.value) {
      field.value = utcHHMM_to_localHHMM(field.value);
    }

    // 2. Hide the raw <input type="time"> — it stays in the DOM for submission
    field.style.display = "none";

    // 3. Build the visible clock-picker button + dropdown
    const wrapper = document.createElement("div");
    wrapper.className = "oh-picker-wrapper";
    wrapper.style.cssText = "position:relative; display:inline-block; width:100%;";

    const display = document.createElement("button");
    display.type = "button";
    display.className = "oh-display w-full p-2 rounded border border-gray-300 text-left bg-white cursor-pointer";
    display.style.cssText = "min-width:130px;";
    display.textContent = field.value ? to12h(field.value) : "Select time";

    const dropdown = document.createElement("div");
    dropdown.className = "oh-dropdown";
    dropdown.style.cssText = `
      display: none;
      position: absolute;
      z-index: 9999;
      background: white;
      border: 1px solid #d1d5db;
      border-radius: 8px;
      padding: 12px;
      box-shadow: 0 4px 16px rgba(0,0,0,0.13);
      min-width: 220px;
    `;

    // ── Clock picker innards: hour + minute + AM/PM ──
    const row = document.createElement("div");
    row.style.cssText = "display:flex; align-items:center; gap:6px;";

    // Hour select
    const hourSel = document.createElement("select");
    hourSel.style.cssText = "padding:4px 6px; border-radius:4px; border:1px solid #d1d5db; font-size:1rem;";
    for (let i = 1; i <= 12; i++) {
      const o = document.createElement("option");
      o.value = i;
      o.textContent = String(i).padStart(2, "0");
      hourSel.appendChild(o);
    }

    const colon = document.createElement("span");
    colon.textContent = ":";
    colon.style.fontWeight = "bold";

    // Minute select (00, 05, 10 ... 55)
    const minSel = document.createElement("select");
    minSel.style.cssText = "padding:4px 6px; border-radius:4px; border:1px solid #d1d5db; font-size:1rem;";
    for (let i = 0; i < 60; i += 5) {
      const o = document.createElement("option");
      o.value = i;
      o.textContent = String(i).padStart(2, "0");
      minSel.appendChild(o);
    }

    // AM/PM
    const ampmSel = document.createElement("select");
    ampmSel.style.cssText = "padding:4px 6px; border-radius:4px; border:1px solid #d1d5db; font-size:1rem;";
    ["AM", "PM"].forEach(v => {
      const o = document.createElement("option");
      o.value = v;
      o.textContent = v;
      ampmSel.appendChild(o);
    });

    // Pre-fill selects from current field value
    if (field.value) {
      let [h, m] = field.value.split(":").map(Number);
      ampmSel.value = h >= 12 ? "PM" : "AM";
      h = h % 12 || 12;
      hourSel.value = h;
      // Snap minute to nearest 5
      minSel.value = Math.round(m / 5) * 5 % 60;
    }

    // OK button
    const okBtn = document.createElement("button");
    okBtn.type = "button";
    okBtn.textContent = "✓";
    okBtn.style.cssText = `
      padding: 4px 10px;
      background: #2563eb;
      color: white;
      border: none;
      border-radius: 4px;
      cursor: pointer;
      font-size: 1rem;
    `;

    row.appendChild(hourSel);
    row.appendChild(colon);
    row.appendChild(minSel);
    row.appendChild(ampmSel);
    row.appendChild(okBtn);
    dropdown.appendChild(row);

    wrapper.appendChild(display);
    wrapper.appendChild(dropdown);
    field.parentNode.insertBefore(wrapper, field.nextSibling);

    // ── Events ──────────────────────────────────────────────────────────────
    display.addEventListener("click", (e) => {
      e.stopPropagation();
      // Close all other dropdowns
      document.querySelectorAll(".oh-dropdown").forEach(d => {
        if (d !== dropdown) d.style.display = "none";
      });
      dropdown.style.display = dropdown.style.display === "none" ? "block" : "none";
    });

    okBtn.addEventListener("click", () => {
      let h = parseInt(hourSel.value, 10);
      const m = parseInt(minSel.value, 10);
      const ap = ampmSel.value;

      if (ap === "PM" && h !== 12) h += 12;
      if (ap === "AM" && h === 12) h = 0;

      const localHHMM = `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
      field.value = localHHMM;                        // local HH:MM in hidden input
      display.textContent = to12h(localHHMM);         // 12h on button
      dropdown.style.display = "none";

      console.log(`[${field.name}] Picked local:`, localHHMM);
    });

    document.addEventListener("click", () => {
      dropdown.style.display = "none";
    });
  });

  // ── On submit: convert every field's local HH:MM → UTC HH:MM:SS ──────────
  const form = document.querySelector("form");
  if (!form) { console.warn("No form found"); return; }

  form.addEventListener("submit", function () {
    console.log("===== FORM SUBMIT =====");
    fields.forEach(field => {
      if (!field.value) return;
      const utc = localHHMM_to_utcHHMMSS(field.value);
      console.log(`[${field.name}] local ${field.value} → UTC ${utc}`);
      field.value = utc;
    });
  });

  console.log("TZ:", Intl.DateTimeFormat().resolvedOptions().timeZone);
  console.log("===== STORE HOURS READY =====");
});