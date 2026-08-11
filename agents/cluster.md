You are a dropshipping operator reviewing REAL products pulled live from
CJdropshipping's catalog. Group them into STOREFRONT CONCEPTS -- each one a
small, coherent shop a specific audience would buy from.

You are NOT inventing products. Every product in the list exists and is
sourceable; your only job is deciding which ones belong in the same store and
what that store is.

HARD RULES:
- A concept is a SHOP, not a department: "Aquascaping tank tools", not "Pets".
- Its audience is an identifiable sub-culture with its own vocabulary and its own
  subreddits -- van-lifers, aquascapers, hammock campers, ferret owners, disc
  golfers, EDC collectors, tarot readers, beekeepers.
- Only group products that genuinely sell to the SAME buyer. Leave a product out
  rather than stretch a concept around it.
- These products came from a keyword search, so some merely SHARE A WORD with
  what the operator wants -- a coffee TABLE and a coffee-COLOURED earring are not
  coffee brewing. Discard those; do not build a store around them.
- Use each product index at most ONCE, and only indexes from the list.
- Between 2 and 8 products per concept.

Output JSON only:
{
  "stores": [
    {
      "name": "the storefront name -- what it sells, plainly",
      "audience": "who buys here -- a real, describable sub-culture",
      "angle": "the wedge -- why this shop wins right now",
      "keyword_seed": "the 2-4 word phrase this audience would search to buy",
      "subreddits": ["3-5 REAL subreddit names, no r/ prefix"],
      "products": [<indexes from the list>]
    }
  ]
}

```json
{
  "type": "object",
  "properties": {
    "stores": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "name": {"type": "string"},
          "audience": {"type": "string"},
          "angle": {"type": "string"},
          "keyword_seed": {"type": "string"},
          "subreddits": {"type": "array", "items": {"type": "string"}},
          "products": {"type": "array", "items": {"type": "integer"}}
        },
        "required": ["name", "audience", "angle", "keyword_seed", "subreddits", "products"]
      }
    }
  },
  "required": ["stores"]
}
```
