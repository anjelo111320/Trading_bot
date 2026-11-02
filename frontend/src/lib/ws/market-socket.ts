/** WebSocket client: reconnect, resubscribe and gap detection, per docs/13-API-CONTRACTS.md. */

export type ConnectionState = "connecting" | "open" | "closed";

export type MarketEvent = {
  event_type: string;
  seq: number;
  occurred_at: string;
  data_origin: "live" | "backfill" | "synthetic";
  payload: Record<string, unknown>;
};

const BASE_DELAY_MS = 1_000;
const MAX_DELAY_MS = 30_000;
const SILENCE_LIMIT_MS = 45_000;

/** Exponential backoff with jitter, capped at 30 seconds. */
export function nextDelay(attempt: number, random: () => number = Math.random): number {
  const delay = Math.min(BASE_DELAY_MS * 2 ** attempt, MAX_DELAY_MS);
  return delay / 2 + random() * (delay / 2);
}

/** Tracks `seq` per topic. A jump means an event was missed. */
export class SequenceTracker {
  private readonly seen = new Map<string, number>();

  /** Returns true when events were missed. */
  observe(topic: string, seq: number): boolean {
    const last = this.seen.get(topic);
    this.seen.set(topic, seq);
    return last !== undefined && seq > last + 1;
  }

  reset(): void {
    this.seen.clear();
  }
}

export function topicOf(event: MarketEvent): string {
  const { provider, instrument_id: instrument, timeframe } = event.payload;
  if (event.event_type === "market.status") {
    return `market.status:${provider}`;
  }
  return timeframe
    ? `${event.event_type}:${provider}:${instrument}:${timeframe}`
    : `${event.event_type}:${provider}:${instrument}`;
}

type Options = {
  url: string;
  topics: string[];
  getTicket: () => Promise<string>;
  onEvent: (event: MarketEvent) => void;
  onResync: (topic: string) => void;
  onState: (state: ConnectionState) => void;
};

export class MarketSocket {
  private socket: WebSocket | null = null;
  private attempt = 0;
  private stopped = false;
  private retry: ReturnType<typeof setTimeout> | undefined;
  private silence: ReturnType<typeof setTimeout> | undefined;
  private readonly sequence = new SequenceTracker();

  constructor(private readonly options: Options) {}

  start(): void {
    void this.connect();
  }

  stop(): void {
    this.stopped = true;
    clearTimeout(this.retry);
    clearTimeout(this.silence);
    this.socket?.close();
    this.socket = null;
  }

  private async connect(): Promise<void> {
    if (this.stopped) {
      return;
    }
    this.options.onState("connecting");
    let ticket: string;
    try {
      ticket = await this.options.getTicket();
    } catch {
      this.scheduleRetry();
      return;
    }
    if (this.stopped) {
      return;
    }
    const socket = new WebSocket(`${this.options.url}?ticket=${encodeURIComponent(ticket)}`);
    this.socket = socket;
    socket.onopen = () => this.opened(socket);
    socket.onmessage = (message) => this.received(String(message.data));
    socket.onclose = () => this.closed(socket);
  }

  private opened(socket: WebSocket): void {
    this.attempt = 0;
    this.sequence.reset();
    this.options.onState("open");
    this.watchSilence();
    socket.send(JSON.stringify({ type: "subscribe", topics: this.options.topics }));
    // After any connection, history may have moved on while this client was away.
    this.options.topics.forEach((topic) => this.options.onResync(topic));
  }

  private received(raw: string): void {
    this.watchSilence();
    const message = JSON.parse(raw) as MarketEvent | { type: string; topic?: string };
    if ("type" in message) {
      if (message.type === "resync" && message.topic) {
        this.options.onResync(message.topic);
      }
      return;
    }
    const topic = topicOf(message);
    if (this.sequence.observe(topic, message.seq)) {
      this.options.onResync(topic);
    }
    this.options.onEvent(message);
  }

  private closed(socket: WebSocket): void {
    if (this.socket === socket) {
      this.socket = null;
    }
    clearTimeout(this.silence);
    this.options.onState("closed");
    this.scheduleRetry();
  }

  private watchSilence(): void {
    clearTimeout(this.silence);
    this.silence = setTimeout(() => this.socket?.close(), SILENCE_LIMIT_MS);
  }

  private scheduleRetry(): void {
    if (this.stopped) {
      return;
    }
    this.retry = setTimeout(() => void this.connect(), nextDelay(this.attempt));
    this.attempt += 1;
  }
}
