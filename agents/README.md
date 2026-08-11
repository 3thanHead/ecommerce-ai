# Agents

Every LLM prompt this app uses lives here, one file per agent -- not as a
string constant buried in a `.py` file. Loaded and driven by `backend/agent.py`
(`Agent(name, heavy=...)` / `ToolAgent(name, tools=..., heavy=...)`); nothing
else needs to know the file format below.

## File format

```
<system prompt -- everything the model is told about its job, in plain
markdown prose. This is the whole prompt: no templating, no variables. The
per-call data (real CJ products, real Reddit posts, web search results, etc.)
is built by the Python caller and sent as the user message -- the agent only
ever sees the finished prose you write here plus whatever data-of-the-moment
the caller hands it.>

​```json
<optional, ToolAgent only: the tools this agent may call, Ollama/OpenAI
function-calling shape -- [{"type": "function", "function": {"name": ...,
"description": ..., "parameters": {...JSON Schema...}}}, ...]. Only present
when this file is used with ToolAgent; a plain Agent ignores this block
entirely, so don't add it unless the agent actually calls tools.>
​```

​```json
<the JSON Schema the reply must match, enforced by Ollama's schema-constrained
decoding (valid-by-construction, no empty/broken replies). Omit this whole
fenced block (and the tools block above) entirely for a plain-text agent
(e.g. a caption writer) -- .chat() then returns raw text instead of a parsed
dict. If this is the file's ONLY fenced block, it's the schema, not tools --
the tools block only exists when there's a second block after it.>
​```
```

The schema (and, for a ToolAgent, the tool defs) live in the same file as the
prompt that has to satisfy them on purpose: change one, you're looking
straight at the other, so they can't quietly drift apart.

## Adding a plain agent

1. Write `agents/<name>.md`: prompt, then an optional single ` ```json ` schema block.
2. In the `.py` module that needs it, module-level: `_agent = Agent("<name>")`
   (add `heavy=True` to route it through the bigger node -- see
   `backend/config.py`'s `ollama_heavy_*` settings -- for a knowledge-heavy
   judgment call; the default workhorse model is fine for most agents).
3. Call `await _agent.chat(user_message)` (or `.chat_stream(...)` to stream
   into a `progress.Steps` "thinking" panel). Build `user_message` from real
   data; that assembly, and everything you do with the reply afterward, is
   Python's job, not the agent's.

## Adding a tool-calling agent

1. Write `agents/<name>.md`: prompt, then a ` ```json ` **tools** block, then
   a ` ```json ` **schema** block (both required -- a ToolAgent always
   finalizes into a structured reply).
2. Write the tool(s) themselves in Python: `async def _do_x(arguments: dict) -> str`
   per tool -- this is real logic (an HTTP call, a DB read, whatever), so it's
   code, not agent text. Its name must exactly match the `"name"` declared in
   the tools block.
3. Module-level: `_agent = ToolAgent("<name>", tools={"tool_name": _do_x}, max_rounds=4)`.
   Construction raises immediately if the declared tool names and the
   `tools=` dict don't match exactly -- a typo fails at import, not mid-request.
4. Call `await _agent.run(user_message, on_chunk=...)`. It loops the model
   through tool calls (executing each via your Python function, feeding the
   result back) until the model stops asking, then finalizes into the
   declared schema -- same return shape as a plain `Agent.chat()`, so callers
   never need to know an agent used tools at all.

## Current agents

| File | Used by | Heavy | Tools | Job |
|---|---|---|---|---|
| `cluster.md` | `research/prospect.py` | yes | – | group real CJ products into storefront concepts |
| `aisle-map.md` | `research/prospect.py` | yes | – | map a shopper theme onto CJ's real category tree |
| `product-judge.md` | `research/products.py` | yes | – | verify a CJ product genuinely IS a given idea |
| `drill.md` | `research/drilldown.py` | no | – | audience research: subreddit posting fit + product opportunities from real Reddit evidence |
| `caption.md` | `research/captions.py` | no | – | short-form social ad caption for a product (plain text, no schema) |
| `web-research.md` | `research/webresearch.py` | no | `web_search` | search the open web (via local SearXNG) for real evidence on a product/category, feeds `drill()` |
