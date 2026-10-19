// Pi extension: sends one OTLP/HTTP-JSON log record per model response to the collector.
// Pi has no OTel exporter of its own. Sends usage metadata only (model, tokens, cost, tool names), never text.
// Install: copy to ~/.pi/agent/extensions/. Endpoint: OTEL_EXPORTER_OTLP_ENDPOINT, else ENDPOINT below.
const ENDPOINT = process.env.OTEL_EXPORTER_OTLP_ENDPOINT || "http://127.0.0.1:6979";
const TIMEOUT_MS = 2000;

const attr = (key: string, v: unknown) =>
  typeof v === "number" ? { key, value: Number.isInteger(v) ? { intValue: v } : { doubleValue: v } } : { key, value: { stringValue: String(v) } };

export default function (pi: any) {
  pi.on("message_end", async (event: any, ctx: any) => {
    const m = event.message;
    if (m?.role !== "assistant" || !m.usage) return;
    const u = m.usage;
    const tools = (m.content || []).filter((b: any) => b.type === "toolCall").map((b: any) => b.name);
    const record = {
      timeUnixNano: String(Date.now() * 1e6),
      body: { stringValue: "pi.api_request" },
      attributes: [
        attr("session.id", ctx?.sessionManager?.getSessionId?.() ?? ""), attr("cwd", ctx?.cwd ?? ""),
        attr("provider", m.provider), attr("model", m.model), attr("stop_reason", m.stopReason),
        attr("input_tokens", u.input), attr("output_tokens", u.output), attr("cache_read_tokens", u.cacheRead),
        attr("cache_creation_tokens", u.cacheWrite), attr("reasoning_tokens", u.reasoning ?? 0),
        attr("cost_usd", u.cost?.total ?? 0), attr("tools", tools.join(",")),
      ],
    };
    const body = { resourceLogs: [{ resource: { attributes: [attr("service.name", "pi")] }, scopeLogs: [{ logRecords: [record] }] }] };
    try {
      await fetch(ENDPOINT.replace(/\/$/, "") + "/v1/logs", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal: AbortSignal.timeout(TIMEOUT_MS),
      });
    } catch {} // collector down: drop silently, like the native exporters
  });
}
