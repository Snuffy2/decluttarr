FROM python:3.12-slim-bookworm
LABEL org.opencontainers.image.source="https://github.com/Snuffy2/decluttarr"

ENV IS_IN_DOCKER 1

WORKDIR /app

COPY . .
RUN pip install --no-cache-dir -r docker/requirements.txt


CMD ["python", "main.py"]
