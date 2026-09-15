/** Base HTTP client (fetch wrapper) for the PFIM frontend. */
const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";
const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

interface CapabilityBootstrap {
  token: string;
  header_name: string;
}

interface ApiErrorBody {
  error_code?: string;
  message?: string;
  detail?: unknown;
}

export class ApiError extends Error {
  readonly status: number;
  readonly errorCode: string | null;
  readonly detail: unknown;

  constructor(message: string, status: number, errorCode: string | null, detail: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.errorCode = errorCode;
    this.detail = detail;
  }
}

export class ApiNetworkError extends Error {
  readonly requestSent: boolean;
  readonly originalError: unknown;

  constructor(message: string, requestSent: boolean, originalError: unknown) {
    super(message);
    this.name = "ApiNetworkError";
    this.requestSent = requestSent;
    this.originalError = originalError;
  }
}

let capabilityPromise: Promise<CapabilityBootstrap> | null = null;

function loadCapability(): Promise<CapabilityBootstrap> {
  if (!capabilityPromise) {
    capabilityPromise = fetch(`${BASE_URL}/security/capability`, {
      cache: "no-store",
    }).then(async (res) => {
      if (!res.ok) {
        throw new ApiNetworkError(
          "Unable to initialise operation protection",
          false,
          null
        );
      }
      return res.json() as Promise<CapabilityBootstrap>;
    }).catch((error: unknown) => {
      capabilityPromise = null;
      if (error instanceof ApiNetworkError) throw error;
      throw new ApiNetworkError(
        "Unable to contact the backend before the operation",
        false,
        error
      );
    });
  }
  return capabilityPromise;
}

async function isCapabilityRejection(res: Response): Promise<boolean> {
  if (res.status !== 403) return false;
  try {
    const body = (await res.clone().json()) as { error_code?: string };
    return body.error_code === "CAPABILITY_REQUIRED" || body.error_code === "CAPABILITY_INVALID";
  } catch {
    return false;
  }
}

async function protectedFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const method = (init.method ?? "GET").toUpperCase();
  if (!UNSAFE_METHODS.has(method)) {
    try {
      return await fetch(url, init);
    } catch (error) {
      throw new ApiNetworkError("Unable to contact the backend", false, error);
    }
  }

  async function send(bootstrap: CapabilityBootstrap): Promise<Response> {
    const headers = new Headers(init.headers);
    headers.set(bootstrap.header_name, bootstrap.token);
    try {
      return await fetch(url, { ...init, headers });
    } catch (error) {
      throw new ApiNetworkError(
        "Connection interrupted after sending the operation",
        true,
        error
      );
    }
  }

  let response = await send(await loadCapability());
  if (await isCapabilityRejection(response)) {
    // Middleware rejects these requests before invoking the handler; only these
    // two codes can be retried safely without duplicating a successful mutation.
    capabilityPromise = null;
    response = await send(await loadCapability());
  }
  return response;
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let message = `API error ${res.status}`;
    let errorCode: string | null = null;
    let detail: unknown = null;
    try {
      const body = (await res.json()) as ApiErrorBody;
      if (body?.message) message = body.message;
      if (body?.error_code) errorCode = body.error_code;
      detail = body?.detail ?? null;
    } catch {
      // Keep the generic message for a non-JSON response body.
    }
    throw new ApiError(message, res.status, errorCode, detail);
  }
  if (res.status === 204) {
    return undefined as T;
  }
  return res.json() as Promise<T>;
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body !== undefined && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await protectedFetch(`${BASE_URL}${path}`, { ...init, headers });
  return handleResponse<T>(res);
}

/** Upload multipart/form-data (CSV imports, etc.). Let the browser set
 * Content-Type with the correct FormData boundary; setting it manually
 * as apiFetch does for JSON would break the upload. */
export async function apiFetchFormData<T>(path: string, formData: FormData, method = "POST"): Promise<T> {
  const res = await protectedFetch(`${BASE_URL}${path}`, { method, body: formData });
  return handleResponse<T>(res);
}

/** Download a binary file (e.g. CSV export or backup) as a Blob. */
export async function apiFetchBlob(path: string): Promise<Blob> {
  const res = await fetch(`${BASE_URL}${path}`);
  if (!res.ok) throw new Error(`API error ${res.status}`);
  return res.blob();
}

/** Download a file and save it with the specified name.
 * Using a Blob instead of opening the URL in a tab turns server errors
 * into catchable exceptions, rather than blank pages or error text files. */
export async function downloadFile(path: string, filename: string): Promise<void> {
  const blob = await apiFetchBlob(path);
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
