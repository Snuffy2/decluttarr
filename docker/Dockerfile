FROM python:3.11-slim-bookworm
LABEL org.opencontainers.image.source="https://github.com/Snuffy2/decluttarr"

ENV IS_IN_DOCKER 1

WORKDIR /app

COPY . .
RUN pip install --upgrade pip
RUN apt-get update && apt-get upgrade -y
RUN apt-get install -y git curl
RUN pip install --no-cache-dir -r docker/requirements.txt


CMD ["python", "main.py"]
