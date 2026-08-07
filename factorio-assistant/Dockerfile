ARG BUILD_FROM=debian:bookworm-slim

FROM ${BUILD_FROM}

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    curl \
    jq \
    libasound2 \
    libcurl4 \
    libfontconfig1 \
    libgcc-s1 \
    libgl1 \
    libglib2.0-0 \
    libpulse0 \
    libstdc++6 \
    libx11-6 \
    libxcursor1 \
    libxext6 \
    libxfixes3 \
    libxi6 \
    libxrandr2 \
    libxrender1 \
    python3 \
    python3-pip \
    tar \
    xz-utils \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r /tmp/requirements.txt

ARG FACTORIO_VERSION=2.0.77
RUN curl -sSL "https://www.factorio.com/get-download/${FACTORIO_VERSION}/headless/linux64" -o /tmp/factorio.tar.xz \
    && tar -xJf /tmp/factorio.tar.xz -C /opt \
    && rm /tmp/factorio.tar.xz

RUN mkdir -p /app /factorio /etc/factorio

ARG FACTORIO_DATA_REF=${FACTORIO_VERSION}
RUN mkdir -p /app/factorio-templates /app/factorio-reference/modules \
    && printf '%s\n' "${FACTORIO_DATA_REF}" > /app/factorio-reference/version.txt

# Use the version-pinned repository snapshot included in the build context.
COPY factorio-data/server-settings.example.json /app/factorio-templates/server-settings.example.json
COPY factorio-data/map-gen-settings.example.json /app/factorio-templates/map-gen-settings.example.json
COPY factorio-data/map-settings.example.json /app/factorio-templates/map-settings.example.json
COPY factorio-data/server-adminlist.example.json /app/factorio-templates/server-adminlist.example.json
COPY factorio-data/server-whitelist.example.json /app/factorio-templates/server-whitelist.example.json
COPY factorio-data/changelog.txt /app/factorio-reference/changelog.txt
COPY factorio-data/credits.txt /app/factorio-reference/credits.txt
COPY factorio-data/base/info.json /app/factorio-reference/modules/base.info.json
COPY factorio-data/core/info.json /app/factorio-reference/modules/core.info.json
COPY factorio-data/space-age/info.json /app/factorio-reference/modules/space-age.info.json
COPY factorio-data/quality/info.json /app/factorio-reference/modules/quality.info.json
COPY factorio-data/elevated-rails/info.json /app/factorio-reference/modules/elevated-rails.info.json

COPY config-path.cfg /etc/factorio/config-path.cfg

COPY run.sh /app/run.sh
COPY factorio-assistant-service.py /app/factorio-assistant-service.py
COPY telemetry_models.py /app/telemetry_models.py
COPY catalog_builder.py /app/catalog_builder.py
COPY rcon_client.py /app/rcon_client.py
COPY web_server.py /app/web_server.py
COPY web /app/web
COPY mod /app/factorio_assistant
RUN chmod +x /app/run.sh

WORKDIR /opt/factorio

CMD [ "/app/run.sh" ]