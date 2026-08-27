/* Shared display formatting for Meridian workspaces. */

export function formatCurrency(amount, currency) {
  const code = currency || "USD";
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency: code,
    }).format(amount);
  } catch {
    return `${code} ${amount.toFixed(2)}`;
  }
}

export function dayKey(isoTimestamp) {
  const parsed = new Date(isoTimestamp);
  if (Number.isNaN(parsed.getTime())) {
    return "unknown";
  }
  const parts = [
    parsed.getFullYear(),
    String(parsed.getMonth() + 1).padStart(2, "0"),
    String(parsed.getDate()).padStart(2, "0"),
  ];
  return parts.join("-");
}

export function dayLabel(isoTimestamp) {
  const parsed = new Date(isoTimestamp);
  if (Number.isNaN(parsed.getTime())) {
    return "Unknown date";
  }
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startOfDay = new Date(parsed.getFullYear(), parsed.getMonth(), parsed.getDate());
  const dayMs = 24 * 60 * 60 * 1000;
  const diffDays = Math.round((startOfDay.getTime() - startOfToday.getTime()) / dayMs);
  if (diffDays === 0) {
    return "Today";
  }
  if (diffDays === -1) {
    return "Yesterday";
  }
  return parsed.toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
  });
}
