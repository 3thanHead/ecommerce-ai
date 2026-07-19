# storefront-ai

An AI-run storefront where **generation is local and free, hosting is AWS
and static**. The approval-gated flow (niche → brand → catalog → assembly →
marketing) runs against the home LLM cluster; every stage waits for your
`pick` / `approve` / `revise` before anything routes downstream. GitHub
Actions never calls a model — it renders committed content and ships it to
S3/CloudFront.

```
you (REPL/chat) ──► generation service ──► home LLM cluster   (LAN, free)
                        │ approvals
                        ▼
                 content/export.json  ── git push ──►  Actions: build → S3/CloudFront
```

## The flow

```bash
cp .env.example .env         # point LLM_BASE_URL at the cluster master (or local Ollama)
make run                     # generation service on :8820
make chat                    # the chat console at :8820/ — shop agent + plain chat
make shop                    # the REPL: start <seed> → pick <n> → approve …
                             #   preview live at :8820/shop and :8820/blog
make export                  # approved content → content/export.json
make site                    # render locally, open site/dist/index.html
make videos                  # ffmpeg product videos (images/<sku>.png needed)
make ship                    # commit content + push → Actions deploys
```

Stages live today: **niche** (candidates, re-pickable — switching resets
downstream), **catalog** (bulk LangGraph node), **assembly** (about/FAQ/
policy pages), **marketing** (per-product hooks/captions/scripts +
calendar). **brand** is still a stub that passes through. The storefront
uses one clean built-in template (`app/agents/shop/render.py`); selectable
themes are a later addition.

## Chat console

`make run` also serves a browser chat console at **http://localhost:8820/** — the
same streaming UI as iot_ai's chat app, re-themed for the shop. The **shop** agent
is selected by default, so you drive the whole approval ladder (`start <seed>`,
`pick <n>`, `approve`, `revise …`) in chat and watch each stage generate live; its
activity feed shows the current stage as a chip. Flip the agent picker to *Chat
(plain model)* to talk to the raw model instead.

It talks to whatever `LLM_BASE_URL` names, so the **same console runs against this
machine's own Ollama or the home cluster interchangeably** — no code change, just the
env var (matching iot_ai's `edge up --local` vs cluster). Agents run in-process, so
there's no second service to start.

## Layout

```
app/            the generation service (FastAPI, same event protocol as iot_ai's agents)
  agents/       venture ladder, prompts (*.md), shop machinery, render.py template
  api/          /api/agents, /store/export, live LAN preview (/shop, /blog), chat console (/)
  static/       the chat console page (single self-contained index.html)
site/build.py   export.json -> static site (same template as the live preview)
site/media.py   marketing plans -> rotating product videos (pure ffmpeg)
content/        the approved snapshots — the only thing Actions needs
infra/          Terraform: S3 + CloudFront (OAC) + the GitHub OIDC deploy role
cli.py          the approval REPL (`make shop`)
```

## One-time AWS + GitHub setup

1. AWS account, MFA, an admin CLI key, `aws configure` (region `us-east-1`).
2. ```bash
   cd infra && terraform init
   terraform apply -var bucket_name=<globally-unique> -var github_repo=3thanHead/storefront-ai
   ```
3. Hand the outputs to Actions (no AWS keys stored anywhere — OIDC):
   ```bash
   gh variable set AWS_DEPLOY_ROLE_ARN --body "$(terraform -chdir=infra output -raw deploy_role_arn)"
   gh variable set SITE_BUCKET         --body "$(terraform -chdir=infra output -raw bucket)"
   gh variable set CF_DIST_ID          --body "$(terraform -chdir=infra output -raw distribution_id)"
   ```
4. Put the `site_url` output into `.env` as `BLOG_BASE_URL` so agent-minted
   links point at the live site.

## Relationship to iot_ai

The home cluster (HAProxy + Ollama nodes + `edge` tooling) lives in and is
operated from the `iot_ai` monorepo; this repo consumes it purely as an HTTP
endpoint (`LLM_BASE_URL`) — free local inference, no shared code. The
fleet's image node (RTX box, ComfyUI/SD) arrives the same way via
`IMAGE_BASE_URL`.
