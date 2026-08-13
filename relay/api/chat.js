// flightsim compiler relay -- an OpenAI-compatible /v1/chat/completions
// proxy so a fresh clone can compile prompts with ZERO setup.
//
// What this function does, exactly:
//   * holds the OpenAI key SERVER-SIDE (process.env.OPENAI_API_KEY, set as
//     a Vercel project env var -- the key never appears in this repo, in
//     responses, or in logs);
//   * pins the model to gpt-4.1-mini regardless of what the client sends
//     (the relay pays per token; the client does not get to pick);
//   * rate-limits per client IP and per instance, and caps request size,
//     because the endpoint is anonymous by design;
//   * forwards ONLY a whitelisted request shape (messages, max_tokens,
//     temperature, response_format) -- no streaming, no tools, no images.
//
// Honesty note carried from the main repo: the in-memory rate limiter is
// per warm serverless instance, not global -- Vercel may run several
// instances, so the real ceiling is (limit x instances). It deters casual
// abuse; it is not a billing guarantee. The spend guarantee is the
// account's own hard usage limit on platform.openai.com.

const PINNED_MODEL = "gpt-4.1-mini";
const UPSTREAM = "https://api.openai.com/v1/chat/completions";

const PER_IP_LIMIT = 40;          // requests per window per IP
const INSTANCE_LIMIT = 200;       // requests per window, whole instance
const WINDOW_MS = 60 * 60 * 1000; // 1 hour sliding window
const MAX_BODY_CHARS = 200_000;   // the compiler's system prompt is ~20k
const MAX_COMPLETION_TOKENS = 4096; // the compiler's own max_tokens

const hits = new Map(); // ip -> [timestamps]; per-instance memory only

function prune(list, now) {
  while (list.length && now - list[0] > WINDOW_MS) list.shift();
  return list;
}

function rateLimited(ip) {
  const now = Date.now();
  const mine = prune(hits.get(ip) || [], now);
  let total = 0;
  for (const [key, list] of hits) {
    const kept = prune(list, now);
    if (kept.length) { hits.set(key, kept); total += kept.length; }
    else hits.delete(key);
  }
  if (mine.length >= PER_IP_LIMIT || total >= INSTANCE_LIMIT) return true;
  mine.push(now);
  hits.set(ip, mine);
  return false;
}

export default async function handler(req, res) {
  if (req.method === "GET") {
    // Health probe: states the pinned model and limits, nothing secret.
    res.status(200).json({
      service: "flightsim-relay",
      model: PINNED_MODEL,
      per_ip_per_hour: PER_IP_LIMIT,
      source: "https://github.com/DhruvaValluru/flightsim/tree/main/relay",
    });
    return;
  }
  if (req.method !== "POST") {
    res.status(405).json({ error: { message: "POST /v1/chat/completions" } });
    return;
  }

  const key = process.env.OPENAI_API_KEY;
  if (!key) {
    res.status(503).json({ error: {
      message: "relay misconfigured: OPENAI_API_KEY env var not set" } });
    return;
  }

  const ip = (req.headers["x-forwarded-for"] || "").split(",")[0].trim()
    || req.socket?.remoteAddress || "unknown";
  if (rateLimited(ip)) {
    res.status(429).json({ error: {
      message: `relay rate limit: ${PER_IP_LIMIT} requests/hour per IP; ` +
        "run your own model instead (FLIGHTSIM_LLM=ollama) or bring a key " +
        "(FLIGHTSIM_LLM=groq/openai)" } });
    return;
  }

  const body = req.body;
  if (!body || !Array.isArray(body.messages) || body.messages.length === 0) {
    res.status(400).json({ error: { message: "messages[] required" } });
    return;
  }
  if (JSON.stringify(body).length > MAX_BODY_CHARS) {
    res.status(413).json({ error: {
      message: `request over ${MAX_BODY_CHARS} chars` } });
    return;
  }
  if (body.stream) {
    res.status(400).json({ error: { message: "streaming not supported" } });
    return;
  }

  // Whitelist: everything else the client sent is dropped, and the model
  // field in particular is REPLACED, never forwarded.
  const upstreamBody = {
    model: PINNED_MODEL,
    messages: body.messages,
    max_tokens: Math.min(
      Number(body.max_tokens) || MAX_COMPLETION_TOKENS, MAX_COMPLETION_TOKENS),
    temperature: Math.max(0, Math.min(Number(body.temperature) || 0, 1)),
  };
  if (body.response_format && typeof body.response_format === "object") {
    // OpenAI's strict:true accepts only its own schema subset (every
    // property required, etc.) and 400s on the flightsim compiler's
    // schema, whose fields are optional by design. Forward the schema as
    // guidance, not grammar: the client's own strict parser is the
    // enforcement either way.
    const rf = structuredClone(body.response_format);
    if (rf.json_schema && typeof rf.json_schema === "object") {
      rf.json_schema.strict = false;
    }
    upstreamBody.response_format = rf;
  }

  try {
    const upstream = await fetch(UPSTREAM, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${key}`,
      },
      body: JSON.stringify(upstreamBody),
    });
    const text = await upstream.text();
    res.status(upstream.status)
      .setHeader("Content-Type", "application/json")
      .send(text);
  } catch (err) {
    res.status(502).json({ error: {
      message: `upstream unreachable: ${err?.message || "fetch failed"}` } });
  }
}
