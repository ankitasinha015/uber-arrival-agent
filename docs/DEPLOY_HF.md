# Deploy the live demo to Hugging Face Spaces

An always-on public link (works when your laptop is off). The concierge runs **live** —
every persona makes real Foursquare + Mapbox calls; nothing is recorded or hardcoded.

Runtime needs two secrets: `FOURSQUARE_API_KEY` and `MAPS_API_KEY` (Mapbox). It does
**not** need an Anthropic key or ChromaDB — the persona dinner ranking is deterministic
and the geo is the live call.

## One-time setup

**1. Create the Space** — <https://huggingface.co/new-space>
- Owner: you · Space name: `uber-arrival-agent`
- SDK: **Docker** → *Blank* · Hardware: **CPU basic** (free) · Visibility: **Public**

**2. Add the API keys as secrets** — Space → *Settings* → *Variables and secrets* → *New secret*:
- `FOURSQUARE_API_KEY` = your Foursquare key
- `MAPS_API_KEY` = your Mapbox token

(These are the same values from your local `.env`. HF stores them encrypted; they are
never committed.)

**3. Push the code** to the Space's git repo:

```bash
# from the project root
git remote add space https://huggingface.co/spaces/<your-username>/uber-arrival-agent
git push space main
```

If Git asks for a password, use a Hugging Face **access token** with *write* scope
(<https://huggingface.co/settings/tokens>) as the password, your HF username as the user.

HF builds the Dockerfile (~2–4 min; watch the *Logs* tab). When it's green:

- **Concierge demo:** `https://<your-username>-uber-arrival-agent.hf.space/concierge`
- Single-moment arrival agent: `https://<your-username>-uber-arrival-agent.hf.space/`

## Redeploying after changes

```bash
git push space main
```

## Notes

- **Live == real quota.** Every arrival hits Foursquare/Mapbox. Fine for demos; just be
  aware it uses your API allowance.
- **SSE streams cleanly** on HF (unlike a Cloudflare quick tunnel, which buffers it) —
  the agent's reasoning appears live.
- The Space's README front-matter (`sdk: docker`, `app_port: 7860`) lives at the top of
  the repo's `README.md`; keep it when you edit.
