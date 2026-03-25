# PRD-03: Tri-Panel Synchronized Viewer (360°, 3D, 2D)

**Module:** Frontend Presentation
**Status:** Draft
**Target Audience:** Claude Code

## 1. Overview
The core differentiator of the platform is its ability to present data exactly as it was captured and processed. This module upgrades the existing viewer from a dual-panel layout (3D + 2D) to a Georizon-style **Tri-Panel Synchronized Viewer**. It adds a 360° panoramic image panel and ensures that navigation and asset selection in any one panel instantly updates the other two.

## 2. User Stories
- As a user, I want to see the 3D point cloud, the 2D map, and the 360° panoramic street view simultaneously on one screen.
- As a user, when I click on a traffic sign in the 360° image, I want the 3D viewer and 2D map to immediately center on that exact traffic sign.
- As a user, I want to see the trajectory of the mobile mapping vehicle on the 2D map so I know where data was captured.
- As a user, I want to adjust the brightness and contrast of the 360° image to see details in shadows.

## 3. Architecture & Components
The viewer is a React component built on Next.js, utilizing three distinct rendering libraries synchronized via a shared Zustand state store.

| Panel | Technology | Purpose |
| :--- | :--- | :--- |
| **3D Viewer** | CesiumJS (current) or Potree | Renders the COPC point cloud streaming from R2. Displays 3D bounding boxes of extracted assets. |
| **2D Map** | Leaflet (current) | Renders the base map, survey trajectory line, and 2D points for extracted assets. |
| **360° Image** | Pannellum (new) | Renders equirectangular panoramic images. Displays clickable SVG markers for extracted assets. |
| **State** | Zustand | Manages `cameraPosition`, `selectedAssetId`, and `currentImageId`. |

## 4. Technical Specifications

### 4.1. Database Schema Additions
To support the 360° viewer, the database needs a table to store the panoramic image metadata and a spatial index to find the nearest image to a given point.

```sql
CREATE TABLE IF NOT EXISTS public.panoramic_images (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  dataset_id UUID NOT NULL REFERENCES public.datasets(id) ON DELETE CASCADE,
  image_url TEXT NOT NULL,
  capture_time TIMESTAMPTZ,
  geom geometry(PointZ, 4326) NOT NULL,
  heading FLOAT, -- Camera heading in degrees (0-360)
  pitch FLOAT,
  roll FLOAT
);

CREATE INDEX IF NOT EXISTS pano_geom_idx ON public.panoramic_images USING GIST (geom);
```

### 4.2. API Endpoints (`api/routers/viewer.py`)
**`GET /datasets/{id}/images/nearest`**
- **Query Params:** `lat`, `lon`
- **Action:** Uses PostGIS `<->` operator to find the closest panoramic image to the requested coordinates.
- **Returns:** `{ "id": "uuid", "image_url": "...", "heading": 45.2, "distance_meters": 1.2 }`

**`GET /datasets/{id}/trajectory`**
- **Action:** Generates a GeoJSON LineString from the ordered `panoramic_images.geom` points.
- **Returns:** GeoJSON FeatureCollection.

### 4.3. Frontend Implementation (`frontend/components/viewer/`)

**1. `ViewerStore.ts` (Zustand)**
Create a central state manager to handle cross-panel synchronization.
```typescript
interface ViewerState {
  cameraPosition: [number, number, number] | null; // [lon, lat, height]
  selectedAssetId: string | null;
  currentImageId: string | null;
  setCameraPosition: (pos: [number, number, number]) => void;
  setSelectedAssetId: (id: string | null) => void;
  setCurrentImageId: (id: string | null) => void;
}
```

**2. `PanoPanel.tsx` (New Component)**
- Implement using the `pannellum-react` wrapper.
- **Props:** `imageUrl`, `heading`, `pitch`, `assets` (array of markers).
- **Behavior:** When an asset marker is clicked, call `setSelectedAssetId(asset.id)`. When the user pans the image, update the directional cone on the 2D map.

**3. `MapPanel.tsx` (Update)**
- Add a `trajectoryGeoJSON` prop to render the vehicle path as a blue polyline.
- Add a directional cone (using a custom Leaflet DivIcon) representing the current `cameraPosition` and `heading` from the Zustand store.
- Render extracted assets as magenta circle markers. Clicking a marker calls `setSelectedAssetId`.

**4. `CesiumViewer.tsx` (Update)**
- Subscribe to `selectedAssetId`. When it changes, use `viewer.camera.flyToBoundingSphere` to center the 3D view on the asset.
- Replace the hardcoded Sydney fallback (`151.2093, -33.8688`) with the centroid of the dataset's `bbox_geom`.

**5. `ViewerClient.tsx` (Update)**
- Refactor the layout from a 2-column grid to a 3-panel CSS Grid layout (e.g., Map top-left, Pano bottom-left, 3D right-half).

## 5. Acceptance Criteria
- [ ] The viewer displays three distinct panels: Map, 3D, and 360° Image.
- [ ] Clicking a magenta asset marker in the 2D map automatically loads the nearest 360° image in the Pano panel and flies the 3D camera to the asset.
- [ ] The 2D map displays a continuous trajectory line representing the survey path.
- [ ] The 2D map displays a directional cone indicating the current viewing angle of the 360° image panel.
- [ ] If no dataset or COPC URL is provided, the viewer handles the empty state gracefully without flying to hardcoded fallback coordinates.
