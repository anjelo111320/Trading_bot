import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MarketSocket, SequenceTracker, nextDelay, topicOf, type MarketEvent } from "./market-socket";

class FakeSocket {
  static instances: FakeSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((message: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  sent: string[] = [];

  constructor(readonly url: string) {
    FakeSocket.instances.push(this);
  }

  send(body: string) {
    this.sent.push(body);
  }

  close() {
    this.onclose?.();
  }
}

const TOPIC = "market.candle:binance_usdm:3:1m";

function candleEvent(seq: number): string {
  const event: MarketEvent = {
    event_type: "market.candle",
    seq,
    occurred_at: "2026-11-02T00:00:00Z",
    data_origin: "live",
    payload: { provider: "binance_usdm", instrument_id: 3, timeframe: "1m" },
  };
  return JSON.stringify(event);
}

function build(getTicket: () => Promise<string> = () => Promise.resolve("t1")) {
  const events: MarketEvent[] = [];
  const resyncs: string[] = [];
  const states: string[] = [];
  const socket = new MarketSocket({
    url: "ws://test/api/v1/ws",
    topics: [TOPIC],
    getTicket,
    onEvent: (event) => events.push(event),
    onResync: (topic) => resyncs.push(topic),
    onState: (state) => states.push(state),
  });
  return { socket, events, resyncs, states };
}

async function flush() {
  await vi.advanceTimersByTimeAsync(0);
}

describe("nextDelay", () => {
  it("doubles, then stops at the cap", () => {
    expect(nextDelay(0, () => 1)).toBe(1_000);
    expect(nextDelay(3, () => 1)).toBe(8_000);
    expect(nextDelay(20, () => 1)).toBe(30_000);
  });

  it("always waits at least half the delay", () => {
    expect(nextDelay(0, () => 0)).toBe(500);
  });
});

describe("SequenceTracker", () => {
  it("accepts consecutive events", () => {
    const tracker = new SequenceTracker();
    expect(tracker.observe("t", 5)).toBe(false);
    expect(tracker.observe("t", 6)).toBe(false);
  });

  it("detects a jump", () => {
    const tracker = new SequenceTracker();
    tracker.observe("t", 5);
    expect(tracker.observe("t", 8)).toBe(true);
  });

  it("tracks topics separately", () => {
    const tracker = new SequenceTracker();
    tracker.observe("a", 5);
    expect(tracker.observe("b", 90)).toBe(false);
  });
});

describe("topicOf", () => {
  it("rebuilds the candle topic", () => {
    expect(topicOf(JSON.parse(candleEvent(1)))).toBe(TOPIC);
  });

  it("rebuilds the status topic", () => {
    const event = { event_type: "market.status", payload: { provider: "binance_spot" } };
    expect(topicOf(event as unknown as MarketEvent)).toBe("market.status:binance_spot");
  });
});

describe("MarketSocket", () => {
  beforeEach(() => {
    FakeSocket.instances = [];
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", FakeSocket);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("subscribes on open and refills history", async () => {
    const { socket, resyncs, states } = build();
    socket.start();
    await flush();
    const [fake] = FakeSocket.instances;
    fake!.onopen!();
    expect(JSON.parse(fake!.sent[0]!)).toEqual({ type: "subscribe", topics: [TOPIC] });
    expect(resyncs).toEqual([TOPIC]);
    expect(states).toEqual(["connecting", "open"]);
    socket.stop();
  });

  it("reconnects with a new ticket and subscribes again without a page reload", async () => {
    const tickets = ["first", "second"];
    const { socket, resyncs } = build(() => Promise.resolve(tickets.shift()!));
    socket.start();
    await flush();
    FakeSocket.instances[0]!.onopen!();
    FakeSocket.instances[0]!.close();
    await vi.advanceTimersByTimeAsync(1_000);
    const second = FakeSocket.instances[1]!;
    expect(second.url).toContain("ticket=second");
    second.onopen!();
    expect(second.sent).toHaveLength(1);
    expect(resyncs).toHaveLength(2);
    socket.stop();
  });

  it("refills a topic when an event was missed", async () => {
    const { socket, resyncs, events } = build();
    socket.start();
    await flush();
    const fake = FakeSocket.instances[0]!;
    fake.onopen!();
    resyncs.length = 0;
    fake.onmessage!({ data: candleEvent(1) });
    fake.onmessage!({ data: candleEvent(2) });
    expect(resyncs).toEqual([]);
    fake.onmessage!({ data: candleEvent(5) });
    expect(resyncs).toEqual([TOPIC]);
    expect(events).toHaveLength(3);
    socket.stop();
  });

  it("obeys a resync request from a server whose queue overflowed", async () => {
    const { socket, resyncs } = build();
    socket.start();
    await flush();
    const fake = FakeSocket.instances[0]!;
    fake.onopen!();
    resyncs.length = 0;
    fake.onmessage!({ data: JSON.stringify({ type: "resync", topic: TOPIC }) });
    expect(resyncs).toEqual([TOPIC]);
    socket.stop();
  });

  it("reconnects if the server goes silent", async () => {
    const { socket } = build();
    socket.start();
    await flush();
    FakeSocket.instances[0]!.onopen!();
    await vi.advanceTimersByTimeAsync(45_000);
    await vi.advanceTimersByTimeAsync(1_000);
    expect(FakeSocket.instances.length).toBe(2);
    socket.stop();
  });

  it("retries when a ticket cannot be fetched", async () => {
    let calls = 0;
    const { socket } = build(() => {
      calls += 1;
      return calls === 1 ? Promise.reject(new Error("down")) : Promise.resolve("t");
    });
    socket.start();
    await flush();
    expect(FakeSocket.instances).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(1_000);
    expect(FakeSocket.instances).toHaveLength(1);
    socket.stop();
  });

  it("stays stopped", async () => {
    const { socket } = build();
    socket.start();
    await flush();
    socket.stop();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(FakeSocket.instances).toHaveLength(1);
  });
});
