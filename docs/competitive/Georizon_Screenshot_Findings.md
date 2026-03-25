# Georizon Screenshot & Research Findings

## Screenshot 1: pasted_file_Cyhj8n_image.png — Georizon Viewer (Railway/Train Corridor)
**Layout**: Three-panel split view
- **Left panel**: 2D map view showing a railway corridor with a red trajectory line overlaid on a top-down point cloud / aerial map. North arrow compass visible.
- **Top-right panel**: 3D point cloud viewer showing the railway station area (white/grey points, RGB colorized). Magenta/pink dots are visible on the point cloud (likely asset markers or annotation points). A blue rectangle highlights a selected area. A "2D / 3D" toggle button is visible in the bottom-right corner of this panel. A north arrow is also visible.
- **Bottom-right panel**: 360° panoramic street-level image of the same railway station. Shows a train, platform, buildings. A toolbar with 6 circular icon buttons is visible at the top: back arrow, info (i), eye/visibility, contrast/brightness, fullscreen/crop, info. A north arrow compass is visible in the bottom-right.
- **Key UX pattern**: Synchronized navigation — clicking a point on the 2D map or 3D viewer jumps the panoramic image to that location. The red line on the 2D map represents the survey trajectory.
- **Magenta dots**: These appear to be asset markers or annotation points that are visible across both the 2D map and the 3D point cloud, indicating cross-view synchronization of vector data.

## Screenshot 2: pasted_file_ZJSBjk_image.png — Georizon Viewer (Urban Street)
**Layout**: Three-panel split view (same as above)
- **Left panel**: 2D top-down point cloud view (greyscale intensity render mode) showing a road/street. A blue triangle (camera position indicator) is visible. Magenta dots (asset markers) are scattered across the scene. "2D / 3D" toggle visible.
- **Top-right panel**: 3D point cloud viewer showing the same street from a perspective angle. Magenta dots visible in the point cloud. Toolbar with icons: up arrow (move), eye (visibility), contrast, fullscreen, info. Text "Find your desired loca..." visible (search bar).
- **Bottom-right panel**: 360° panoramic street-level image showing a Dutch urban street with a delivery truck, buildings, road markings. Magenta dots are overlaid on the panoramic image (these are the same asset markers projected into the image). Toolbar visible.
- **Key UX pattern**: The same magenta asset markers appear simultaneously in all three views (2D map, 3D point cloud, and 360° panorama), demonstrating full cross-view synchronization of vector/asset data.
- **Render mode**: The 2D panel appears to show intensity/greyscale render mode for the point cloud.

## Screenshot 3: pasted_file_XkqtzX_image.png — imajview 5 (Desktop Application)
**Application**: imajview® 5 by Imajing (LocalCImajnet) — a desktop GIS/asset management application
**Layout**: Four-panel layout
- **Top-left (main)**: 360° panoramic image of a railway track with overlaid vector annotations (yellow lines = speed limit zones "TIV VS", green lines = track geometry). A progress/timeline scrubber at the bottom.
- **Top-right**: 2D map panel showing the railway corridor with colored overlays (green = track, orange/red = zones). Aerial imagery base map.
- **Bottom-left (LAYERS panel)**: Layer tree showing:
  - PK (kilometer markers)
  - Tisereal-91998-2023-01-15-160556000_lines
  - Limites de vitesse (speed limits)
  - PR
  - Panneaux prescription (regulatory signs)
  - Streetlight (highlighted/active)
  - Line marker
  - Trottoirs (sidewalks/pavements)
  - Signaux Intersection et priorité (intersection signals)
  - Signaux d'indications (information signs)
  - Panneaux de danger (danger signs)
  - SH Lignes
  - Polyline measure
  - Polygon measure
  - Polygon marker
  - Points
  - Layer controls: search, sort up/down, delete, add, folder, grid, cloud, WMS
- **Bottom-center (OBJECTS panel)**: Shows object list with "Default geometry: POINT" dropdown. Lists POINT 0, POINT 1. Has "Model: Panneaux de danger" dropdown with attribute table (TYPE, NAME, VALUE columns). "fid" = AUTOMATIC, "Registro" = A1a. "CREATE NEW OBJECT" button.
- **Bottom-right (TOOLS panel)**: Tool icons for measurement and editing.
- **Key features visible**: Asset inventory with attribute editing, layer management, WMS integration, vector overlay on panoramic imagery, synchronized map view.

## Screenshot 4: pasted_file_AuMJzu_image.png — imajview 5 (Asset Inspection)
**Application**: imajview® 5 by Imajing (LightPolesPlan3)
**Layout**: Two-panel layout
- **Main panel (left/center)**: 360° panoramic image showing a streetlight pole with ID "2538" visible on the pole. A circular magnification/zoom inset shows "2538" close-up. A progress/timeline scrubber at the bottom.
- **Top-right (LAYERS panel)**: Layer tree showing:
  - PR
  - Line marker
  - Limites de vitesse
  - Candélabre (streetlights)
  - Trottoirs
  - Streetlight (highlighted/active)
  - Signaux d'indications
  - Signaux Intersection et priorité
  - SV Directionelle
  - SH Lignes
  - Polyline measure
  - Polygon measure
  - Polygon marker
  - Panneaux prescription
  - Panneaux de danger
  - tlse-91000-2022-08-18-142421000
  - seq-92999-2023-09-26-124025000
  - points
  - CP.CadastralParcel
  - HR.ORTHOIMAGERY.ORTHOPHOTOS
  - Bing
  - OpenTransportMap
  - Tabs: POSITIONING | MEASURING | OBJECTS | LAYERS
- **Bottom-right (MAP panel)**: 2D mini-map showing the same area with red dots (asset positions) and the selected asset highlighted in green (ID 2538). Blue rectangle = current view extent.
- **OBJECT PROPERTIES popup**: Shows:
  - Title: "Streetlight" / "Route de Labège" / d = 702.414m
  - Attributes: fid=498, type=not known, height=10, NumID Pole=2538
  - Action buttons: delete, locate on map, confirm/save
- **Key features**: Object property inspection with attribute editing, distance measurement (d = 702.414m), asset identification by clicking in panoramic view, synchronized mini-map.

## Screenshot 5: pasted_file_KslALw_image.png — Georizon Architecture Diagram
**Type**: Marketing/architecture diagram
**Content**: Shows the Georizon automated processing pipeline:
- **Input sources**: Multiple drones (various types), mobile mapping vehicle (police/survey car), fixed-wing aircraft, train-mounted scanner
- **Cloud processing pipeline**: INGEST → VALIDATE → HARMONIZE → QA/QC → TILING
- **Uniform output**: API → Viewer (desktop/mobile) → API
- **Three output pillars**:
  1. CONSISTENT QUALITY → Point Clouds (colorized aerial point cloud image)
  2. VENDOR-INDEPENDENT → Imagery (aerial oblique imagery)
  3. DIRECTLY AVAILABLE → Mapping & Analytics (aerial map)
- **Key message**: Vendor-independent, automated, cloud-based processing from multiple sensor types to uniform output

## Summary of Key Features Observed

### Georizon Viewer (web-based, screenshots 1 & 2):
1. **Three-panel synchronized layout**: 2D map + 3D point cloud + 360° panoramic image
2. **2D/3D toggle** in point cloud panel
3. **Trajectory line** visualization on 2D map (red line = survey path)
4. **Asset markers** (magenta dots) synchronized across all three views
5. **Camera position indicator** (blue triangle) on 2D map
6. **North arrow compass** in multiple panels
7. **Panoramic image toolbar**: back navigation, info, visibility, contrast/brightness, fullscreen, info
8. **Search bar** ("Find your desired location...")
9. **Intensity/greyscale render mode** for point cloud (visible in screenshot 2)
10. **RGB colorized point cloud** rendering (visible in screenshot 1)

### imajview 5 (desktop application, screenshots 3 & 4):
1. **Layer management panel** with searchable layer tree, sort, delete, add, folder, grid, WMS buttons
2. **Object/asset inventory** with attribute editing (OBJECTS panel)
3. **Measurement tools**: distance (d = 702.414m), polyline measure, polygon measure
4. **Asset property inspection**: click asset in panorama → object properties popup
5. **WMS layer integration** (WMS button in layers panel)
6. **Multiple base maps**: Bing, OpenTransportMap, HR.ORTHOIMAGERY.ORTHOPHOTOS, CP.CadastralParcel
7. **Timeline/scrubber**: navigate through survey sequence
8. **Circular magnification inset** for close-up inspection of assets
9. **Asset types managed**: streetlights, speed limits, road signs (danger, prescription, indication, intersection), line markers, sidewalks, kilometer markers, track geometry
10. **Tabs**: POSITIONING | MEASURING | OBJECTS | LAYERS
11. **Vector overlay on panoramic imagery**: lines, points drawn over the 360° image
12. **Create new object** functionality (digitization from panoramic view)
13. **Multi-dataset management**: multiple survey datasets visible in layer tree (by date/sequence ID)

### Georizon Processing Pipeline (screenshot 5):
1. Multi-vendor sensor ingestion (drones, vehicles, aircraft, trains)
2. Automated pipeline: INGEST → VALIDATE → HARMONIZE → QA/QC → TILING
3. Output: Point Clouds, Imagery, Mapping & Analytics
4. API access at both input and output stages
