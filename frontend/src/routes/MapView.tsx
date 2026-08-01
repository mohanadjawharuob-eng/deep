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

const COLOUR: Record<string, string> = {
  site: "#c2622f",
  artifact: "#3f7d6a",
  context: "#5b6cb5",
  gis_layer: "#8a6bb1",
};

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

    const instance = L.map(container.current, { zoomControl: true }).setView([31.95, 35.93], 8);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "© OpenStreetMap contributors",
      maxZoom: 19,
    }).addTo(instance);

    layer.current = L.layerGroup().addTo(instance);
    map.current = instance;

    const refresh = async () => {
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
        const colour = COLOUR[hit.resource_type] ?? "#7a7a7a";

        const marker = L.circleMarker([hit.latitude, hit.longitude], {
          radius: hit.is_approximate ? 9 : 6,
          color: colour,
          weight: hit.is_approximate ? 1 : 2,
          fillColor: colour,
          fillOpacity: hit.is_approximate ? 0.15 : 0.75,
          // A dashed ring reads as "somewhere around here", which is what an
          // approximate coordinate means.
          dashArray: hit.is_approximate ? "3 3" : undefined,
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
    void refresh();

    return () => {
      instance.remove();
      map.current = null;
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
        actions={
          <div className="row-tight wrap">
            {[
              { value: "site", label: "Sites" },
              { value: "artifact", label: "Finds" },
              { value: "context", label: "Contexts" },
              { value: "gis_layer", label: "GIS" },
            ].map((option) => (
              <button
                key={option.value}
                type="button"
                className={`btn btn-sm ${types.includes(option.value) ? "btn-primary" : ""}`}
                onClick={() => toggle(option.value)}
              >
                <span
                  className="legend-dot"
                  style={{ background: COLOUR[option.value] }}
                  aria-hidden="true"
                />
                {option.label}
              </button>
            ))}
          </div>
        }
      />

      {error && <ErrorNote message={error} />}

      <div
        ref={container}
        className="map-shell"
        data-theme={resolved}
        role="application"
        aria-label="Map of records"
      />

      <p className="small muted" style={{ marginTop: "var(--space-3)" }}>
        A hollow, dashed marker means the location is restricted and shown only
        approximately.
      </p>
    </>
  );
}

function escapeHtml(value: string) {
  return value.replace(
    /[&<>"']/g,
    (character) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]!,
  );
}
