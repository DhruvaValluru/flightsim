# flightsim compiler relay

The Vercel serverless function behind `FLIGHTSIM_LLM=relay` -- the
zero-setup hosted tier. It proxies `/v1/chat/completions` to OpenAI with
a server-side key, pins the model to `gpt-4.1-mini`, rate-limits per IP
(40/hour) and rejects streaming/oversized requests. See the header
comment in [api/chat.js](api/chat.js) for the exact behaviour and the
stated limits of the in-memory rate limiter.

**There is no key in this directory or anywhere in the repo.** The key
lives only in the Vercel project's `OPENAI_API_KEY` env var, spend-capped
by the account's own usage limit.

Deploy your own (any Vercel account):

```bash
cd relay
npx vercel deploy --prod
npx vercel env add OPENAI_API_KEY production   # paste your key at the prompt
npx vercel deploy --prod                       # redeploy so the var applies
```

Then point the app at it: `FLIGHTSIM_LLM=relay` and
`FLIGHTSIM_RELAY_URL=https://<your-deployment>` in `~/.flightsim.env`.
