// store_hours_timezone.js
document.addEventListener("DOMContentLoaded", function () {
  console.log("===== STORE HOURS INIT =====");

  const fields = document.querySelectorAll(".operating-hours-field");
  console.log("Fields found:", fields.length);

  function to12h(hhmm) {
    if (!hhmm) return "Select time";

    let [h, m] = hhmm.split(":").map(Number);

    const ampm = h >= 12 ? "PM" : "AM";
    h = h % 12 || 12;

    return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")} ${ampm}`;
  }

  fields.forEach((field) => {
    // Hide original input
    field.style.display = "none";

    // Wrapper
    const wrapper = document.createElement("div");
    wrapper.className = "oh-picker-wrapper";
    wrapper.style.cssText =
      "position:relative; display:inline-block; width:100%;";

    // Display button
    const display = document.createElement("button");
    display.type = "button";
    display.className =
      "oh-display w-full p-2 rounded border border-gray-300 text-left bg-white cursor-pointer";
    display.style.cssText = "min-width:130px;";
    display.textContent = field.value
      ? to12h(field.value)
      : "Select time";

    // Dropdown
    const dropdown = document.createElement("div");
    dropdown.className = "oh-dropdown";
    dropdown.style.cssText = `
      display:none;
      position:absolute;
      z-index:9999;
      background:white;
      border:1px solid #d1d5db;
      border-radius:8px;
      padding:12px;
      box-shadow:0 4px 16px rgba(0,0,0,0.13);
      min-width:240px;
      margin-top:4px;
    `;

    // Prevent clicks inside dropdown from closing it
    dropdown.addEventListener("click", (e) => {
      e.stopPropagation();
    });

    const row = document.createElement("div");
    row.style.cssText =
      "display:flex; align-items:center; gap:6px;";

    // Hours
    const hourSel = document.createElement("select");
    hourSel.style.cssText =
      "padding:4px 6px; border-radius:4px; border:1px solid #d1d5db;";

    for (let i = 1; i <= 12; i++) {
      const opt = document.createElement("option");
      opt.value = i;
      opt.textContent = String(i).padStart(2, "0");
      hourSel.appendChild(opt);
    }

    // Colon
    const colon = document.createElement("span");
    colon.textContent = ":";

    // Minutes (00-59)
    const minSel = document.createElement("select");
    minSel.style.cssText =
      "padding:4px 6px; border-radius:4px; border:1px solid #d1d5db;";

    for (let i = 0; i < 60; i++) {
      const opt = document.createElement("option");
      opt.value = i;
      opt.textContent = String(i).padStart(2, "0");
      minSel.appendChild(opt);
    }

    // AM/PM
    const ampmSel = document.createElement("select");
    ampmSel.style.cssText =
      "padding:4px 6px; border-radius:4px; border:1px solid #d1d5db;";

    ["AM", "PM"].forEach((v) => {
      const opt = document.createElement("option");
      opt.value = v;
      opt.textContent = v;
      ampmSel.appendChild(opt);
    });

    // Load existing DB value exactly
    if (field.value) {
      let [h, m] = field.value.split(":").map(Number);

      ampmSel.value = h >= 12 ? "PM" : "AM";

      h = h % 12 || 12;

      hourSel.value = String(h);
      minSel.value = String(m);
    }

    // Save button
    const okBtn = document.createElement("button");
    okBtn.type = "button";
    okBtn.textContent = "✓";
    okBtn.style.cssText = `
      padding:4px 10px;
      background:#2563eb;
      color:white;
      border:none;
      border-radius:4px;
      cursor:pointer;
      font-size:1rem;
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

    // Open / close picker
    display.addEventListener("click", (e) => {
      e.stopPropagation();

      document.querySelectorAll(".oh-dropdown").forEach((d) => {
        if (d !== dropdown) {
          d.style.display = "none";
        }
      });

      dropdown.style.display =
        dropdown.style.display === "block"
          ? "none"
          : "block";
    });

    // Save selected time
    okBtn.addEventListener("click", (e) => {
      e.stopPropagation();

      let h = parseInt(hourSel.value, 10);
      const m = parseInt(minSel.value, 10);

      if (ampmSel.value === "PM" && h !== 12) {
        h += 12;
      }

      if (ampmSel.value === "AM" && h === 12) {
        h = 0;
      }

      const hhmm =
        `${String(h).padStart(2, "0")}:` +
        `${String(m).padStart(2, "0")}`;

      // Save exactly as wall-clock time
      field.value = hhmm;

      // Update button text
      display.textContent = to12h(hhmm);

      // Close only when ✓ clicked
      dropdown.style.display = "none";

      console.log(`[${field.name}] Saved: ${hhmm}`);
    });
  });

  // Close only when clicking outside
  document.addEventListener("click", () => {
    document.querySelectorAll(".oh-dropdown").forEach((dropdown) => {
      dropdown.style.display = "none";
    });
  });

  console.log("===== STORE HOURS CUSTOM UI READY =====");
});