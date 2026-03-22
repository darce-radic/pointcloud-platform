# Tiling Worker — Cloud-Optimised Point Cloud (COPC) converter
# Uses the official PDAL image which bundles PDAL + all drivers (LAS, E57, PLY, etc.)
# NOTE: pdal/pdal is Miniconda-based — use conda to install Python, not apt
FROM pdal/pdal:2.8.0

# Install Python 3.11 and pip via conda (the pdal image uses Miniconda, not apt)
RUN conda install -n base -c conda-forge python=3.11 pip -y && \
    conda clean -afy

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy worker source
COPY src/ ./src/

# Health check — verify PDAL is available
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD pdal --version || exit 1

# Run the worker
CMD ["python", "-u", "src/worker.py"]
