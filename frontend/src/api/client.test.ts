import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "./client";

afterEach(() => vi.unstubAllGlobals());

function respond(status: number, body: string, contentType: string) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(body, { status, headers: { "Content-Type": contentType } })));
}

describe("api client", () => {
  it("reports a missing backend when /api answers with HTML (app published as a static site)", async () => {
    respond(200, "<!doctype html><div id=root></div>", "text/html");
    await expect(api("/meta")).rejects.toMatchObject({ code: "not_json", status: 200 });
  });

  it("reports a missing backend when /api is a plain 404 page", async () => {
    respond(404, "Not Found", "text/plain");
    await expect(api("/meta")).rejects.toBeInstanceOf(ApiError);
    await expect(api("/meta")).rejects.toMatchObject({ code: "not_json", status: 404 });
  });

  it("keeps the API's own error codes", async () => {
    respond(403, JSON.stringify({ error: { code: "forbidden" } }), "application/json");
    await expect(api("/team")).rejects.toMatchObject({ code: "forbidden", status: 403 });
  });

  it("returns JSON bodies", async () => {
    respond(200, JSON.stringify({ ok: true }), "application/json");
    await expect(api("/meta")).resolves.toEqual({ ok: true });
  });
});
