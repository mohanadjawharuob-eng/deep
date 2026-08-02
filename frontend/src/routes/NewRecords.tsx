/**
 * Adding a project, a site, a context or a find.
 *
 * These forms did not exist. The API has accepted all four since milestone 2,
 * and every screen that lists them was read-only — so the only way to put an
 * excavation into the platform was to write it into the database by hand. A
 * catalogue nobody can add to is a catalogue nobody uses.
 *
 * Deliberately short. Each form asks for what the record cannot exist without
 * and a handful of things people always know at the moment they are typing;
 * everything else is edited afterwards on the record itself. A create form
 * that asks forty questions is a create form people put off, and a record
 * deferred is a record that ends up on paper.
 *
 * The parent is chosen from a dropdown rather than typed, because a site needs
 * a project and a find needs a site, and making somebody paste an identifier
 * is how the wrong parent gets picked.
 */

import { useState, type ReactNode } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { api, type Page } from "../lib/api";
import { useAction, useQuery, useSession } from "../lib/hooks";
import { Empty, ErrorNote, PageHeader, humanise } from "../components/ui";

const SITE_TYPES = [
  "settlement",
  "burial",
  "religious",
  "industrial",
  "military",
  "agricultural",
  "cave",
  "underwater",
  "rock_art",
  "quarry",
  "other",
];

const CONTEXT_TYPES = [
  "layer",
  "cut",
  "fill",
  "structure",
  "surface",
  "deposit",
  "burial",
  "feature",
  "find_spot",
  "other",
];

/* --------------------------------------------------------------------------
 * The shell every one of these forms uses
 * ----------------------------------------------------------------------- */
function Form({
  title,
  subtitle,
  breadcrumb,
  children,
  onSubmit,
  saving,
  error,
  submitLabel = "Create",
}: {
  title: string;
  subtitle?: string;
  breadcrumb?: { label: string; to?: string }[];
  children: ReactNode;
  onSubmit: () => void;
  saving: boolean;
  error: string | null;
  submitLabel?: string;
}) {
  return (
    <>
      <PageHeader title={title} subtitle={subtitle} breadcrumb={breadcrumb} />
      <form
        className="card"
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit();
        }}
      >
        <div className="card-body">
          {error && <ErrorNote message={error} />}
          {children}
          <div className="row-tight" style={{ marginTop: "var(--space-4)" }}>
            <button className="btn btn-primary" type="submit" disabled={saving}>
              {saving ? "Saving…" : submitLabel}
            </button>
          </div>
        </div>
      </form>
    </>
  );
}

function Field({
  label,
  help,
  children,
}: {
  label: string;
  help?: string;
  children: ReactNode;
}) {
  return (
    <div className="field">
      <span className="field-label">{label}</span>
      {children}
      {help && <p className="field-help">{help}</p>}
    </div>
  );
}

/** Somebody without the right to create should be told, not shown a form. */
function NotAllowed({ what }: { what: string }) {
  return (
    <Empty title={`You cannot add a ${what}`}>
      Creating records needs contributor access to the archaeology module, and
      being on the project's team. Ask whoever administers the platform.
    </Empty>
  );
}

/* --------------------------------------------------------------------------
 * A project
 * ----------------------------------------------------------------------- */
export function NewProject() {
  const navigate = useNavigate();
  const { can } = useSession();
  const [form, setForm] = useState({
    name: "",
    code: "",
    institution: "",
    country: "",
    region: "",
    description: "",
    start_date: "",
  });

  const create = useAction(async () => {
    const created = await api.post<{ id: string }>("/projects", {
      name: form.name,
      // Upper-cased here as well as on the server, so the field shows what
      // will actually be stored rather than surprising somebody afterwards.
      code: form.code.trim().toUpperCase(),
      institution: form.institution || null,
      country: form.country || null,
      region: form.region || null,
      description: form.description || null,
      start_date: form.start_date || null,
    });
    navigate(`/projects/${created.id}`);
  });

  if (!can("archaeology", "supervisor")) {
    return (
      <Empty title="You cannot start a project">
        Starting a project needs supervisor access to the archaeology module —
        it is the thing everything else hangs off. Ask whoever administers the
        platform.
      </Empty>
    );
  }

  return (
    <Form
      title="New project"
      subtitle="An excavation, a survey, a research programme"
      breadcrumb={[{ label: "Projects", to: "/projects" }, { label: "New" }]}
      onSubmit={() => void create.run()}
      saving={create.running}
      error={create.error}
    >
      <Field label="Name">
        <input
          className="input"
          required
          value={form.name}
          onChange={(event) => setForm({ ...form, name: event.target.value })}
          placeholder="Tell el-Demo Regional Survey"
        />
      </Field>

      <Field
        label="Code"
        help="Short, and it goes into every inventory number underneath. Letters, digits and hyphens."
      >
        <input
          className="input mono"
          required
          minLength={2}
          value={form.code}
          onChange={(event) => setForm({ ...form, code: event.target.value.toUpperCase() })}
          placeholder="TED-2024"
        />
      </Field>

      <div className="row">
        <Field label="Country">
          <input
            className="input"
            value={form.country}
            onChange={(event) => setForm({ ...form, country: event.target.value })}
          />
        </Field>
        <Field label="Region">
          <input
            className="input"
            value={form.region}
            onChange={(event) => setForm({ ...form, region: event.target.value })}
          />
        </Field>
      </div>

      <Field label="Institution">
        <input
          className="input"
          value={form.institution}
          onChange={(event) => setForm({ ...form, institution: event.target.value })}
        />
      </Field>

      <Field label="Starts">
        <input
          className="input"
          type="date"
          value={form.start_date}
          onChange={(event) => setForm({ ...form, start_date: event.target.value })}
        />
      </Field>

      <Field label="Description">
        <textarea
          className="input textarea"
          rows={3}
          value={form.description}
          onChange={(event) => setForm({ ...form, description: event.target.value })}
        />
      </Field>
    </Form>
  );
}

/* --------------------------------------------------------------------------
 * A site
 * ----------------------------------------------------------------------- */
export function NewSite() {
  const navigate = useNavigate();
  const { can } = useSession();
  const [params] = useSearchParams();
  const [form, setForm] = useState({
    name: "",
    code: "",
    // Pre-selected when arriving from a project, which is how most sites are
    // added — from the project you are already looking at.
    project_id: params.get("project_id") ?? "",
    site_type: "settlement",
    country: "",
    latitude: "",
    longitude: "",
    description: "",
  });

  const projects = useQuery<Page<{ id: string; name: string; code: string }>>(
    (signal) => api.get("/projects", { limit: 200 }, signal),
    [],
  );

  const create = useAction(async () => {
    const created = await api.post<{ id: string }>("/sites", {
      name: form.name,
      code: form.code,
      project_id: form.project_id,
      site_type: form.site_type,
      country: form.country || null,
      latitude: form.latitude ? Number(form.latitude) : null,
      longitude: form.longitude ? Number(form.longitude) : null,
      description: form.description || null,
    });
    navigate(`/sites/${created.id}`);
  });

  if (!can("archaeology", "contributor")) return <NotAllowed what="site" />;

  return (
    <Form
      title="New site"
      subtitle="A place the project works on"
      breadcrumb={[{ label: "Sites", to: "/sites" }, { label: "New" }]}
      onSubmit={() => void create.run()}
      saving={create.running}
      error={create.error}
    >
      <Field label="Project" help="A site belongs to one project.">
        <select
          className="input select"
          required
          value={form.project_id}
          onChange={(event) => setForm({ ...form, project_id: event.target.value })}
        >
          <option value="">Choose one…</option>
          {projects.data?.items.map((project) => (
            <option key={project.id} value={project.id}>
              {project.name} ({project.code})
            </option>
          ))}
        </select>
      </Field>

      <Field label="Name">
        <input
          className="input"
          required
          value={form.name}
          onChange={(event) => setForm({ ...form, name: event.target.value })}
        />
      </Field>

      <Field label="Code" help="Unique within the project.">
        <input
          className="input mono"
          required
          value={form.code}
          onChange={(event) => setForm({ ...form, code: event.target.value })}
          placeholder="TED"
        />
      </Field>

      <Field label="Type">
        <select
          className="input select"
          value={form.site_type}
          onChange={(event) => setForm({ ...form, site_type: event.target.value })}
        >
          {SITE_TYPES.map((value) => (
            <option key={value} value={value}>
              {humanise(value)}
            </option>
          ))}
        </select>
      </Field>

      <Field label="Country">
        <input
          className="input"
          value={form.country}
          onChange={(event) => setForm({ ...form, country: event.target.value })}
        />
      </Field>

      <div className="row">
        <Field label="Latitude">
          <input
            className="input"
            type="number"
            step="any"
            value={form.latitude}
            onChange={(event) => setForm({ ...form, latitude: event.target.value })}
          />
        </Field>
        <Field label="Longitude">
          <input
            className="input"
            type="number"
            step="any"
            value={form.longitude}
            onChange={(event) => setForm({ ...form, longitude: event.target.value })}
          />
        </Field>
      </div>
      <p className="field-help">
        Decimal degrees. Leave them out if you do not have them — a site with no
        position is still a site, and a guessed one is worse than none. If the
        location is sensitive, mark the site restricted after creating it.
      </p>

      <Field label="Description">
        <textarea
          className="input textarea"
          rows={3}
          value={form.description}
          onChange={(event) => setForm({ ...form, description: event.target.value })}
        />
      </Field>
    </Form>
  );
}

/* --------------------------------------------------------------------------
 * A context
 * ----------------------------------------------------------------------- */
export function NewContext() {
  const navigate = useNavigate();
  const { can } = useSession();
  const [params] = useSearchParams();
  const [form, setForm] = useState({
    context_number: "",
    site_id: params.get("site_id") ?? "",
    context_type: "layer",
    trench: "",
    area: "",
    description: "",
    interpretation: "",
    excavated_by: "",
  });

  const sites = useQuery<Page<{ id: string; name: string; code: string }>>(
    (signal) => api.get("/sites", { limit: 200 }, signal),
    [],
  );

  const create = useAction(async () => {
    const created = await api.post<{ id: string }>("/contexts", {
      context_number: form.context_number,
      site_id: form.site_id,
      context_type: form.context_type,
      trench: form.trench || null,
      area: form.area || null,
      description: form.description || null,
      interpretation: form.interpretation || null,
      excavated_by: form.excavated_by || null,
    });
    navigate(`/contexts/${created.id}`);
  });

  if (!can("archaeology", "contributor")) return <NotAllowed what="context" />;

  return (
    <Form
      title="New context"
      subtitle="A layer, a cut, a fill — one unit of the sequence"
      breadcrumb={[{ label: "Sites", to: "/sites" }, { label: "New context" }]}
      onSubmit={() => void create.run()}
      saving={create.running}
      error={create.error}
    >
      <Field label="Site">
        <select
          className="input select"
          required
          value={form.site_id}
          onChange={(event) => setForm({ ...form, site_id: event.target.value })}
        >
          <option value="">Choose one…</option>
          {sites.data?.items.map((site) => (
            <option key={site.id} value={site.id}>
              {site.name} ({site.code})
            </option>
          ))}
        </select>
      </Field>

      <Field label="Context number" help="As written on the recording sheet. Unique within the site.">
        <input
          className="input mono"
          required
          value={form.context_number}
          onChange={(event) => setForm({ ...form, context_number: event.target.value })}
          placeholder="1001"
        />
      </Field>

      <Field label="Type">
        <select
          className="input select"
          value={form.context_type}
          onChange={(event) => setForm({ ...form, context_type: event.target.value })}
        >
          {CONTEXT_TYPES.map((value) => (
            <option key={value} value={value}>
              {humanise(value)}
            </option>
          ))}
        </select>
      </Field>

      <div className="row">
        <Field label="Trench">
          <input
            className="input"
            value={form.trench}
            onChange={(event) => setForm({ ...form, trench: event.target.value })}
          />
        </Field>
        <Field label="Area">
          <input
            className="input"
            value={form.area}
            onChange={(event) => setForm({ ...form, area: event.target.value })}
          />
        </Field>
      </div>

      <Field label="Description">
        <textarea
          className="input textarea"
          rows={3}
          value={form.description}
          onChange={(event) => setForm({ ...form, description: event.target.value })}
        />
      </Field>

      <Field label="Interpretation">
        <textarea
          className="input textarea"
          rows={2}
          value={form.interpretation}
          onChange={(event) => setForm({ ...form, interpretation: event.target.value })}
        />
      </Field>

      <Field label="Excavated by">
        <input
          className="input"
          value={form.excavated_by}
          onChange={(event) => setForm({ ...form, excavated_by: event.target.value })}
        />
      </Field>

      <p className="field-help">
        The stratigraphy is added afterwards — one relationship at a time on the
        context itself, or all at once from a spreadsheet on the site.
      </p>
    </Form>
  );
}

/* --------------------------------------------------------------------------
 * A find
 * ----------------------------------------------------------------------- */
export function NewArtifact() {
  const navigate = useNavigate();
  const { can } = useSession();
  const [params] = useSearchParams();
  const [form, setForm] = useState({
    inventory_number: "",
    name: "",
    site_id: params.get("site_id") ?? "",
    context_id: params.get("context_id") ?? "",
    object_type: "",
    material_text: "",
    trench: "",
    find_date: "",
    found_by: "",
    description: "",
  });

  const sites = useQuery<Page<{ id: string; name: string; code: string }>>(
    (signal) => api.get("/sites", { limit: 200 }, signal),
    [],
  );

  // Only the chosen site's contexts. Offering every context in the institution
  // is how a find ends up filed under another excavation's layer.
  const contexts = useQuery<Page<{ id: string; context_number: string }>>(
    (signal) => api.get("/contexts", { site_id: form.site_id, limit: 200 }, signal),
    [form.site_id],
    { enabled: Boolean(form.site_id) },
  );

  const create = useAction(async () => {
    const created = await api.post<{ id: string }>("/artifacts", {
      inventory_number: form.inventory_number,
      name: form.name || null,
      site_id: form.site_id,
      context_id: form.context_id || null,
      object_type: form.object_type || null,
      material_text: form.material_text || null,
      trench: form.trench || null,
      find_date: form.find_date || null,
      found_by: form.found_by || null,
      description: form.description || null,
    });
    navigate(`/artifacts/${created.id}`);
  });

  if (!can("archaeology", "contributor")) return <NotAllowed what="find" />;

  return (
    <Form
      title="New find"
      subtitle="An object as excavated"
      breadcrumb={[{ label: "Finds", to: "/artifacts" }, { label: "New" }]}
      onSubmit={() => void create.run()}
      saving={create.running}
      error={create.error}
    >
      <Field label="Site">
        <select
          className="input select"
          required
          value={form.site_id}
          onChange={(event) =>
            setForm({ ...form, site_id: event.target.value, context_id: "" })
          }
        >
          <option value="">Choose one…</option>
          {sites.data?.items.map((site) => (
            <option key={site.id} value={site.id}>
              {site.name} ({site.code})
            </option>
          ))}
        </select>
      </Field>

      <Field
        label="Context"
        help={
          form.site_id
            ? "Optional, but a find without one is a find nobody can date."
            : "Choose the site first."
        }
      >
        <select
          className="input select"
          value={form.context_id}
          disabled={!form.site_id}
          onChange={(event) => setForm({ ...form, context_id: event.target.value })}
        >
          <option value="">Not recorded</option>
          {contexts.data?.items.map((context) => (
            <option key={context.id} value={context.id}>
              {context.context_number}
            </option>
          ))}
        </select>
      </Field>

      <Field label="Inventory number" help="Unique within the site.">
        <input
          className="input mono"
          required
          value={form.inventory_number}
          onChange={(event) => setForm({ ...form, inventory_number: event.target.value })}
          placeholder="TED-2024-0001"
        />
      </Field>

      <Field label="Name">
        <input
          className="input"
          value={form.name}
          onChange={(event) => setForm({ ...form, name: event.target.value })}
          placeholder="Rim sherd"
        />
      </Field>

      <div className="row">
        <Field label="Object type">
          <input
            className="input"
            value={form.object_type}
            onChange={(event) => setForm({ ...form, object_type: event.target.value })}
            placeholder="vessel"
          />
        </Field>
        <Field label="Material">
          <input
            className="input"
            value={form.material_text}
            onChange={(event) => setForm({ ...form, material_text: event.target.value })}
            placeholder="ceramic"
          />
        </Field>
      </div>

      <div className="row">
        <Field label="Trench">
          <input
            className="input"
            value={form.trench}
            onChange={(event) => setForm({ ...form, trench: event.target.value })}
          />
        </Field>
        <Field label="Found on">
          <input
            className="input"
            type="date"
            value={form.find_date}
            onChange={(event) => setForm({ ...form, find_date: event.target.value })}
          />
        </Field>
      </div>

      <Field label="Found by">
        <input
          className="input"
          value={form.found_by}
          onChange={(event) => setForm({ ...form, found_by: event.target.value })}
        />
      </Field>

      <Field label="Description">
        <textarea
          className="input textarea"
          rows={3}
          value={form.description}
          onChange={(event) => setForm({ ...form, description: event.target.value })}
        />
      </Field>

      <p className="field-help">
        Measurements, condition, dating and photographs are added on the find
        itself. <Link to="/museum/import">Importing a spreadsheet</Link> is
        quicker for a whole season.
      </p>
    </Form>
  );
}
