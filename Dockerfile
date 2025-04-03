FROM python:3.12-slim

WORKDIR /app/OpenManus

RUN apt-get update && apt-get install -y --no-install-recommends git curl \
    && (command -v uv >/dev/null 2>&1 || pip install --no-cache-dir uv)

COPY . .

RUN uv pip install --system -r requirements.txt

RUN playwright install --with-deps

CMD ["bash"]
