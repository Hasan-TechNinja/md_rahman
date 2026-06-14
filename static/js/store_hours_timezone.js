document.addEventListener("DOMContentLoaded", function () {
  const fields = document.querySelectorAll(
    ".operating-hours-field"
  );

  // UTC -> Local display
  fields.forEach(field => {
    if (!field.value) return;

    const parts = field.value.split(":");

    if (parts.length < 2) return;

    const utcDate = new Date();
    utcDate.setUTCHours(
      parseInt(parts[0], 10),
      parseInt(parts[1], 10),
      0,
      0
    );

    field.value = utcDate.toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      hour12: true
    });
  });

  // Local -> UTC before save
  const form = document.querySelector("form");

  if (!form) return;

  form.addEventListener("submit", function () {
    fields.forEach(field => {
      if (!field.value) return;

      const localDate = new Date(
        `1970-01-01 ${field.value}`
      );

      if (isNaN(localDate)) return;

      const hours = String(
        localDate.getUTCHours()
      ).padStart(2, "0");

      const minutes = String(
        localDate.getUTCMinutes()
      ).padStart(2, "0");

      field.value = `${hours}:${minutes}:00`;
    });
  });
});