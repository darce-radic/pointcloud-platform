# Tiling Worker — Cloud-Optimised Point Cloud (COPC) converter
# Uses Miniconda3 as base, installs PDAL via conda-forge and Python packages via pip
# This avoids the conda Python path conflict in the pdal/pdal image
FROM continuumio/miniconda3:24.1.2-0

# Install PDAL and its dependencies via conda-forge (includes all drivers: LAS, E57, PLY, etc.)
RUN conda install -n base -c conda-forge pdal python-pdal python=3.11 -y && \
    conda clean -afy

WORKDIR /app

# Install Python dependencies via pip (uses the conda base Python 3.11)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy worker source
COPY src/ ./src/

# Health check — verify PDAL is available
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD pdal --version || exit 1

# Run the worker using the conda base Python
CMD ["python", "-u", "src/worker.py"]
