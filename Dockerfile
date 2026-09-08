FROM python:3.12-slim AS base

ARG WITH_OFFICE=0
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && if [ "$WITH_OFFICE" = "1" ]; then \
      apt-get install -y --no-install-recommends libreoffice-writer libreoffice-impress fonts-liberation; \
    fi \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

COPY app ./app
COPY migrations ./migrations

RUN useradd -r -u 10001 brainxp && chown -R brainxp /srv
USER brainxp

EXPOSE 8000
CMD ["uvicorn","app.main:api","--host","0.0.0.0","--port","8000"]
