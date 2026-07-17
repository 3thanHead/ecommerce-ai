# The storefront flow, end to end. Generation happens HERE (home cluster,
# free); GitHub Actions only renders + ships what's committed.
#
#   make run        start the generation service (docker, LAN)
#   make shop       the approval REPL (start/pick/approve/theme/...)
#   make export     snapshot approved content -> content/export.json
#   make site       build the static site from the committed snapshot
#   make videos     render product videos (needs images/<sku>.png + ffmpeg)
#   make ship       commit content + push  -> Actions deploys to AWS
URL ?= http://localhost:8820

run:
	docker compose up -d --build

shop:
	python3 cli.py

export:
	curl -sf $(URL)/store/export | python3 -m json.tool > content/export.json
	@echo "content/export.json updated -- review, then 'make ship'"

site:
	python3 site/build.py --file content/export.json
	@echo "open site/dist/index.html"

videos:
	python3 site/media.py --file content/export.json --images images --out videos

ship:
	git add content/
	git commit -m "content: export $$(date +%Y-%m-%d)"
	git push
	@echo "pushed -- GitHub Actions builds + deploys to S3/CloudFront"

.PHONY: run shop export site videos ship
