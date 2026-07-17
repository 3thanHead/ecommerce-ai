# storefront-ai — the content-generation service. Pure Python; the LLM work
# happens on the home cluster over HTTP, so a slim base is plenty.
FROM python:3.12-slim

COPY requirements.txt /opt/storefront/requirements.txt
RUN pip install --no-cache-dir -r /opt/storefront/requirements.txt

COPY app/ /opt/storefront/app/
WORKDIR /opt/storefront

EXPOSE 8820
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8820"]
