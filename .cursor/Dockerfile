FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System packages: Python 3.12 toolchain, git/curl for source and downloads,
# and MongoDB 8.0 (server + shell) from the official MongoDB apt repository.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        gnupg \
        python3 \
        python3-venv \
        python3-pip \
    && curl -fsSL https://www.mongodb.org/static/pgp/server-8.0.asc \
        | gpg -o /usr/share/keyrings/mongodb-server-8.0.gpg --dearmor \
    && echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-8.0.gpg ] https://repo.mongodb.org/apt/ubuntu noble/mongodb-org/8.0 multiverse" \
        > /etc/apt/sources.list.d/mongodb-org-8.0.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends mongodb-org \
    && rm -rf /var/lib/apt/lists/*

# The base image already ships a non-root `ubuntu` user (uid 1000); run as it.
USER ubuntu
