FROM python:3.12-alpine3.23

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY gitea_mirror/ ./gitea_mirror/
RUN pip install --no-cache-dir --no-deps . \
    && adduser -D -u 1000 mirror

USER mirror

ENTRYPOINT ["gitea-mirror"]
CMD ["--help"]
