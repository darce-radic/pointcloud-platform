# PRD-05: BIM Extraction Worker

**Module:** AI Analytics Workers
**Status:** Draft
**Target Audience:** Claude Code

## 1. Overview
The BIM (Building Information Modeling) Extraction worker processes indoor or architectural point clouds to automatically detect structural elements (walls, floors, ceilings) and generate standard CAD/BIM files. The current implementation in `workers/bim-extraction/src/entrypoint.py` is a mock that generates empty `.ifc` and `.dxf` files. This PRD defines the requirements to implement a functional scan-to-BIM pipeline.

## 2. User Stories
- As an architect, I want to upload a laser scan of a building interior and automatically get a 3D IFC model of the walls and floors.
- As a CAD draftsperson, I want to download a 2D DXF floor plan generated from the point cloud so I don't have to trace it manually.
- As a user, I want the extracted BIM elements to be viewable in the platform's 3D viewer alongside the original point cloud.

## 3. Architecture & Tools
- **Framework:** Python, executed in a Docker container via Railway.
- **Queue:** Polling the Supabase `processing_jobs` table.
- **Point Cloud Segmentation:** PDAL and NumPy/SciPy for planar region growing and RANSAC plane fitting.
- **BIM Generation:** `IfcOpenShell` (Python library for creating Industry Foundation Classes `IFC4` files).
- **CAD Generation:** `ezdxf` (Python library for creating 2D `.dxf` floor plans).

## 4. Technical Specifications

### 4.1. Replace Stubs in `entrypoint.py`

The current entrypoint contains three mock functions: `_heuristic_segmentation`, `generate_ifc`, and `generate_dxf`.

**1. Point Cloud Segmentation (`_heuristic_segmentation`)**
- Use PDAL to downsample the cloud (`filters.voxelcentroidnearestneighbor`).
- Use PDAL's `filters.smrf` to separate the floor slab from the rest of the cloud.
- For the non-floor points, implement a simple RANSAC algorithm or use PDAL's `filters.cluster` and `filters.planefit` to identify vertical planar surfaces (walls).
- Output: A list of dictionaries representing detected planes, including `type` (wall/floor), `centroid`, `normal_vector`, `length`, `height`, and `width`.

**2. IFC Generation (`generate_ifc`)**
- Initialize a new `IFC4` project using `ifcopenshell`.
- Create a building context (`IfcProject`, `IfcSite`, `IfcBuilding`, `IfcBuildingStorey`).
- For each detected plane in the segmentation step:
  - If `type == 'floor'`, create an `IfcSlab`.
  - If `type == 'wall'`, create an `IfcWallStandardCase`.
  - Use the plane's centroid and dimensions to set the IFC geometry (extruded area solids).
- Write the output to a temporary `.ifc` file.

**3. DXF Generation (`generate_dxf`)**
- Initialize a new DXF document using `ezdxf`.
- For each detected `wall` plane, extract the 2D bounding box (ignoring the Z axis).
- Draw lines or polylines representing the walls on a specific layer (e.g., `WALLS`).
- Write the output to a temporary `.dxf` file.

### 4.2. Database & Storage Updates
When the worker completes:
1. Upload the generated files to R2:
   - `assets/{dataset_id}/model.ifc`
   - `assets/{dataset_id}/floorplan.dxf`
   - `assets/{dataset_id}/segments.json` (raw plane data for the web viewer)
2. Update the `datasets` table:
   ```sql
   UPDATE public.datasets 
   SET ifc_url = 'https://<r2_public_base>/assets/{id}/model.ifc',
       dxf_url = 'https://<r2_public_base>/assets/{id}/floorplan.dxf',
       segments_url = 'https://<r2_public_base>/assets/{id}/segments.json',
       bim_stats = '{"walls": 14, "slabs": 1}'::jsonb
   WHERE id = '{dataset_id}';
   ```
3. Update the `processing_jobs` table status to `completed`.

*(Note: The new columns must be added to the Supabase schema as per PRD-01).*

## 5. Acceptance Criteria
- [ ] The worker successfully polls a `bim_extraction` job and downloads the COPC file.
- [ ] The segmentation logic identifies at least one floor slab and one vertical wall from a test indoor dataset.
- [ ] The worker generates a valid `.ifc` file that can be opened in a standard viewer (e.g., BIMvision or Speckle).
- [ ] The worker generates a valid `.dxf` file that can be opened in AutoCAD or QGIS.
- [ ] The files are uploaded to R2 and the URLs are saved to the `datasets` table.
