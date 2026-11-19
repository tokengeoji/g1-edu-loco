FROM python:3.10-slim-bookworm

ARG INSTALL_REALSENSE=0
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt
RUN if [ "$INSTALL_REALSENSE" = "1" ]; then \
        apt-get update && apt-get install -y --no-install-recommends libusb-1.0-0 libudev1 \
        && rm -rf /var/lib/apt/lists/* \
        && python -m pip install --no-cache-dir --only-binary=:all: pyrealsense2==2.56.5.9235; \
    fi

COPY g1stairs/ ./g1stairs/
