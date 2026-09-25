// Money arrives from the API as integer paise. It is only turned into rupees here, for display.
export function formatINR(paise) {
  const sign = paise < 0 ? "-" : "";
  const abs = Math.abs(paise);
  const rupees = Math.floor(abs / 100);
  const rem = abs % 100;
  const grouped = rupees.toLocaleString("en-IN");
  return `${sign}\u20b9${grouped}${rem ? "." + String(rem).padStart(2, "0") : ""}`;
}

export function formatDate(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-GB", {
    day: "numeric", month: "short", year: "numeric", timeZone: "UTC",
  });
}

export const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
