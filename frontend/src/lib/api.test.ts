import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getMe, parseSse, streamMessage, type StreamEvent } from "./api";
import { getAccessToken, getRefreshToken, storeTokens } from "./auth";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

describe("token refresh", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    window.localStorage.clear();
    storeTokens("expired-access", "refresh-1");
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockReset();
  });

  afterEach(() => vi.unstubAllGlobals());

  it("runs a single refresh when parallel requests get a 401", async () => {
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input);
      const auth = new Headers(init?.headers).get("authorization");
      if (url.endsWith("/auth/refresh")) {
        return jsonResponse(200, {
          access_token: "fresh-access",
          refresh_token: "refresh-2",
          token_type: "bearer",
          expires_in: 900,
        });
      }
      if (auth === "Bearer expired-access") {
        return jsonResponse(401, { title: "Unauthorized", detail: "expired" });
      }
      return jsonResponse(200, {
        id: "u",
        email: "u@x",
        role: "patient",
        display_name: "U",
        organization_id: "o",
      });
    });

    const [a, b] = await Promise.all([getMe(), getMe()]);

    expect(a.display_name).toBe("U");
    expect(b.display_name).toBe("U");
    const refreshCalls = fetchMock.mock.calls.filter(([input]) =>
      String(input).endsWith("/auth/refresh"),
    );
    expect(refreshCalls).toHaveLength(1);
    expect(getAccessToken()).toBe("fresh-access");
    expect(getRefreshToken()).toBe("refresh-2");
  });

  it("refreshes once on the stream path too", async () => {
    let streamCalls = 0;
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/refresh")) {
        return jsonResponse(200, {
          access_token: "fresh-access",
          refresh_token: "refresh-2",
          token_type: "bearer",
          expires_in: 900,
        });
      }
      streamCalls += 1;
      const auth = new Headers(init?.headers).get("authorization");
      if (auth !== "Bearer fresh-access") {
        return jsonResponse(401, { title: "Unauthorized", detail: "expired" });
      }
      return new Response(streamOf(['data: {"type":"start","simulated":true}\n\n']), {
        status: 200,
        headers: { "content-type": "text/event-stream" },
      });
    });

    const events: StreamEvent[] = [];
    await streamMessage("c1", "hello", (event) => events.push(event));

    expect(streamCalls).toBe(2);
    expect(events).toEqual([{ type: "start", simulated: true }]);
  });
});

describe("parseSse", () => {
  it("carries a partial line across chunk boundaries", async () => {
    const body = streamOf([
      'data: {"type":"start","simu',
      'lated":true}\n\ndata: {"type":"delta","text":"hi "}\n',
      '\ndata: {"type":"delta","text":"there"}\n\n',
    ]);
    const events: StreamEvent[] = [];
    for await (const event of parseSse(body)) events.push(event);
    expect(events).toEqual([
      { type: "start", simulated: true },
      { type: "delta", text: "hi " },
      { type: "delta", text: "there" },
    ]);
  });

  it("stops reading when aborted", async () => {
    const controller = new AbortController();
    controller.abort();
    const events: StreamEvent[] = [];
    for await (const event of parseSse(streamOf(['data: {"type":"delta","text":"x"}\n\n']), controller.signal)) {
      events.push(event);
    }
    expect(events).toEqual([]);
  });
});
