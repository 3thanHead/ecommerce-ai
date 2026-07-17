"""shop -- the approval-gated venture agent (machinery in shop/venture.py).

Stage ladder: 0 niche pick -> 1 brand -> 2 catalog -> 3 assembly ->
4 marketing. Every stage generates, then WAITS for the user; approving a
stage auto-generates the next one. brand is a stub that passes through on
approval.

Chat commands (parsed here in code -- run() is overridden, no tool loop):

    start <seed topic>   new venture; generates niche+product candidates
    pick <n> [notes]     choose a stage-0 candidate; routes everything after
    approve [notes]      approve the current stage -> next stage generates
    revise <notes>       regenerate the current stage with your notes
    status / show [stage]
    pay <sku> | publish <sku> | blog <sku>     product utilities
    list products|posts

final.output schema:
    {"status": "...", "message": "<what happened + what to do next>",
     "stage": "<current>", "ladder": [...], ...stage payloads}
"""
import logging

from langchain_core.messages import HumanMessage, SystemMessage

from .. import db
from . import events
from .base import BaseAgent, _extract_json
from .shop import venture

log = logging.getLogger("agents.shop")

USAGE = ("Commands: `start <seed topic>`, then per stage: `pick <n>`, "
         "`approve [notes]`, `revise <notes>`. Also `status`, `show [stage]`, "
         "`pay|publish|blog <sku>`, `list products|posts`.")


class ShopAgent(BaseAgent):
    name = "shop"
    description = ("Builds a store stage by stage — niche pick, brand, "
                   "catalog, assembly, marketing — pausing for your "
                   "approval at every stage.")

    # run() is overridden; these only satisfy the abstract interface.
    def system_prompt(self) -> str:
        return ""

    def tools(self):
        return []

    async def _llm_json(self, system: str, user: str) -> dict:
        ai = await self.llm().ainvoke([SystemMessage(system), HumanMessage(user)])
        return _extract_json(str(ai.content)) or {}

    # -- entry ----------------------------------------------------------------

    async def run(self, input_text: str):
        yield events.start(self.name, input_text[:200])
        cmd, _, arg = input_text.strip().partition(" ")
        cmd, arg = cmd.lower(), arg.strip()
        try:
            v = await venture.get()
            if cmd in ("start", "new") and arg:
                v = venture.new(arg)
                async for ev in self._generate(v, notes=""):
                    yield ev
            elif v is None:
                yield events.final({"status": "idle", "message":
                    "No venture yet — `start <seed topic>` begins one. " + USAGE})
            elif cmd == "pick":
                async for ev in self._pick(v, arg):
                    yield ev
            elif cmd in ("approve", "ok", "lgtm"):
                async for ev in self._approve(v, arg):
                    yield ev
            elif cmd in ("revise", "redo", "again"):
                async for ev in self._generate(v, notes=arg, regen=True):
                    yield ev
            elif cmd in ("next", "continue", "generate"):
                async for ev in self._generate(v, notes=""):
                    yield ev
            elif cmd == "status":
                yield events.final(self._status(v))
            elif cmd == "show":
                yield events.final(self._show(v, arg))
            elif cmd in ("pay", "publish", "blog"):
                async for ev in self._product_util(cmd, arg):
                    yield ev
            elif cmd == "list":
                yield events.final(await self._list(arg or "products"))
            else:
                yield events.final({**self._status(v), "message":
                    self._status(v)["message"] + " " + USAGE})
        except Exception as e:
            log.exception("shop agent failed")
            yield events.error(str(e))

    # -- the gated ladder --------------------------------------------------------

    async def _generate(self, v: dict, notes: str, regen: bool = False):
        """Generate (or regenerate) the current stage, store it as pending,
        and tell the user how to gate it."""
        stage = venture.current_stage(v)
        key = stage["key"]
        if not regen and v["stages"][key]["status"] == "pending":
            yield events.final({**self._status(v), "message":
                f"'{stage['title']}' is already waiting on you — {stage['gate']}, "
                f"or `revise <notes>`."})
            return
        yield events.tool_call(key, {"stage": stage["title"],
                                     **({"notes": notes} if notes else {})})
        out = await venture.GENERATORS[key](v, self._llm_json, notes)
        yield events.tool_result(key, out)
        if out.get("error"):
            yield events.final({"status": "error", "stage": key,
                                "message": f"{stage['title']} failed: {out['error']} "
                                           "— `next` retries, `revise <notes>` steers."})
            return
        entry = v["stages"][key]
        entry.update(status="pending", output=out)
        if notes:
            entry.setdefault("notes", []).append(notes)
        await venture.save(v)
        yield events.final({"status": "pending", "stage": key,
                            key: out, "ladder": venture.stage_brief(v),
                            "message": f"{stage['title']} ready — {stage['gate']}."})

    async def _pick(self, v: dict, arg: str):
        """Choose a niche candidate -- allowed at ANY point. Re-picking after
        stages were built resets everything downstream, because the niche
        routes all of it (site content, catalog, ...)."""
        candidates = (v["stages"]["niche"].get("output") or {}).get("candidates", [])
        if not candidates:
            yield events.final({**self._status(v), "message":
                "No candidates to pick from yet — `start <seed>` generates them."})
            return
        num, _, notes = arg.partition(" ")
        try:
            chosen = candidates[int(num) - 1]
        except (ValueError, IndexError):
            yield events.final({"status": "pending", "message":
                f"`pick <1-{len(candidates)}>` — see `show niche`."})
            return
        if notes.strip():  # user edits to the direction ride on the pick
            chosen = {**chosen, "angle": f"{chosen['angle']} ({notes.strip()})"}
        repick = v["stages"]["niche"]["status"] == "approved"
        v["stages"]["niche"].update(status="approved", picked=chosen)
        if repick:
            venture.reset_downstream(v, "niche")
        await venture.save(v)
        yield events.tool_result("pick", {"picked": chosen["niche"],
                                          **({"rerouted": True} if repick else {})})
        async for ev in self._generate(v, notes=""):
            yield ev

    async def _approve(self, v: dict, notes: str):
        stage = venture.current_stage(v)
        key = stage["key"]
        if v["stages"][key]["status"] != "pending":
            yield events.final({**self._status(v), "message":
                f"Nothing pending at '{stage['title']}' — `next` generates it first."})
            return
        if key == "niche":
            yield events.final({"status": "pending", "message":
                "The niche stage is approved by choosing: `pick <n>`."})
            return
        entry = v["stages"][key]
        entry["status"] = "approved"
        if notes:
            entry.setdefault("notes", []).append(notes)
        await venture.save(v)
        if key == STAGE_LAST:
            yield events.final({"status": "done", "ladder": venture.stage_brief(v),
                                "message": "Every stage is approved — the venture "
                                           "is fully staged. 🎉"})
            return
        async for ev in self._generate(v, notes=""):
            yield ev

    # -- reporting -----------------------------------------------------------------

    def _status(self, v: dict | None) -> dict:
        if v is None:
            return {"status": "idle", "message": "No venture — `start <seed>`."}
        stage = venture.current_stage(v)
        state = v["stages"][stage["key"]]["status"]
        doing = ("waiting on you: " + stage["gate"] if state == "pending"
                 else "`next` generates it")
        return {"status": "ok", "stage": stage["key"],
                "ladder": venture.stage_brief(v), "seed": v.get("seed"),
                "message": f"Venture '{v.get('seed')}' is at "
                           f"'{stage['title']}' ({state}) — {doing}."}

    def _show(self, v: dict, key: str) -> dict:
        key = key or venture.current_stage(v)["key"]
        if key not in venture.STAGE_KEYS:
            return {"status": "idle",
                    "message": f"Stages: {', '.join(venture.STAGE_KEYS)}."}
        entry = v["stages"][key]
        return {"status": "ok", "stage": key, key: entry.get("output"),
                "picked": entry.get("picked"),
                "message": f"'{key}' is {entry['status']}."}

    async def _product_util(self, cmd: str, sku: str):
        p = (await db.find(venture.PRODUCTS, where={"sku": sku}, limit=1)
             or [None])[0] if sku else None
        if p is None:
            yield events.final({"status": "idle", "message":
                f"`{cmd} <sku>` needs a catalog sku — `list products`."})
            return
        yield events.tool_call(cmd, {"sku": sku})
        if cmd == "pay":
            out = await venture.payment_link(p)
            msg = out.get("payment_url") or out.get("error", "")
        elif cmd == "publish":
            out = await venture.publish_product(p)
            oks = [r["platform"] for r in out if r.get("ok")]
            msg = "Published to " + ", ".join(oks) + "." if oks else "Published nowhere."
        else:
            out = await venture.write_post(p, self._llm_json)
            msg = out.get("url") or out.get("error", "")
        yield events.tool_result(cmd, out)
        yield events.final({"status": "ok" if not (isinstance(out, dict) and out.get("error"))
                            else "error", cmd: out, "message": str(msg)})

    async def _list(self, what: str) -> dict:
        what = "posts" if what.rstrip("s") in ("post", "blog") else "products"
        items = await db.find(what, order_by="created_at" if what == "products"
                              else "published_at", desc=True, limit=25)
        keys = (("sku", "title", "kind", "price_usd", "status", "payment_url")
                if what == "products" else ("slug", "title", "url", "sku"))
        return {"status": "ok", what: [{k: i.get(k) for k in keys} for i in items],
                "message": f"{len(items)} {what}."}


STAGE_LAST = venture.STAGE_KEYS[-1]

AGENT = ShopAgent()
