# BIM Extraction Worker — Scan-to-BIM pipeline
# Uses Miniconda3 as base for PDAL + conda-forge dependencies
FROM continuumio/miniconda3:24.1.2-0

# Install PDAL, ifcopenshell, numpy, scipy, shapely and Python via conda-forge
RUN conda install -n base -c conda-forge \
    pdal python-pdal python=3.11 ifcopenshell numpy scipy shapely -y && \
    conda clean -afy

WORKDIR /app

# Install Python dependencies via pip
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy worker source
COPY src/ ./src/

# Health check — verify PDAL is available
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD pdal --version || exit 1

# Run the worker
CMD ["python", "-u", "src/entrypoint.py"]
