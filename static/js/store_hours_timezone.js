document.addEventListener("DOMContentLoaded", function () {
  console.log("===== STORE HOURS INIT =====");

  const fields = document.querySelectorAll(
    ".operating-hours-field"
  );

  console.log("Fields found:", fields.length);

  // UTC -> Local display
  fields.forEach(field => {
    if (!field.value) {
      console.log(`[${field.name}] Empty value, skipping`);
      return;
    }

    console.log(
      `[${field.name}] Original DB value (UTC):`,
      field.value
    );

    const parts = field.value.split(":");

    if (parts.length < 2) {
      console.warn(
        `[${field.name}] Invalid time format:`,
        field.value
      );
      return;
    }

    const utcDate = new Date();

    utcDate.setUTCHours(
      parseInt(parts[0], 10),
      parseInt(parts[1], 10),
      0,
      0
    );

    console.log(
      `[${field.name}] UTC Date Object:`,
      utcDate.toISOString()
    );

    const localTime = utcDate.toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      hour12: true
    });

    console.log(
      `[${field.name}] Converted to Browser Local Time:`,
      localTime
    );

    field.value = localTime;
  });

  const form = document.querySelector("form");

  if (!form) {
    console.warn("No form found");
    return;
  }

  form.addEventListener("submit", function () {
    fields.forEach(field => {
      if (!field.value) return;

      // Parse "09:30 AM" or "09:30" manually
      const match = field.value.match(/^(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(AM|PM)?$/i);

      if (!match) {
        console.error(`[${field.name}] Could not parse time:`, field.value);
        return;
      }

      let hours   = parseInt(match[1], 10);
      const mins  = parseInt(match[2], 10);
      const ampm  = match[4];

      if (ampm) {
        const isPM = ampm.toUpperCase() === "PM";
        if (isPM && hours !== 12) hours += 12;
        if (!isPM && hours === 12) hours = 0;   // midnight edge case
      }

      // Use local setters — JS will internally track this as local time
      const localDate = new Date(1970, 0, 1, hours, mins, 0, 0);

      const utcHours   = String(localDate.getUTCHours()).padStart(2, "0");
      const utcMinutes = String(localDate.getUTCMinutes()).padStart(2, "0");

      field.value = `${utcHours}:${utcMinutes}:00`;

      console.log(`[${field.name}] Local "${field.value}" → UTC "${field.value}"`);
    });
  });

  console.log(
    "Browser timezone:",
    Intl.DateTimeFormat().resolvedOptions().timeZone
  );

  console.log(
    "Timezone offset (minutes):",
    new Date().getTimezoneOffset()
  );

  console.log("===== STORE HOURS READY =====");
});