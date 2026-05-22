FROM python:3.11-slim

ARG TRIVY_VERSION=0.70.0

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV INTRUST_STORAGE_DIR=storage
ENV DATABASE_TYPE=sqlite
ENV PATH="/app/bin:${PATH}"

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl tar \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN mkdir -p /app/bin \
    && curl -fsSL "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_Linux-32bit.tar.gz" \
    | tar -xz -C /app/bin trivy \
    && chmod +x /app/bin/trivy

COPY . .
RUN mkdir -p /app/storage /app/logs

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]