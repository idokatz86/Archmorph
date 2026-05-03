# Archmorph Diagram Export Specification

> Implementation-ready specification for presentation-grade architecture diagram exports.
> Target audience: developers implementing the export pipeline.
> Date: 2026-03-17 | Version: 2.0

> May 2026 update: the customer-facing Architecture Package is the primary website export. It exposes HTML plus standalone target/DR SVG render targets. Classic editable diagram formats remain legacy/internal API capabilities only and are no longer visible in the customer export UI.

> May 2026 security update (#671): generated artifact export/download endpoints require a caller-held `X-Export-Capability` token scoped to the requested analysis. Tokens are opaque, one-time-use, expire after 15 minutes by default, and rotate after every successful export.

---

## 1. Input Data Contract

Every export consumes a unified `ExportPayload` built from the analysis session:

```python
ExportPayload = {
    # Identity
    "title": str,                    # "Contoso AWS → Azure Migration"
    "project_name": str,             # customer-provided or generated
    "version": str,                  # "1.0-draft", auto-incremented
    "generated_at": str,             # ISO-8601 timestamp
    "source_provider": str,          # "aws" | "gcp"

    # Architecture data
    "zones": List[Zone],             # see samples.py schema
    "mappings": List[ServiceMapping], # source→azure with confidence, effort, gaps
    "service_connections": List[Connection],
    "cost_estimate": Optional[CostEstimate],

    # HLD metadata (for header/footer)
    "architecture_style": str,       # "hub-spoke", "3-tier", "microservices"
    "primary_region": str,           # "West Europe"
    "dr_region": Optional[str],      # "North Europe"
    "compliance_frameworks": List[str],  # ["SOC 2", "GDPR"]
}
```

Architecture Package exports additionally consume `customer_intent` and optional `guided_answers` from the guided-question flow. `customer_intent` is the compact narration profile used for talking points and limitations; `guided_answers` preserves the raw user-provided answer payload when it is needed for review.

## 1.1 Export Families

| Family | Formats | Primary Consumer | Notes |
|--------|---------|------------------|-------|
| Architecture Package | `format=html` or `format=svg` with `diagram=primary` or `diagram=dr` | Customer, CTO, architecture review | Polished review package with Azure topology views, talking points, limitations, and namespaced inline SVG assets. This is the only visible website diagram export family. |
| Classic Diagram Export | `excalidraw`, `drawio`, `vsdx` | Internal/legacy engineers editing diagrams in external tools | Legacy renderer contract retained for compatibility only; do not surface these options in the customer website export UI. |

## 1.2 Capability Token Boundary

The export/download routes are a bearer-capability boundary, separate from the general API key/admin model. This applies to classic diagram exports, architecture-package exports, HLD exports, and PDF report downloads.

| Requirement | Contract |
| --- | --- |
| Header | `X-Export-Capability: <opaque-token>` |
| Scope | `artifact:export` and exactly one `diagram_id` |
| Entropy | `secrets.token_urlsafe(32)` for export capabilities; diagram IDs use at least `secrets.token_urlsafe(16)` |
| Storage | Server stores SHA-256 token digest only, never the raw token |
| Expiry | Default 15 minutes (`EXPORT_CAPABILITY_TTL_SECONDS`) |
| Replay | Token is consumed when validated; reuse returns 401 |
| Rotation | Successful export responses include a fresh `export_capability` and `export_capability_expires_in` |
| Local/dev | `ARCHMORPH_EXPORT_CAPABILITY_REQUIRED=false` may be used for local scripts; production/staging fail closed |
| Audit | Emit issuance/validation/denial events without raw token values |

Pitfalls: do not put product-flow tokens in URLs, do not persist capabilities in analysis artifacts/history, do not make tokens multi-use for bulk export, and do not treat a guessed `diagram_id` as sufficient authorization.

---

## 2. Page/Layer Structure (All Formats)

Each export produces a **multi-page/multi-tab** diagram. Not a single flat canvas.

### Page 1: "Migration Overview" (the hero page)

**Purpose:** CTO/steering committee view. Printed at A3 for boardroom wall. This is the page that goes into the SOW.

**Contains:**
- Source architecture on the LEFT (faded/ghosted at 40% opacity)
- Azure target architecture on the RIGHT (full color)
- Migration arrows from source→target connecting equivalent services
- Confidence traffic lights on each target service
- Zone/boundary groupings with subnet labels
- Title cartouche (top-left)
- Legend (bottom-right)
- Disclaimer footer

### Page 2: "Azure Target Architecture" (clean target state)

**Purpose:** The "to-be" architecture without source clutter. Goes into technical design docs and Azure portal resource group planning.

**Contains:**
- Azure services only (no source references)
- Full connection topology with protocols and port numbers
- Zone boundaries with VNet/Subnet CIDR placeholders
- Service tiers and SKUs annotated
- Cost callouts per zone (monthly estimate)

### Page 3: "Service Mapping Detail"

**Purpose:** Migration team reference. Maps every source service to its Azure target with metadata.

**Contains:**
- Table-style layout (one row per mapping)
- Columns: Source Service | Azure Target | Confidence | Migration Effort | Feature Gaps | Est. Monthly Cost
- Color-coded by confidence
- Grouped by category (Compute, Database, Networking, Security, etc.)

### Page 4: "Connection Topology" (optional, for complex architectures)

**Purpose:** Network team reference. Shows all connections with protocol detail.

**Contains:**
- Every `service_connection` as a labeled edge
- Connection type color coding
- Protocol + port labels on each edge
- Security zone boundaries
- Firewall/NSG inspection points highlighted

---

## 3. Service Shape Specification

### 3.1 Shape Anatomy

Each service node is a **compound shape** with this structure:

```
┌─────────────────────────────────────────┐
│ [Azure Icon]  Service Name              │  ← 14pt, Segoe UI Semibold
│               source: EC2 → VM          │  ← 10pt, italic, #64748B
│               ●●●○○ 85% confidence      │  ← traffic light dots
│               $142/mo | Standard_D4s_v3 │  ← 9pt, #94A3B8
└─────────────────────────────────────────┘
```

### 3.2 Shape Dimensions

| Property | Excalidraw (px) | Draw.io (px) | Visio (inches) |
|----------|----------------|--------------|----------------|
| Width | 280 | 280 | 3.0 |
| Height | 80 | 80 | 0.85 |
| Icon size | 36×36 | 40×40 | 0.4×0.4 |
| Corner radius | 8 | 8 | 0.08 |
| Border width | 2 | 2 | 0.02 |
| Inner padding | 8 | 8 | 0.08 |

### 3.3 Icon Sources

| Format | Icon Source | Fallback |
|--------|-----------|----------|
| Excalidraw | SVG embedded as `image` element via `files` dict (from `icons.registry`) | Colored rectangle with service initial |
| Draw.io | `shape=image;image=data:image/svg+xml;base64,...` OR `shape=mxgraph.azure.*` stencils | Generic cloud shape `mxgraph.azure.general` |
| Visio | Azure Cloud Design stencils (VSSX) master shapes | Rectangle with "Azure" prefix label |

**Icon registry priority:**
1. `icons.registry.resolve_icon(name, provider="azure")` → SVG data URI
2. `assets/diagram_stencils.json` → Draw.io/Visio stencil IDs
3. Generic fallback shape

### 3.4 Confidence Visual Encoding

**Traffic light system on service border + badge:**

| Confidence | Border Color | Badge BG | Badge Text | Dot Pattern |
|-----------|-------------|----------|-----------|-------------|
| ≥ 0.85 (High) | `#22C55E` (green) | `#DCFCE7` | `#166534` | ●●●●● |
| 0.70–0.84 (Medium) | `#F59E0B` (amber) | `#FEF3C7` | `#92400E` | ●●●○○ |
| < 0.70 (Low) | `#EF4444` (red) | `#FEE2E2` | `#991B1B` | ●○○○○ |

**Implementation note:** The border color is the primary indicator. The confidence badge is a small rounded rect inside the shape at bottom-right. Both must be present for accessibility (color + text redundancy).

### 3.5 Migration Effort Badge (Page 1 only)

Small pill badge below or beside each target service:

| Effort | Badge Color | Label |
|--------|------------|-------|
| Low | `#DCFCE7` bg, `#166534` text | "Lift & Shift" |
| Medium | `#FEF3C7` bg, `#92400E` text | "Replatform" |
| High | `#FEE2E2` bg, `#991B1B` text | "Refactor" |

---

## 4. Connection/Edge Specification

### 4.1 Connection Type Styling

Each `service_connection` has a `type` field. Style by type:

| Connection Type | Line Color | Line Style | Line Width | Arrow |
|----------------|-----------|-----------|-----------|-------|
| `traffic` | `#0078D4` (Azure blue) | Solid | 2px | Single arrow → |
| `database` | `#8B5CF6` (purple) | Solid | 2px | Single arrow → |
| `auth` | `#F59E0B` (amber) | Dashed (8,4) | 2px | Single arrow → |
| `control` | `#64748B` (gray) | Dotted (2,4) | 1.5px | Single arrow → |
| `security` | `#EF4444` (red) | Dashed (4,4) | 2px | Double arrow ↔ |
| `storage` | `#06B6D4` (cyan) | Solid | 1.5px | Single arrow → |
| `inspection` | `#EF4444` (red) | Dashed (12,4) | 2px | Double arrow ↔ |
| `metrics` / `monitoring` | `#64748B` (gray) | Dotted (2,6) | 1px | Single arrow → |
| `backup` | `#06B6D4` (cyan) | Dashed (4,4) | 1px | Single arrow → |

### 4.2 Edge Labels

Every connection edge must display a label. Format: `{protocol}` (e.g., "HTTPS", "TCP/5432", "gRPC").

| Property | Value |
|----------|-------|
| Font | 10pt Segoe UI |
| Color | Same as line color |
| Position | Midpoint of edge, offset 8px above the line |
| Background | White with 80% opacity (so label is readable over crossing lines) |

### 4.3 Edge Routing

| Format | Routing Style |
|--------|--------------|
| Excalidraw | Straight lines with arrow endpoints. Points array: `[[0,0], [dx,dy]]` |
| Draw.io | `edgeStyle=orthogonalEdgeStyle;rounded=1;` — orthogonal with rounded corners |
| Visio | Dynamic connector with auto-routing. Use `RoutingStyle=2` (center-to-center) |

### 4.4 Migration Arrows (Page 1 only)

Source→Target migration arrows (distinct from topology connections):

| Property | Value |
|----------|-------|
| Color | `#22C55E` (green) for high confidence, `#F59E0B` for medium, `#EF4444` for low |
| Style | Dashed (12, 6) |
| Width | 3px |
| Arrow | Fat arrow head (triangle, filled) |
| Label | `migrate` or `replatform` or `refactor` based on effort |

---

## 5. Zone/Boundary Specification

### 5.1 Zone Visual Properties

Zones represent VPCs, subnets, resource groups, or logical groupings.

| Property | Value |
|----------|-------|
| Shape | Rounded rectangle, radius 12px (Excalidraw), 12 (Draw.io), 0.12in (Visio) |
| Border | 2px solid `#0078D4` |
| Fill | Pastel zone color at 15% opacity (see palette below) |
| Header | Zone name in 16pt Segoe UI Semibold, `#0078D4` |
| Subheader | Zone description/role in 11pt, `#64748B` |

### 5.2 Zone Color Palette (cycled by zone index)

```python
ZONE_PALETTE = [
    {"fill": "#E3F2FD", "border": "#1565C0", "label": "Blue"},    # Network zones
    {"fill": "#E8F5E9", "border": "#2E7D32", "label": "Green"},   # Compute zones
    {"fill": "#FFF3E0", "border": "#E65100", "label": "Orange"},  # Data zones
    {"fill": "#F3E5F5", "border": "#6A1B9A", "label": "Purple"},  # Security zones
    {"fill": "#E0F7FA", "border": "#00838F", "label": "Cyan"},    # Integration zones
    {"fill": "#FBE9E7", "border": "#BF360C", "label": "Red"},     # Edge zones
    {"fill": "#F1F8E9", "border": "#558B2F", "label": "Lime"},    # Monitoring zones
    {"fill": "#EDE7F6", "border": "#4527A0", "label": "Indigo"},  # AI/ML zones
]
```

### 5.3 Cloud Boundary (outermost container)

| Property | Value |
|----------|-------|
| Shape | Rounded rectangle enclosing all zones |
| Border | 2px dashed `#0078D4`, dash pattern (8,4) |
| Fill | None (transparent) |
| Label | "Microsoft Azure" at top-left inside boundary, 14pt, `#0078D4` |
| Logo | Azure logo icon at top-left beside label (when icon registry resolves it) |

### 5.4 Source Cloud Boundary (Page 1 only)

| Property | Value |
|----------|-------|
| Opacity | 40% on all elements |
| Border | 2px dashed, provider-specific color (`#FF9900` AWS, `#4285F4` GCP) |
| Label | "AWS" or "GCP" with provider logo |
| Position | Left side of canvas |

---

## 6. Layout Engine Rules

### 6.1 General Layout

| Rule | Specification |
|------|--------------|
| Canvas size | A3 landscape (420×297mm / 16.54×11.69in / 4960×3508px at 300dpi) |
| Margin | 60px all sides (Excalidraw/Draw.io), 0.6in (Visio) |
| Grid | 10px snap (Draw.io), 20px (Excalidraw), 0.125in (Visio) |
| Max zones per row | 4 |
| Zone gap | 60px horizontal, 80px vertical |
| Service gap within zone | 52px vertical |

### 6.2 Topology-Aware Layout

The layout must respect the `architecture_style`:

| Architecture Style | Layout Pattern |
|-------------------|---------------|
| `hub-spoke` | Hub zone centered. Spoke zones arranged radially. Transit/Gateway at hub center. |
| `3-tier` | Top row: Edge/CDN/LB. Middle row: Compute/App. Bottom row: Database/Storage. Left-to-right data flow. |
| `microservices` | Grid layout. API Gateway at top. Service mesh in center. Databases at bottom. |
| `serverless` | Event flow left-to-right. Triggers on left, Functions in middle, Storage/DB on right. |
| `data-pipeline` | Horizontal flow: Ingestion → Processing → Storage → Analytics → Visualization. |

### 6.3 Service Ordering Within Zones

1. Load balancers / entry points at TOP of zone
2. Compute / application services in MIDDLE
3. Databases / storage at BOTTOM of zone
4. Security / monitoring services on the RIGHT side

### 6.4 Z-Order

```
Bottom:  Cloud boundary
         Zone backgrounds
         Connection edges (behind service shapes)
Top:     Service shapes
         Edge labels
         Badges
         Legend
         Title cartouche
```

---

## 7. Legend Specification

### 7.1 Legend Position

Bottom-right corner of the canvas, outside the cloud boundary. Fixed 320×220px (Excalidraw/Draw.io) or 3.5×2.3in (Visio).

### 7.2 Legend Contents

```
┌─────────────────────────────────────────┐
│  LEGEND                                 │
│                                         │
│  Confidence                             │
│  ■ High (≥85%)    ■ Medium (70-84%)     │
│  ■ Low (<70%)                           │
│                                         │
│  Connection Types                       │
│  ── Traffic (Azure Blue)                │
│  ── Database (Purple)                   │
│  -- Auth (Amber, dashed)                │
│  ·· Control (Gray, dotted)              │
│  -- Security (Red, dashed)              │
│  ── Storage (Cyan)                      │
│                                         │
│  Migration Effort (Page 1 only)         │
│  [Lift & Shift] [Replatform] [Refactor] │
└─────────────────────────────────────────┘
```

### 7.3 Legend Styling

| Property | Value |
|----------|-------|
| Background | `#FFFFFF` with `#E2E8F0` border, 1px solid |
| Corner radius | 8px |
| Title | "LEGEND" — 12pt Segoe UI Bold, `#0F172A` |
| Items | 10pt Segoe UI, `#334155` |
| Color swatches | 12×12px filled squares beside each label |
| Line samples | 30px line segments in the corresponding style |

---

## 8. Title Cartouche / Header Block

Top-left of every page:

```
┌──────────────────────────────────────────────────────┐
│  Contoso AWS → Azure Migration                       │  ← 24pt, Segoe UI Bold, #0078D4
│  Architecture: Hub & Spoke | Region: West Europe     │  ← 12pt, #64748B
│  Generated: 2026-03-17 | v1.0-draft | Archmorph      │  ← 10pt, #94A3B8
│  DRAFT — Subject to technical validation             │  ← 10pt, RED, italic
└──────────────────────────────────────────────────────┘
```

| Property | Value |
|----------|-------|
| Position | Top-left, inside margin |
| Background | None (text only) |
| Project name | 24pt Segoe UI Bold, `#0078D4` |
| Metadata line | 12pt Segoe UI, `#64748B` |
| Generator line | 10pt Segoe UI, `#94A3B8` |
| Disclaimer | 10pt Segoe UI Italic, `#EF4444` — always present unless `version` contains "final" |

---

## 9. Footer / Disclaimer

Bottom-center of every page:

```
CONFIDENTIAL — Prepared by Archmorph v{version} — Not a commitment to Azure costs or SLAs
© {year} {project_name} — Page {n} of {total}
```

| Property | Value |
|----------|-------|
| Font | 8pt Segoe UI, `#94A3B8` |
| Position | Bottom-center, 20px from bottom edge |
| Visibility | All pages |

---

## 10. Format-Specific Implementation Details

### 10.1 Excalidraw (.excalidraw)

**File structure:** Single JSON file with `elements`, `appState`, `files` keys.

| Aspect | Implementation |
|--------|---------------|
| Multi-page | Excalidraw does NOT support pages. Use **frame elements** (`type: "frame"`) to simulate pages. Each "page" is a frame placed side-by-side at 5000px intervals on the X axis. |
| Icons | Embedded as `type: "image"` elements. SVG data URIs stored in `files` dict keyed by SHA-256 hash of service name. |
| Zones | `type: "rectangle"` with `fillStyle: "solid"`, pastel background, `roughness: 0`. |
| Connections | `type: "arrow"` with `points` array. `strokeStyle` maps: solid→"solid", dashed→custom `strokeLineDash`. |
| Grouping | Use `groupIds` array on elements to group zone contents. |
| Font | `fontFamily: 1` (Virgil/handwritten is default — override to `fontFamily: 3` for "Cascadia" monospace labels, or leave at 1 for sketch feel). For presentation diagrams, use `fontFamily: 2` (Helvetica). |
| Background | `appState.viewBackgroundColor: "#FFFFFF"` |

**Excalidraw-specific data:**
```json
{
  "type": "excalidraw",
  "version": 2,
  "source": "archmorph",
  "elements": [...],
  "appState": {
    "viewBackgroundColor": "#FFFFFF",
    "gridSize": 20,
    "theme": "light"
  },
  "files": {
    "<hash>": {
      "mimeType": "image/svg+xml",
      "id": "<hash>",
      "dataURL": "data:image/svg+xml;base64,...",
      "created": 1
    }
  }
}
```

### 10.2 Draw.io (.drawio)

**File structure:** XML `<mxfile>` with `<diagram>` children (one per page/tab).

| Aspect | Implementation |
|--------|---------------|
| Multi-page | Multiple `<diagram>` elements inside `<mxfile>`. `name` attribute = page title. |
| Icons | Prefer embedded SVG via `shape=image;image=data:image/svg+xml;base64,...`. Fallback: `shape=mxgraph.azure.*` stencil library shapes. |
| Zones | `swimlane` style with `startSize=30` for header. Fill = pastel zone color. |
| Connections | `<mxCell edge="1">` with `source` and `target` attributes pointing to shape IDs. Style: `edgeStyle=orthogonalEdgeStyle;rounded=1;`. |
| Routing | Orthogonal with rounded corners. `jettySize=auto;orthogonalLoop=1;` |
| Page size | `pageWidth="4960" pageHeight="3508"` (A3 at ~300 PPI equivalent). |
| Stencil lib | Reference: `mxgraph.azure.*` — ships with Draw.io. Full list: [draw.io Azure stencils](https://github.com/jgraph/drawio/tree/master/src/main/webapp/stencils/azure). |

**Draw.io multi-page structure:**
```xml
<?xml version="1.0" encoding="UTF-8"?>
<mxfile host="archmorph" type="device" version="24.0">
  <diagram id="page1" name="Migration Overview">
    <mxGraphModel dx="1200" dy="800" ...>
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
        <!-- shapes + edges -->
      </root>
    </mxGraphModel>
  </diagram>
  <diagram id="page2" name="Azure Target Architecture">
    <!-- ... -->
  </diagram>
  <diagram id="page3" name="Service Mapping Detail">
    <!-- ... -->
  </diagram>
</mxfile>
```

**Draw.io service shape cell:**
```xml
<!-- Icon cell -->
<mxCell id="101" value=""
  style="shape=image;image=data:image/svg+xml;base64,...;aspect=fixed;"
  vertex="1" parent="zone_id">
  <mxGeometry x="8" y="40" width="40" height="40" as="geometry"/>
</mxCell>

<!-- Label + metadata cell -->
<mxCell id="102"
  value="&lt;b&gt;Azure Virtual Machines&lt;/b&gt;&lt;br/&gt;&lt;i style='color:#64748B;font-size:10px'&gt;from: EC2&lt;/i&gt;&lt;br/&gt;&lt;span style='color:#22C55E;font-size:9px'&gt;●●●●● 95%&lt;/span&gt; &lt;span style='color:#94A3B8;font-size:9px'&gt;$142/mo&lt;/span&gt;"
  style="text;html=1;align=left;verticalAlign=top;whiteSpace=wrap;rounded=1;strokeColor=#22C55E;fillColor=#FFFFFF;spacingLeft=4;"
  vertex="1" parent="zone_id">
  <mxGeometry x="52" y="40" width="220" height="70" as="geometry"/>
</mxCell>
```

### 10.3 Visio (.vsdx / .vdx)

**File structure:** VDX XML (Visio 2003 XML Drawing format). Target `.vdx` which can be opened by Visio and converted to `.vsdx`.

| Aspect | Implementation |
|--------|---------------|
| Multi-page | Multiple `<Page>` elements inside `<Pages>`. |
| Icons | Use `<Master>` shapes referencing Azure stencil names. Users must have the "Microsoft Azure" Visio stencil installed for icons to resolve. Embed shape geometry as fallback. |
| Zones | Group shapes (`Type="Group"`) with sub-shapes. |
| Connections | Dynamic connector shapes with `<XForm1D>` (BeginX/Y → EndX/Y). `<Connect>` elements in `<Connects>` section. |
| Page size | PageWidth=34 (inches) / PageHeight=22 for landscape A3-equivalent. |
| Stencil reference | Masters section declares stencil shapes. Azure stencils: "Microsoft Azure Cloud and AI.vssx" (official Visio stencil pack). |
| Units | All coordinates in inches. |

**Visio master stencil requirements:**
- Official: [Microsoft Azure stencils for Visio](https://learn.microsoft.com/en-us/azure/architecture/icons/)
- Masters are declared in `<Masters>` section and referenced by `Master="ID"` on shapes
- For portability, include basic shape geometry in the Master so diagrams render even without the official stencil

**Visio page structure:**
```xml
<Pages>
  <Page ID="0" Name="Migration Overview">
    <PageSheet>
      <PageProps>
        <PageWidth>34</PageWidth>
        <PageHeight>22</PageHeight>
      </PageProps>
    </PageSheet>
    <Shapes>
      <!-- Zone group shapes with service sub-shapes -->
    </Shapes>
    <Connects>
      <!-- Connection topology -->
    </Connects>
  </Page>
  <Page ID="1" Name="Azure Target Architecture">
    <!-- ... -->
  </Page>
</Pages>
```

---

## 11. Service Mapping Table (Page 3) Layout

This page renders as a structured visual table, not a flow diagram.

### 11.1 Table Structure

```
┌────────────────────────────────────────────────────────────────────────────────────┐
│  SERVICE MAPPING — Contoso AWS → Azure Migration                                   │
├─────────┬──────────────────┬──────────────────┬────────┬────────┬─────────┬────────┤
│ Category│ Source Service    │ Azure Target      │ Conf.  │ Effort │ Gaps    │ Cost   │
├─────────┼──────────────────┼──────────────────┼────────┼────────┼─────────┼────────┤
│ COMPUTE │                  │                  │        │        │         │        │
│         │ EC2              │ Virtual Machines │ ●●●●● 95%│ Low  │ None    │ $142   │
│         │ EKS              │ AKS              │ ●●●●● 95%│ Med  │ Add-ons │ $380   │
├─────────┼──────────────────┼──────────────────┼────────┼────────┼─────────┼────────┤
│ DATABASE│                  │                  │        │        │         │        │
│         │ Aurora           │ SQL Database     │ ●●●○○ 85%│ High │ Compat  │ $520   │
└─────────┴──────────────────┴──────────────────┴────────┴────────┴─────────┴────────┘
```

### 11.2 Table Cell Styling

| Column | Width | Alignment | Font |
|--------|-------|-----------|------|
| Category | 100px | Left, bold | 12pt Segoe UI Bold |
| Source Service | 180px | Left | 12pt Segoe UI |
| Azure Target | 180px | Left, bold | 12pt Segoe UI Semibold |
| Confidence | 100px | Center | 11pt, color-coded |
| Effort | 80px | Center | 10pt, pill badge |
| Feature Gaps | 120px | Left | 10pt, `#64748B` |
| Est. Cost | 80px | Right | 10pt Segoe UI Mono |

Category rows use the zone color palette as row background separators.

---

## 12. What Makes This "Presentation-Ready"

The difference between a data dump and a presentation-grade diagram:

| Data Dump | Presentation-Ready |
|-----------|-------------------|
| All services same size/color | Services sized by importance, color-coded by confidence |
| Random placement | Topology-aware layout (hub-spoke, 3-tier, etc.) |
| No metadata | Service annotations with cost, tier, SLA |
| Plain arrows | Protocol-labeled, type-colored connections |
| No grouping | Zone/boundary containers with subnet context |
| No legend | Full legend with color key |
| No header/footer | Project name, version, date, disclaimer |
| Single flat page | Multi-page: overview → detail → mapping table |
| No source reference | Source→target migration context (Page 1) |
| Missing icons | Official Azure icon set, consistently sized |
| No visual hierarchy | Z-ordering, opacity levels, font size hierarchy |
| No whitespace | Proper margins, grid alignment, balanced spacing |
| Hardcoded title | Dynamic title from project context |

### 12.1 Print-Ready A3 Checklist

Before declaring an export "production-ready," verify:

- [ ] All text readable at A3 print size (minimum 8pt at output)
- [ ] Color contrast passes WCAG AA (especially confidence colors on white bg)
- [ ] No overlapping shapes or labels
- [ ] All connections routed without ambiguity
- [ ] Legend fully visible and doesn't overlap content
- [ ] Title cartouche includes project name, date, version
- [ ] Disclaimer present unless version is "final"
- [ ] Zone labels don't overlap service shapes
- [ ] Edge labels have white background knockout (readable over crossing lines)
- [ ] Page number present on multi-page exports

---

## 13. Phased Implementation Plan

### Phase 1: Enhance Current Single-Page Export

**Target:** Fix the existing generators to match this spec for Page 2 (Azure Target Architecture).

Changes to `diagram_export.py`:
1. Add connection type styling (currently all arrows are identical)
2. Add cost annotations on shapes (from `cost_estimate`)
3. Add confidence badges (not just border color)
4. Add proper legend with all connection types
5. Add title cartouche with metadata
6. Add footer/disclaimer
7. Respect `service_connections` for edge routing (currently: consecutive zone arrows only)
8. Use topology-aware layout based on `architecture_style`

### Phase 2: Multi-Page Export

1. Add Page 1 (Migration Overview) with source + target side-by-side
2. Add Page 3 (Service Mapping Table)
3. Implement Draw.io multi-`<diagram>` structure
4. Implement Visio multi-`<Page>` structure
5. Implement Excalidraw frame-based page simulation

### Phase 3: Icon Enrichment

1. Expand `diagram_stencils.json` to cover all 130+ Azure services in mappings
2. Add AWS icon stencils for source services (Page 1)
3. Add GCP icon stencils for source services (Page 1)
4. Implement icon fallback chain: registry SVG → stencil ID → generic shape

---

## 14. Color Constant Reference

```python
# Brand
AZURE_PRIMARY     = "#0078D4"
AZURE_SECONDARY   = "#50E6FF"
ARCHMORPH_GREEN   = "#22C55E"
ARCHMORPH_DARK    = "#0F172A"

# Confidence (traffic light)
CONF_HIGH         = "#22C55E"  # green
CONF_MEDIUM       = "#F59E0B"  # amber
CONF_LOW          = "#EF4444"  # red

# Connection types
CONN_TRAFFIC      = "#0078D4"  # Azure blue
CONN_DATABASE     = "#8B5CF6"  # purple
CONN_AUTH         = "#F59E0B"  # amber
CONN_CONTROL      = "#64748B"  # gray
CONN_SECURITY     = "#EF4444"  # red
CONN_STORAGE      = "#06B6D4"  # cyan
CONN_MONITORING   = "#64748B"  # gray (dotted)
CONN_BACKUP       = "#06B6D4"  # cyan (dashed)
CONN_INSPECTION   = "#EF4444"  # red (long dash)

# Text
TEXT_PRIMARY       = "#0F172A"
TEXT_SECONDARY     = "#334155"
TEXT_MUTED         = "#64748B"
TEXT_SUBTLE        = "#94A3B8"

# Backgrounds
BG_WHITE           = "#FFFFFF"
BG_SURFACE         = "#F8FAFC"
LEGEND_BORDER      = "#E2E8F0"

# Provider source colors (Page 1 ghosted)
AWS_ORANGE         = "#FF9900"
GCP_BLUE           = "#4285F4"
```

---

## 15. Data Dependencies

The export function must receive or compute these values:

| Data | Source | Required For |
|------|--------|-------------|
| `zones` | `analysis.zones` | All pages |
| `mappings` | `analysis.mappings` | Pages 1, 2, 3 |
| `service_connections` | `analysis.service_connections` | Pages 1, 2, 4 |
| `cost_estimate` | `azure_pricing.py` result | Pages 2, 3 (cost column) |
| `architecture_style` | `analysis.architecture_overview.architecture_style` or inferred | Layout engine |
| `source_provider` | `analysis.source_provider` | Page 1 (source cloud color) |
| `title` | `analysis.title` or `hld.title` | Title cartouche |
| `primary_region` | `hld.region_strategy.primary_region` | Title cartouche |
| `compliance_frameworks` | `compliance_mapper.py` result | Footer context |
| `version` | Auto-generated or user-provided | Header/footer |
| `feature_gaps` | From `mappings[].notes` or AI analysis | Page 3 |
| `migration_effort` | From `mappings[].effort` or inferred from confidence | Pages 1, 3 |

---

## 16. Function Signatures (Updated)

Classic editable diagram exports continue through the legacy diagram renderer:

```python
def generate_diagram(
    analysis_result: dict,
  format: str,   # "excalidraw" | "drawio" | "vsdx"
    *,
    pages: list[str] | None = None,  # None = all pages. ["overview", "target", "mapping", "topology"]
    include_source: bool = True,     # Show source cloud on overview page
    include_costs: bool = True,      # Show cost annotations
    include_legend: bool = True,     # Show legend
    cost_estimate: dict | None = None,
    hld_metadata: dict | None = None,  # title, region, version, etc.
    project_name: str = "Architecture Migration",
) -> dict:
    """
    Returns:
        {
            "format": str,
            "filename": str,
            "content": str,      # JSON (excalidraw) or XML (drawio/vsdx)
            "content_type": str,  # MIME type
            "pages": list[str],  # names of included pages
        }
    """
```

      Architecture Package exports use a separate renderer and route:

      ```python
      def generate_architecture_package(
        analysis_result: dict,
        *,
        format: str = "html",      # "html" | "svg"
        diagram: str = "primary",  # "primary" | "dr"
      ) -> dict:
        """
        Returns:
          {
            "format": str,
            "filename": str,      # architecture-package-*.html or architecture-package-*.svg
            "content": str,       # HTML or SVG
            "content_type": str,  # text/html or image/svg+xml
          }
        """
      ```
