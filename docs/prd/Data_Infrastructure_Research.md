# Point Cloud Data Infrastructure Research
**Prepared by:** Manus AI
**Date:** March 26, 2026

## Executive Summary

This report extends the platform research to cover the underlying data infrastructure required for a modern, scalable point cloud and spatial analytics platform. It evaluates three critical dimensions: **Data Storage Formats** (optimised for cloud streaming), **Data Discovery & Cataloguing** (for metadata and search), and **Data Visualisation Frameworks** (for rendering massive datasets in the browser). The findings are mapped to the platform's goal of achieving parity with enterprise solutions like Georizon.

---

## 1. Cloud-Native Point Cloud Storage

Traditional point cloud formats (LAS, LAZ) are designed for local file systems and require downloading the entire file before processing or viewing. For a web-based platform, data must be stored in "cloud-native" formats that support HTTP range requests, allowing clients to stream only the data they need (spatial subsetting) at the required level of detail (LOD).

### COPC (Cloud Optimized Point Cloud)
**COPC** [1] is the modern standard for cloud-native LiDAR storage. It is essentially a standard LAZ 1.4 file, but the data is internally organised into a clustered octree structure. 
- **Advantage:** It is backward compatible. Any legacy tool that reads LAZ can read a COPC file. However, modern cloud-aware tools (like QGIS, PDAL, and web viewers) can read the COPC VLR (Variable Length Record) header and use HTTP range requests to stream only the necessary chunks directly from an S3 bucket.
- **Platform Fit:** The platform's current tiling worker already uses PDAL to convert incoming data to COPC. This is the correct architectural choice and should be maintained.

### Entwine Point Tile (EPT)
**EPT** [2] is an older octree-based storage format. Unlike COPC, which is a single file, EPT creates a directory structure with thousands of small JSON and LAZ files representing different octree nodes.
- **Advantage:** Highly scalable for massive, multi-terabyte datasets.
- **Disadvantage:** Managing millions of small files on S3 can be slow and expensive. COPC was developed specifically to solve the "too many files" problem of EPT by packing the octree into a single file.

### TileDB
**TileDB** [3] is a universal storage engine based on multi-dimensional arrays. It offers a proprietary (but open-core) format that is highly optimised for complex analytics across point clouds, genomics, and raster data.
- **Platform Fit:** While powerful for complex distributed analytics, TileDB introduces significant architectural overhead. For a platform focused on visualization and standard asset extraction, COPC remains the more practical, standards-based choice.

---

## 2. Geospatial Data Discovery & Cataloguing

As the platform ingests more surveys, users need a way to search, filter, and discover datasets based on spatial extent, time, and derived metadata (e.g., "Show me all surveys in Sydney containing extracted traffic signs").

### SpatioTemporal Asset Catalog (STAC)
**STAC** [4] is the industry standard specification for describing geospatial data. It provides a common JSON-based language that makes data easily indexable and discoverable.
- **Core Components:**
  - **Item:** A GeoJSON feature representing a single asset (e.g., a COPC file) with temporal and spatial metadata.
  - **Collection:** A grouping of related Items (e.g., a specific mobile mapping campaign).
  - **Catalog:** The top-level entry point linking Collections together.
  - **API:** A RESTful API specification (often implemented via `stac-fastapi`) for querying the catalog.
- **Platform Fit:** The platform should adopt the STAC specification for its internal database schema or expose a STAC API endpoint. This allows interoperability with external tools and standardized metadata management.

### STAC Browser & Open Data Cube
- **STAC Browser** [5] (maintained by Radiant Earth) is an open-source React application that provides a user-friendly UI for exploring any STAC-compliant API.
- **Open Data Cube (ODC)** [6] is a powerful framework for indexing and analyzing massive geospatial datasets (primarily raster/satellite data). It is likely overkill for the current platform's focus on discrete point cloud surveys.

---

## 3. 3D Visualisation & Presentation Frameworks

Rendering billions of points in a web browser requires specialized WebGL/WebGPU frameworks that can interpret the octree structure of COPC/EPT files and stream data dynamically based on camera position.

### Potree & Potree-Next
**Potree** [7] is the undisputed industry standard for web-based point cloud rendering. It is an open-source WebGL viewer developed by the Vienna University of Technology.
- **Potree 1.8:** The current stable version. It handles octree traversal, LOD streaming, and rendering. It supports measurement tools, clipping, and profile generation.
- **Potree-Next** [8]: An active rewrite of Potree using **WebGPU**. WebGPU provides compute shaders and lower-level GPU access, allowing for significantly higher point budgets and the integration of new technologies like Gaussian Splatting. 
- **Platform Fit:** The platform's frontend viewer should leverage Potree (or Potree-based wrappers) for the 3D point cloud panel, as it is specifically optimized for this data type.

### CesiumJS & 3D Tiles
**CesiumJS** [9] is a world-class open-source library for creating 3D globes and maps. It relies heavily on the **3D Tiles** standard (developed by Cesium).
- **Advantage:** Excellent for contextualizing point clouds within a global, high-precision geospatial environment (e.g., placing a point cloud exactly on a digital terrain model of the Earth).
- **Disadvantage:** Cesium's native point cloud support is heavily tied to the 3D Tiles format. Rendering raw COPC files directly in Cesium often requires intermediate translation or third-party plugins. The platform currently uses CesiumJS; transitioning to a Potree-Cesium hybrid approach could optimize rendering performance.

### TerriaJS
**TerriaJS** [10] is an open-source spatial digital twin framework built on top of CesiumJS and Leaflet. It is used by major government portals (e.g., Digital Earth Australia).
- **Platform Fit:** TerriaJS excels at federating hundreds of different data sources (WMS, 3D Tiles, GeoJSON) into a single catalog UI. It is highly relevant if the platform aims to become a comprehensive "Digital Twin" portal rather than just a viewer.

### Speckle
**Speckle** [11] is an open-source platform specifically designed for 3D data and BIM collaboration.
- **Platform Fit:** While Speckle has a modern Three.js-based web viewer, it is optimized for structured BIM/CAD geometry rather than massive raw point clouds. However, as the platform implements the `bim-extraction` worker, Speckle's viewer could be highly relevant for presenting the resulting `.ifc` files alongside the point cloud.

---

## Implementation Recommendations

1.  **Storage:** Maintain **COPC** on S3 as the primary storage format. It provides the best balance of backward compatibility and cloud-native streaming performance.
2.  **Discovery:** Implement a **STAC-compliant API** layer on top of the existing Supabase PostgreSQL database to standardize how datasets and extracted assets are queried.
3.  **Visualisation:** For the Tri-Panel Viewer specified in the PRD, integrate **Potree** for the 3D point cloud panel to handle COPC streaming efficiently, while retaining Leaflet for the 2D map and Pannellum for the 360° panoramic imagery.

## References

[1] [COPC – Cloud Optimized Point Cloud Specification](https://copc.io/)
[2] [Entwine Point Tile (EPT) Format](https://entwine.io/entwine-point-tile.html)
[3] [TileDB - The Universal Database](https://tiledb.com/)
[4] [STAC - SpatioTemporal Asset Catalog](https://stacspec.org/)
[5] [Radiant Earth STAC Browser](https://github.com/radiantearth/stac-browser)
[6] [Open Data Cube](https://www.opendatacube.org/)
[7] [Potree WebGL Point Cloud Viewer](https://github.com/potree/potree)
[8] [Potree-Next (WebGPU)](https://github.com/m-schuetz/Potree-Next)
[9] [CesiumJS](https://cesium.com/platform/cesiumjs/)
[10] [TerriaJS Digital Twin Framework](https://terria.com/open-source)
[11] [Speckle 3D Data Platform](https://speckle.systems/)
