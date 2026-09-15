import { beforeEach, describe, expect, it, vi } from "vitest";

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
    ...init,
  });
}

describe("capability HTTP client", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.restoreAllMocks();
  });

  it("does not require a capability token for reads", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ status: "ok" }));
    vi.stubGlobal("fetch", fetchMock);
    const { apiFetch } = await import("./client");

    await expect(apiFetch<{ status: string }>("/health")).resolves.toEqual({ status: "ok" });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toContain("/health");
  });

  it("obtains a volatile token and sends it with a mutation", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({ token: "secret-token", header_name: "X-PFIM-Capability" })
      )
      .mockResolvedValueOnce(jsonResponse({ created: true }));
    vi.stubGlobal("fetch", fetchMock);
    const { apiFetch } = await import("./client");

    await apiFetch("/backup", { method: "POST" });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[0][0]).toContain("/security/capability");
    const mutationInit = fetchMock.mock.calls[1][1] as RequestInit;
    expect(new Headers(mutationInit.headers).get("X-PFIM-Capability")).toBe("secret-token");
  });

  it("only retries a rejection before the handler caused by an expired token", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ token: "old", header_name: "X-PFIM-Capability" }))
      .mockResolvedValueOnce(
        jsonResponse(
          { error_code: "CAPABILITY_INVALID", message: "token reset" },
          { status: 403 }
        )
      )
      .mockResolvedValueOnce(jsonResponse({ token: "new", header_name: "X-PFIM-Capability" }))
      .mockResolvedValueOnce(jsonResponse({ created: true }));
    vi.stubGlobal("fetch", fetchMock);
    const { apiFetch } = await import("./client");

    await expect(apiFetch("/backup", { method: "POST" })).resolves.toEqual({ created: true });

    expect(fetchMock).toHaveBeenCalledTimes(4);
    const retryInit = fetchMock.mock.calls[3][1] as RequestInit;
    expect(new Headers(retryInit.headers).get("X-PFIM-Capability")).toBe("new");
  });

  it("does not retry a different application 403", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({ token: "secret-token", header_name: "X-PFIM-Capability" })
      )
      .mockResolvedValueOnce(
        jsonResponse({ error_code: "FORBIDDEN", message: "operation forbidden" }, { status: 403 })
      );
    vi.stubGlobal("fetch", fetchMock);
    const { apiFetch } = await import("./client");

    await expect(apiFetch("/example", { method: "DELETE" })).rejects.toThrow(
      "operation forbidden"
    );

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("limits renewal to one attempt even when the new token is rejected", async () => {
    const rejection = () => jsonResponse(
      { error_code: "CAPABILITY_INVALID", message: "invalid token" },
      { status: 403 }
    );
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ token: "old", header_name: "X-PFIM-Capability" }))
      .mockResolvedValueOnce(rejection())
      .mockResolvedValueOnce(jsonResponse({ token: "new", header_name: "X-PFIM-Capability" }))
      .mockResolvedValueOnce(rejection());
    vi.stubGlobal("fetch", fetchMock);
    const { apiFetch } = await import("./client");

    await expect(apiFetch("/backup", { method: "POST" })).rejects.toMatchObject({
      status: 403, errorCode: "CAPABILITY_INVALID",
    });
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it("exposes maintenance without repeating the mutation", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ token: "current", header_name: "X-PFIM-Capability" }))
      .mockResolvedValueOnce(jsonResponse(
        { error_code: "MAINTENANCE_MODE", message: "Maintenance in progress" },
        { status: 503 }
      ));
    vi.stubGlobal("fetch", fetchMock);
    const { apiFetch } = await import("./client");

    await expect(apiFetch("/backup", { method: "POST" })).rejects.toMatchObject({
      status: 503, errorCode: "MAINTENANCE_MODE", message: "Maintenance in progress",
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("preserves status, error_code and detail in API errors", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(
        {
          error_code: "BACKUP_VERIFICATION_FAILED",
          message: "invalid manifest",
          detail: { filename: "backup.db" },
        },
        { status: 409 }
      )
    );
    vi.stubGlobal("fetch", fetchMock);
    const { ApiError, apiFetch } = await import("./client");

    const error = await apiFetch("/backup/example/restore", { method: "GET" }).catch(
      (caught: unknown) => caught
    );

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      message: "invalid manifest",
      status: 409,
      errorCode: "BACKUP_VERIFICATION_FAILED",
      detail: { filename: "backup.db" },
    });
  });

  it("distinguishes failed bootstrap from a mutation with a lost response", async () => {
    const bootstrapFailure = vi.fn().mockRejectedValue(new TypeError("offline"));
    vi.stubGlobal("fetch", bootstrapFailure);
    let client = await import("./client");

    await expect(client.apiFetch("/backup/example/restore", { method: "POST" })).rejects
      .toMatchObject({ requestSent: false });
    expect(bootstrapFailure).toHaveBeenCalledOnce();

    vi.resetModules();
    const responseLost = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({ token: "secret-token", header_name: "X-PFIM-Capability" })
      )
      .mockRejectedValueOnce(new TypeError("connection reset"));
    vi.stubGlobal("fetch", responseLost);
    client = await import("./client");

    await expect(client.apiFetch("/backup/example/restore", { method: "POST" })).rejects
      .toMatchObject({ requestSent: true });
    expect(responseLost).toHaveBeenCalledTimes(2);
  });
});
