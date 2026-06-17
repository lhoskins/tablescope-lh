import { describe, expect, it, vi } from "vitest";

const streamMock = vi.fn();

vi.mock("@/lib/api-client", () => ({
  apiClient: {
    stream: (...args: unknown[]) => streamMock(...args),
  },
}));

import { streamHomeIntelligence, type IntelligenceEvent } from "./home-intelligence";

function responseFromFrames(frames: string[]): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const f of frames) controller.enqueue(encoder.encode(f));
      controller.close();
    },
  });
  return { ok: true, status: 200, body } as unknown as Response;
}

function collect(): Promise<IntelligenceEvent[]> {
  return new Promise((resolve) => {
    const events: IntelligenceEvent[] = [];
    streamHomeIntelligence((e) => {
      events.push(e);
      if (e.type === "done") resolve(events);
    });
  });
}

describe("streamHomeIntelligence", () => {
  it("parses SSE frames into typed events", async () => {
    streamMock.mockResolvedValueOnce(
      responseFromFrames([
        'data: {"type":"start","projects":[{"id":"1","name":"A","color":"#000"}]}\n\n',
        'data: {"type":"project_complete","projectId":"1","projectName":"A","projectColor":"#000","insights":[]}\n\n',
        'data: {"type":"done","projectCount":1}\n\n',
      ]),
    );
    const events = await collect();
    expect(events.map((e) => e.type)).toEqual([
      "start",
      "project_complete",
      "done",
    ]);
  });

  it("passes granularity through to the stream URL", async () => {
    streamMock.mockResolvedValueOnce(
      responseFromFrames(['data: {"type":"done","projectCount":0}\n\n']),
    );
    await new Promise<void>((resolve) => {
      streamHomeIntelligence(
        (e) => {
          if (e.type === "done") resolve();
        },
        { granularity: 5 },
      );
    });
    expect(streamMock).toHaveBeenCalledWith(
      expect.stringContaining("granularity=5"),
      expect.anything(),
    );
  });

  it("handles a frame split across multiple chunks", async () => {
    streamMock.mockResolvedValueOnce(
      responseFromFrames([
        'data: {"type":"st',
        'art","projects":[]}\n\n',
        'data: {"type":"done","projectCount":0}\n\n',
      ]),
    );
    const events = await collect();
    expect(events[0].type).toBe("start");
    expect(events[1].type).toBe("done");
  });

  it("emits a project_error when the response is not ok", async () => {
    streamMock.mockResolvedValueOnce({
      ok: false,
      status: 502,
      body: null,
    } as unknown as Response);
    const events: IntelligenceEvent[] = [];
    await new Promise<void>((resolve) => {
      streamHomeIntelligence((e) => {
        events.push(e);
        resolve();
      });
    });
    expect(events[0].type).toBe("project_error");
  });
});
