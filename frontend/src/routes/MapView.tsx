/**
 * The map.
 *
 * Leaflet, driven by the bounding-box endpoint: what is fetched is what is on
 * screen. Panning refetches; zooming out far enough stops fetching rather than
 * asking the database for the world.
 *
 * Restricted sites are drawn differently and say so. A looter reading a map is
 * the reason the backend blurs those coordinates, and a map that renders a
 * blurred point identically to a surveyed one quietly undoes that.
 */

import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

import { api } from "../lib/api";
import { useTheme } from "../lib/hooks";
import { ErrorNote, PageHeader } from "../components/ui";

type Hit = {
  resource_type: string;
  id: string;
  label: string;
  latitude: number | null;
  longitude: number | null;
  is_approximate: boolean;
  project_id: string | null;
  site_id: string | null;
};

const ROUTE: Record<string, (hit: Hit) => string> = {
  site: (hit) => `/sites/${hit.id}`,
  artifact: (hit) => `/artifacts/${hit.id}`,
  project: (hit) => `/projects/${hit.id}`,
};

/**
 * Marker colours, read from the theme at render time rather than hard-coded.
 *
 * Leaflet draws into SVG attributes and cannot take a CSS custom property, so
 * the values have to be resolved — but resolving them from the stylesheet is
 * what keeps the map inside the design rather than beside it, and is what makes
 * the markers change with the theme.
 */
const MARKER_TOKENS: Record<string, string> = {
  site: "--accent",
  artifact: "--info",
  context: "--ok",
  gis_layer: "--text-3",
};

function tokenValue(name: string, fallback: string) {
  if (typeof window === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

/** Below this zoom the view spans more than a query is worth. */
const MIN_ZOOM_TO_QUERY = 6;

export function MapView() {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const layer = useRef<L.LayerGroup | null>(null);
  const navigate = useNavigate();
  const { resolved } = useTheme();

  const [types, setTypes] = useState<string[]>(["site", "artifact"]);
  const [count, setCount] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tooBroad, setTooBroad] = useState(false);

  // Kept in a ref so the moveend handler, registered once, always reads the
  // current filter rather than the one it closed over.
  const typesRef = useRef(types);
  typesRef.current = types;

  useEffect(() => {
    if (!container.current || map.current) return;

    // Zoom sits top-right: the layer panel and the legend own the left, and
    // Leaflet's default put the +/− buttons directly on top of the first
    // checkbox.
    const instance = L.map(container.current, { zoomControl: false }).setView([31.95, 35.93], 6);
    L.control.zoom({ position: "topright" }).addTo(instance);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "© OpenStreetMap contributors",
      maxZoom: 19,
    }).addTo(instance);

    layer.current = L.layerGroup().addTo(instance);
    map.current = instance;

    // Set when the effect tears down. Both the initial framing and every
    // refresh are async, and a map that has been removed throws
    // `_leaflet_pos of undefined` if anything touches it afterwards —
    // which is exactly what happens when the user navigates away while the
    // first request is still in flight.
    let disposed = false;

    const refresh = async () => {
      if (disposed) return;
      const zoom = instance.getZoom();
      if (zoom < MIN_ZOOM_TO_QUERY) {
        setTooBroad(true);
        layer.current?.clearLayers();
        setCount(null);
        return;
      }
      setTooBroad(false);

      const bounds = instance.getBounds();
      const bbox = [
        bounds.getWest(),
        bounds.getSouth(),
        bounds.getEast(),
        bounds.getNorth(),
      ]
        .map((value) => value.toFixed(6))
        .join(",");

      try {
        const result = await api.get<{ items: Hit[]; total: number }>("/spatial/bbox", {
          bbox,
          types: typesRef.current,
          limit: 500,
        });
        if (disposed) return;
        setError(null);
        setCount(result.total);
        draw(result.items);
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "The map could not be loaded");
      }
    };

    const draw = (hits: Hit[]) => {
      layer.current?.clearLayers();
      for (const hit of hits) {
        if (hit.latitude === null || hit.longitude === null) continue;
        const colour = tokenValue(MARKER_TOKENS[hit.resource_type] ?? "--text-3", "#7a7060");

        // A hollow dashed ring, twice the size, reads as "somewhere in
        // here" — which is what a protected location means. It must never be
        // mistakable for a surveyed point, because a looter reading this map
        // is the reason the backend blurred the coordinate in the first place.
        const warn = tokenValue("--warn", "#8a6410");
        const marker = L.circleMarker([hit.latitude, hit.longitude], {
          radius: hit.is_approximate ? 12 : 6,
          color: hit.is_approximate ? warn : colour,
          weight: 2,
          fillColor: colour,
          fillOpacity: hit.is_approximate ? 0 : 0.75,
          dashArray: hit.is_approximate ? "4 3" : undefined,
        });

        const to = ROUTE[hit.resource_type]?.(hit);
        marker.bindPopup(
          `<strong>${escapeHtml(hit.label)}</strong><br>` +
            `<span style="opacity:.7">${hit.resource_type.replace(/_/g, " ")}</span>` +
            (hit.is_approximate
              ? '<br><span style="opacity:.7">Location shown approximately</span>'
              : "") +
            (to ? `<br><a href="#open">Open record</a>` : ""),
        );
        if (to) {
          marker.on("popupopen", (event) => {
            const link = (event as L.PopupEvent).popup
              .getElement()
              ?.querySelector('a[href="#open"]');
            link?.addEventListener("click", (click) => {
              click.preventDefault();
              navigate(to);
            });
          });
        }
        marker.addTo(layer.current!);
      }
    };

    instance.on("moveend", () => void refresh());

    // Open on the records, not on a hard-coded capital. A platform whose map
    // opens over empty countryside and says "0 records in view" reads as
    // broken, when in fact the data is four hundred kilometres north.
    const frame = async () => {
      try {
        const sites = await api.get<{ items: { latitude: number | null; longitude: number | null }[] }>(
          "/sites",
          { limit: 200 },
        );
        if (disposed) return;
        const points = sites.items
          .filter((site) => site.latitude !== null && site.longitude !== null)
          .map((site) => [site.latitude!, site.longitude!] as [number, number]);

        if (points.length === 1) {
          instance.setView(points[0]!, 12);
        } else if (points.length > 1) {
          instance.fitBounds(L.latLngBounds(points), { padding: [60, 60], maxZoom: 13 });
        } else {
          await refresh();
        }
      } catch {
        // No sites readable, or the request failed. The default view stands,
        // and `refresh` will report whatever is in it.
        await refresh();
      }
    };
    void frame();

    return () => {
      disposed = true;
      instance.remove();
      map.current = null;
      layer.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Changing the filter is a new question about the same view.
  useEffect(() => {
    map.current?.fire("moveend");
  }, [types]);

  const toggle = (value: string) =>
    setTypes((current) =>
      current.includes(value) ? current.filter((item) => item !== value) : [...current, value],
    );

  return (
    <>
      <PageHeader
        title="Map"
        subtitle={
          tooBroad
            ? "Zoom in to load records"
            : count === null
              ? "Everything with a coordinate"
              : `${count.toLocaleString()} record${count === 1 ? "" : "s"} in view`
        }
      />

      {error && <ErrorNote message={error} />}

      <div className="map-shell">
        <div
          ref={container}
          data-theme={resolved}
          role="application"
          aria-label="Map of records"
          style={{ position: "absolute", inset: 0 }}
        />

        <div className="map-panel top-left">
          <div className="overline" style={{ marginBottom: 7 }}>
            Layers
          </div>
          {LAYERS.map((option) => (
            <label key={option.value} className="checkbox" style={{ padding: "3px 0", width: "100%" }}>
              <input
                type="checkbox"
                checked={types.includes(option.value)}
                onChange={() => toggle(option.value)}
              />
              <span
                className="legend-dot"
                style={{ background: `var(${MARKER_TOKENS[option.value]})` }}
                aria-hidden="true"
              />
              <span className="small">{option.label}</span>
            </label>
          ))}
        </div>

        <div className="map-panel bottom-left">
          <div className="overline" style={{ marginBottom: 7 }}>
            Legend
          </div>
          <div className="legend-row">
            <span className="legend-dot" style={{ background: "var(--accent)" }} aria-hidden="true" />
            Surveyed position
          </div>
          <div className="legend-row">
            <span className="legend-dot approximate" aria-hidden="true" />
            Approximate — location protected
          </div>
          <p className="small muted" style={{ marginTop: 6 }}>
            Restricted sites are shown at reduced precision; the circle is the area, not the point.
          </p>
        </div>
      </div>
    </>
  );
}

const LAYERS = [
  { value: "site", label: "Sites" },
  { value: "artifact", label: "Finds" },
  { value: "context", label: "Contexts" },
  { value: "gis_layer", label: "GIS layers" },
];

function escapeHtml(value: string) {
  return value.replace(
    /[&<>"']/g,
    (character) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]!,
  );
}
