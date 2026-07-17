"""shop -- the machinery behind the `shop` agent (../shop_agent.py).

An approval-gated venture pipeline: every stage GENERATES, then WAITS -- the
user approves, revises with notes, or picks among candidates before anything
routes downstream. The stage ladder (venture.py):

    0 niche      niche + winning-product candidates w/ angles   (LLM, live)
    1 brand      store name/domains/voice/colors/tagline        (stub)
    2 catalog    per-product listing copy + image prompts       (LLM bulk, live)
    3 assembly   about/FAQ/policies + Shopify/Woo payload       (LLM, live)
    4 marketing  hooks, scripts, captions, posting calendar     (LLM, live)

Division of labor (house rule): the LLM only does judgment work -- candidates,
copy, prompts; code does everything mechanical -- state, approvals, SKUs,
Stripe (stripe_client.py), Printify (printify.py), the AI-safe publish
allowlist (platforms.py), and the single storefront template (render.py)
served by api/blog.py + rendered static by site/build.py.
"""
