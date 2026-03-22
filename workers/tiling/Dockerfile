# Tiling Worker — Cloud-Optimised Point Cloud (COPC) converter
# Uses the official PDAL image which bundles PDAL + all drivers (LAS, E57, PLY, etc.)
FROM pdal/pdal:2.8.0

# Install Python 3.11 and pip
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 \
    python3.11-dev \
    python3-pip \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Make python3.11 the default python3
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 \
    && update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy worker source
COPY src/ ./src/

# Health check — verify PDAL is available
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD pdal --version || exit 1

# Run the worker
CMD ["python3", "src/worker.py"]
