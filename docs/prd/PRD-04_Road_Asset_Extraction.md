# PRD-04: Road Asset Extraction Worker

**Module:** AI Analytics Workers
**Status:** Draft
**Target Audience:** Claude Code

## 1. Overview
The Road Asset Extraction worker is responsible for identifying infrastructure elements (traffic signs, street lights, road markings) from mobile mapping point clouds. The current implementation in `workers/road-assets/src/entrypoint.py` contains structural scaffolding but relies on stub functions for the actual extraction logic. This PRD outlines the requirements to replace these stubs with functional processing pipelines.

## 2. User Stories
- As a GIS manager, I want the platform to automatically extract all traffic signs from a mobile mapping survey so I don't have to digitize them manually.
- As a user, I want the extracted assets to be saved as a standard GeoJSON file that I can download or view in the 2D map.
- As a user, I want the worker to handle datasets even if the advanced AI model fails, by falling back to geometric filtering.

## 3. Architecture & Tools
- **Framework:** Python, executed in a Docker container via Railway.
- **Queue:** Polling the Supabase `processing_jobs` table.
- **Point Cloud Processing:** PDAL (Point Data Abstraction Library) for geometric filtering and DTM generation.
- **AI/ML:** OpenPCDet (PointPillars) for 3D object detection (optional/future), with a robust PDAL-based geometric fallback for immediate implementation.

## 4. Technical Specifications

### 4.1. Replace Stubs in `entrypoint.py`

The current entrypoint imports three functions that do not exist or are stubs:
```python
from pipeline import preprocess_and_classify, extract_road_surface, detect_traffic_signs
```
These must be implemented within the worker.

**1. Preprocessing & Ground Classification**
Implement a PDAL pipeline to classify ground points and normalize height.
```json
[
    "input.laz",
    {
        "type": "filters.smrf",
        "scalar": 1.2,
        "slope": 0.2,
        "threshold": 0.45,
        "window": 16.0
    },
    {
        "type": "filters.hag_nn"
    }
]
```

**2. Geometric Fallback for Traffic Signs**
Instead of a hardcoded dummy sign, implement `detect_traffic_signs` using PDAL's intensity filtering. Traffic signs are highly reflective.
- Filter points by high intensity (`Intensity > 40000` or equivalent, depending on the scanner).
- Filter by height above ground (`HeightAboveGround > 1.5` and `< 4.0`).
- Cluster the remaining points using `scipy.spatial.DBSCAN` or PDAL's `filters.cluster`.
- Calculate the centroid and bounding box of each cluster.

### 4.2. Database & Storage Updates
When the worker completes:
1. Save the extracted assets as a `FeatureCollection` GeoJSON file.
2. Upload the GeoJSON to R2: `assets/{dataset_id}/road_assets.geojson`.
3. Update the `datasets` table:
   ```sql
   UPDATE public.datasets 
   SET road_assets_url = 'https://<r2_public_base>/assets/{id}/road_assets.geojson',
       road_asset_stats = '{"traffic_signs": 42, "light_poles": 12}'::jsonb
   WHERE id = '{dataset_id}';
   ```
4. Update the `processing_jobs` table status to `completed`.

*(Note: The `road_assets_url` and `road_asset_stats` columns must be added to the Supabase schema as per PRD-01).*

## 5. Acceptance Criteria
- [ ] The worker successfully polls a `road_assets` job from Supabase and downloads the corresponding COPC file.
- [ ] The geometric fallback logic successfully identifies at least one highly reflective vertical cluster (simulating a traffic sign) from a test dataset.
- [ ] The worker generates a valid GeoJSON file containing the detected assets.
- [ ] The GeoJSON is uploaded to R2 and the URL is saved to the `datasets` table.
- [ ] The job status is updated to `completed` without errors.
