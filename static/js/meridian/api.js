/* Typed Meridian API access: JSON-only responses, normalized stable errors,
   caller-controlled aborts. Mutations are never sent or retried here. */

export class MeridianApiError extends Error {
  constructor({ code, message, recoveryAction, status }) {
    super(message || "The request could not be completed.");
    this.name = "MeridianApiError";
    this.code = code || "unexpected_error";
    this.recoveryAction = recoveryAction || "Try again shortly.";
    this.status = status;
  }
}

export async function meridianFetch(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  if (method !== "GET") {
    throw new MeridianApiError({
      code: "mutations_forbidden",
      message: "Meridian views never send mutations.",
      recoveryAction: "Use an approved proposal instead.",
      status: 0,
    });
  }

  let response;
  try {
    response = await fetch(path, {
      ...options,
      method: "GET",
      headers: { Accept: "application/json", ...(options.headers || {}) },
    });
  } catch (error) {
    if (error && error.name === "AbortError") {
      throw error;
    }
    throw new MeridianApiError({
      code: "network_unreachable",
      message: "Meridian could not reach the server.",
      recoveryAction: "Check your connection and try again.",
      status: 0,
    });
  }

  return _parse(response);
}

const ALLOWED_PROPOSAL_PATHS = new Set(["/api/meridian/funding-rules/propose"]);

export async function meridianPropose(path, payload) {
  /* The only write channel in the browser: it creates a pending proposal
     for owner approval. It never executes anything and never touches Crew. */
  if (!ALLOWED_PROPOSAL_PATHS.has(path)) {
    throw new MeridianApiError({
      code: "mutations_forbidden",
      message: "This endpoint is not a proposal endpoint.",
      recoveryAction: "Only approval-gated proposal endpoints accept writes.",
      status: 0,
    });
  }

  let response;
  try {
    response = await fetch(path, {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (error) {
    if (error && error.name === "AbortError") {
      throw error;
    }
    throw new MeridianApiError({
      code: "network_unreachable",
      message: "Meridian could not reach the server.",
      recoveryAction: "Check your connection and try again.",
      status: 0,
    });
  }

  return _parse(response);
}

async function _parse(response) {
  const contentType = response.headers.get("content-type") || "";
  let payload = null;
  if (contentType.includes("application/json")) {
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
  }

  if (!response.ok) {
    const detail = payload && payload.error ? payload.error : {};
    throw new MeridianApiError({
      code: detail.code,
      message: detail.message,
      recoveryAction: detail.recovery_action,
      status: response.status,
    });
  }

  if (payload === null) {
    throw new MeridianApiError({
      code: "invalid_response",
      message: "The server returned an unexpected response.",
      recoveryAction: "Reload the workspace.",
      status: response.status,
    });
  }

  return payload;
}

export function freshnessText(freshness) {
  if (!freshness) {
    return { state: "unavailable", label: "Freshness unknown" };
  }
  const state = freshness.status || "unavailable";
  if (state === "fresh") {
    return { state, label: `Updated ${formatTimestamp(freshness.last_updated_at)}` };
  }
  if (state === "stale") {
    const asOf = freshness.last_updated_at
      ? ` · updated ${formatTimestamp(freshness.last_updated_at)}`
      : "";
    return { state, label: `Stale${asOf}` };
  }
  return { state, label: "Not connected yet" };
}

export function formatTimestamp(value) {
  if (!value) {
    return "";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "";
  }
  return parsed.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}
