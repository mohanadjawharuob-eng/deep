/**
 * The API client.
 *
 * One place that knows how to talk to the backend, so no component builds a
 * URL or reads a token. Three things it handles that a bare `fetch` does not:
 *
 * - **Token refresh.** An expired access token is exchanged and the request
 *   retried once, transparently. Concurrent requests share one refresh rather
 *   than each starting their own, which would rotate the refresh token several
 *   times and trip the backend's reuse detection — logging the user out for
 *   doing nothing wrong.
 * - **Readable errors.** The backend answers with a `detail` string written
 *   for a person; that is what surfaces, not "Request failed with status 422".
 * - **Cancellation.** Every call takes a signal, so a screen that unmounts
 *   mid-request does not set state afterwards.
 */

const API = "/api/v1";
const ACCESS_KEY = "archeo.access";
const REFRESH_KEY = "archeo.refresh";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly body?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** Whether this is worth showing the user as their mistake rather than ours. */
  get isValidation() {
    return this.status === 422 || this.status === 409;
  }
}

export const tokens = {
  access: () => localStorage.getItem(ACCESS_KEY),
  refresh: () => localStorage.getItem(REFRESH_KEY),
  set(access: string, refresh: string) {
    localStorage.setItem(ACCESS_KEY, access);
    localStorage.setItem(REFRESH_KEY, refresh);
  },
  clear() {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
  },
};

/** Broadcast when the session ends, so the shell can send the user to sign in. */
export const SESSION_ENDED = "archeo:session-ended";

type Options = {
  method?: string;
  body?: unknown;
  query?: Record<string, unknown>;
  signal?: AbortSignal;
  /** Set for the refresh call itself, which must not recurse. */
  raw?: boolean;
};

function buildUrl(path: string, query?: Record<string, unknown>) {
  const url = `${API}${path}`;
  if (!query) return url;

  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) {
      for (const item of value) params.append(key, String(item));
    } else {
      params.set(key, String(value));
    }
  }
  const search = params.toString();
  return search ? `${url}?${search}` : url;
}

async function readError(response: Response): Promise<ApiError> {
  let detail = response.statusText || `Request failed (${response.status})`;
  let body: unknown;
  try {
    body = await response.json();
    const value = (body as { detail?: unknown })?.detail;
    if (typeof value === "string") {
      detail = value;
    } else if (Array.isArray(value)) {
      // FastAPI's validation errors: name the field rather than dumping JSON.
      detail = value
        .map((item: { loc?: unknown[]; msg?: string }) => {
          const field = Array.isArray(item.loc) ? item.loc.slice(1).join(".") : "";
          return field ? `${field}: ${item.msg}` : (item.msg ?? "");
        })
        .filter(Boolean)
        .join("; ");
    }

    // This platform's own validation handler puts "Validation failed" in
    // `detail` and the reasons in `errors`. Reading only `detail` turned a
    // password that was three characters short into "Validation failed.
    // Nothing was changed." - which is true, unhelpful, and indistinguishable
    // from a bug in the platform. The reasons are what somebody needs.
    const reasons = (body as { errors?: unknown })?.errors;
    if (Array.isArray(reasons) && reasons.length > 0) {
      const spelled = reasons
        .map((item: { field?: string; message?: string }) => {
          // Pydantic prefixes a custom validator's message with "Value error,",
          // which means nothing to anybody reading a form.
          const message = (item.message ?? "").replace(/^Value error,\s*/i, "");
          if (!message) return "";
          const field = item.field ? humaniseField(item.field) : "";
          // A message that already names the field reads badly with it
          // prepended: "Password: Password must contain a digit".
          if (!field || message.toLowerCase().startsWith(field.toLowerCase())) return message;
          return `${field}: ${message}`;
        })
        .filter(Boolean)
        .join(". ");
      if (spelled) detail = spelled;
    }
  } catch {
    /* A non-JSON error body is not worth failing over. */
  }
  return new ApiError(response.status, detail, body);
}

/** `full_name` -> `Full name`, so a form error names the field as the form does. */
function humaniseField(name: string): string {
  const words = name.split(".").pop()?.replace(/_id$/, "").replace(/_/g, " ") ?? name;
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** In-flight refresh, shared so parallel 401s cause one rotation, not several. */
let refreshing: Promise<boolean> | null = null;

async function refreshSession(): Promise<boolean> {
  const token = tokens.refresh();
  if (!token) return false;

  refreshing ??= (async () => {
    try {
      const response = await fetch(`${API}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: token }),
      });
      if (!response.ok) return false;
      const data = (await response.json()) as {
        access_token: string;
        refresh_token: string;
      };
      tokens.set(data.access_token, data.refresh_token);
      return true;
    } catch {
      return false;
    } finally {
      // Cleared on the next tick so callers awaiting this promise all see the
      // same result before a new refresh can start.
      queueMicrotask(() => {
        refreshing = null;
      });
    }
  })();

  return refreshing;
}

function endSession() {
  tokens.clear();
  window.dispatchEvent(new CustomEvent(SESSION_ENDED));
}

/**
 * One request, carrying the session, retried once if the token had expired.
 *
 * Kept separate from `request` because not everything the platform returns is
 * JSON — a CSV export or a PDF of labels needs the same session handling and a
 * completely different way of reading the body.
 */
async function sendWithSession(path: string, options: Options = {}): Promise<Response> {
  const { method = "GET", body, query, signal, raw } = options;

  const send = async () => {
    const headers: Record<string, string> = {};
    const access = tokens.access();
    if (access) headers.Authorization = `Bearer ${access}`;
    if (body !== undefined) headers["Content-Type"] = "application/json";

    return fetch(buildUrl(path, query), {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  };

  let response = await send();

  if (response.status === 401 && !raw && tokens.refresh()) {
    if (await refreshSession()) {
      response = await send();
    } else {
      endSession();
    }
  }

  if (response.status === 401 && !raw) endSession();
  if (!response.ok) throw await readError(response);
  return response;
}

export async function request<T>(path: string, options: Options = {}): Promise<T> {
  const response = await sendWithSession(path, options);
  if (response.status === 204) return undefined as T;

  const type = response.headers.get("content-type") ?? "";
  if (!type.includes("json")) return (await response.text()) as T;
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string, query?: Record<string, unknown>, signal?: AbortSignal) =>
    request<T>(path, { query, signal }),
  post: <T>(path: string, body?: unknown, signal?: AbortSignal) =>
    request<T>(path, { method: "POST", body, signal }),
  patch: <T>(path: string, body?: unknown, signal?: AbortSignal) =>
    request<T>(path, { method: "PATCH", body, signal }),
  put: <T>(path: string, body?: unknown, signal?: AbortSignal) =>
    request<T>(path, { method: "PUT", body, signal }),
  delete: <T>(path: string, signal?: AbortSignal) =>
    request<T>(path, { method: "DELETE", signal }),

  /**
   * Send a file.
   *
   * Multipart, so the body must *not* be JSON and the Content-Type header must
   * be left alone — the browser sets it, including the boundary, and a
   * hand-written one produces a request the server cannot parse. Everything
   * else is the same as any other call, and that is the point: an upload
   * written with a bare `fetch` carries no token refresh, so a form left open
   * over lunch fails with an unexplained 401.
   */
  async upload<T>(
    path: string,
    file: File,
    fields: Record<string, string | number | undefined> = {},
    signal?: AbortSignal,
  ): Promise<T> {
    const body = new FormData();
    body.append("file", file);
    for (const [key, value] of Object.entries(fields)) {
      if (value !== undefined && value !== null && value !== "") body.append(key, String(value));
    }

    const send = async () => {
      const headers: Record<string, string> = {};
      const access = tokens.access();
      if (access) headers.Authorization = `Bearer ${access}`;
      return fetch(`${API}${path}`, { method: "POST", headers, body, signal });
    };

    let response = await send();
    if (response.status === 401 && tokens.refresh()) {
      if (await refreshSession()) response = await send();
      else endSession();
    }
    if (response.status === 401) endSession();
    if (!response.ok) throw await readError(response);
    return (await response.json()) as T;
  },

  /**
   * Save a file the platform generates.
   *
   * A plain `<a href="/api/…">` would be simpler, but a link carries no
   * Authorization header — so the server would answer as if nobody were signed
   * in and hand back only the public records, with no error and no hint that
   * anything was missing. A silently short export is worse than a failed one.
   */
  async download(path: string, query?: Record<string, unknown>, filename?: string) {
    const response = await sendWithSession(path, { query });
    const blob = await response.blob();

    // The server names the file; `filename` is the fallback.
    const disposition = response.headers.get("content-disposition") ?? "";
    const named = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition);
    const name = named?.[1] ? decodeURIComponent(named[1]) : (filename ?? "download");

    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = name;
    document.body.append(anchor);
    anchor.click();
    anchor.remove();

    // Safari needs the URL to outlive the click, so revoking waits a tick.
    setTimeout(() => URL.revokeObjectURL(url), 10_000);
  },

  /**
   * Fetch an image the API generates, as a URL an `<img>` can use.
   *
   * The same problem as `download`, and it bites harder because it is silent:
   * `<img src="/api/v1/…/qr.png">` is a request the browser makes on its own,
   * with no Authorization header. The server answers as if nobody were signed
   * in, so every QR code for a record that is not public comes back 404 and the
   * image renders as a broken box — or, with an `onError` handler, as nothing
   * at all. Which is exactly what a label looks like when it fails to print.
   *
   * The caller owns the returned URL and should revoke it when done.
   */
  async imageUrl(path: string, query?: Record<string, unknown>): Promise<string> {
    const response = await sendWithSession(path, { query });
    return URL.createObjectURL(await response.blob());
  },

  async login(identifier: string, password: string) {
    const data = await request<{ access_token: string; refresh_token: string }>(
      "/auth/login",
      { method: "POST", body: { identifier, password }, raw: true },
    );
    tokens.set(data.access_token, data.refresh_token);
    return data;
  },

  async logout() {
    const refresh = tokens.refresh();
    try {
      if (refresh) await request("/auth/logout", { method: "POST", body: { refresh_token: refresh } });
    } catch {
      /* Signing out locally matters more than the server acknowledging it. */
    }
    tokens.clear();
  },
};

/* --------------------------------------------------------------------------
 * Shapes the API returns. Only what the interface actually reads — a full
 * mirror of every schema would go stale faster than it earned its keep.
 * ----------------------------------------------------------------------- */
export type Page<T> = { items: T[]; total: number; limit: number; offset: number };

export type CurrentUser = {
  id: string;
  username: string;
  full_name: string;
  email: string;
  role: string;
  institution?: string | null;
  position?: string | null;
  /** Whether they have uploaded a photograph, so a list of forty people does
      not make forty requests that all 404. */
  has_avatar?: boolean;
};

export type ModuleName =
  | "archaeology"
  | "museum"
  | "social_media"
  | "management"
  | "inventory"
  /** The activity hub. Seeded to every account on creation, unlike the rest. */
  | "activities"
  | "archive";

export type ModuleAccess = {
  user_id: string;
  username: string;
  is_platform_admin: boolean;
  access: Partial<Record<ModuleName, string>>;
};

export type Project = {
  id: string;
  name: string;
  code: string;
  status: string;
  country?: string | null;
  region?: string | null;
  institution?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  site_count?: number;
  artifact_count?: number;
  is_public: boolean;
  latitude?: number | null;
  longitude?: number | null;
};

export type Site = {
  id: string;
  name: string;
  code: string;
  project_id: string;
  site_type?: string | null;
  country?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  location_restricted?: boolean;
  date_from?: number | null;
  date_to?: number | null;
  review_status: string;
  is_public: boolean;
};

export type Artifact = {
  id: string;
  inventory_number: string;
  name: string;
  site_id: string;
  condition?: string | null;
  period_id?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  storage_location_id?: string | null;
  review_status: string;
  is_public: boolean;
};

export type MuseumObject = {
  id: string;
  accession_number: string;
  former_number?: string | null;
  number_is_legacy: boolean;
  title: string;
  object_type?: string | null;
  collection_id: string;
  condition: string;
  status: string;
  storage_location_id?: string | null;
  artifact_id?: string | null;
  is_public: boolean;
  review_status: string;
  //: Resolved by the detail endpoint only, so a card need not ask twice.
  collection_name?: string | null;
  storage_path?: string | null;
  [key: string]: unknown;
};

export type Collection = {
  id: string;
  name: string;
  code: string;
  accession_pattern?: string | null;
  accession_prefix?: string | null;
  accession_sequence: number;
  enforce_pattern: boolean;
  institution?: string | null;
  object_count?: number;
  next_accession_number?: string | null;
};

export type StorageNode = {
  id: string;
  kind: string;
  name: string;
  code: string;
  path: string;
  display_path: string;
  depth: number;
  parent_id?: string | null;
  is_active: boolean;
  capacity?: number | null;
  children: StorageNode[];
};

export type Activity = {
  id: string;
  action: string;
  user_label?: string | null;
  /** Null on an entry whose resource kind was not recorded. */
  resource_type?: string | null;
  resource_label?: string | null;
  summary?: string | null;
  created_at: string;
};

/* --- Form layouts, served by the backend --------------------------------- */
export type FormField = {
  name: string;
  label: string;
  kind: string;
  required: boolean;
  help?: string | null;
  placeholder?: string | null;
  max_length?: number | null;
  value_list?: string | null;
  references?: string | null;
  read_only: boolean;
  /** One of the columns a register of these records always has. */
  in_tray?: boolean;
  /**
   * A field this institution added rather than one the platform ships. Its
   * value lives inside the record's `metadata_json` under `name`, not in a
   * column of its own — which is what lets somebody add one without a
   * migration, and why reading and writing it goes through `fieldValue` and
   * `withField` rather than straight at `values[name]`.
   */
  custom?: boolean;
  width: number;
  unit?: string | null;
};

export type FormGroup = { label: string; fields: FormField[]; help?: string | null };
export type FormTab = { key: string; label: string; groups: FormGroup[] };
export type FormPortal = {
  key: string;
  label: string;
  endpoint: string;
  columns: string[];
  can_add: boolean;
};

export type FormLayout = {
  record_type: string;
  title: string;
  title_field: string;
  key_field: string;
  tabs: FormTab[];
  portals: FormPortal[];
  value_lists: string[];
  value_list_options: Record<string, { value: string; label: string }[]>;
};

/* --- Inventory ----------------------------------------------------------- */
export type Equipment = {
  id: string;
  asset_number: string;
  name: string;
  category?: string | null;
  manufacturer?: string | null;
  model?: string | null;
  serial_number?: string | null;
  status: string;
  needs_calibration: boolean;
  calibration_due_on?: string | null;
  storage_location_id?: string | null;
  is_public: boolean;
  created_at: string;
  [key: string]: unknown;
};

export type EquipmentDetail = Equipment & {
  storage_path?: string | null;
  open_checkout?: Checkout | null;
  last_calibration?: Calibration | null;
  calibration_overdue: boolean;
  can_edit: boolean;
  can_delete: boolean;
};

export type Checkout = {
  id: string;
  equipment_id: string;
  borrower_id?: string | null;
  borrower_label: string;
  project_id?: string | null;
  destination?: string | null;
  taken_at: string;
  due_on?: string | null;
  returned_at?: string | null;
  condition_out?: string | null;
  condition_in?: string | null;
  notes?: string | null;
  kit_id?: string | null;
  asset_number?: string | null;
  equipment_name?: string | null;
  days_overdue?: number | null;
};

export type Calibration = {
  id: string;
  equipment_id: string;
  performed_on: string;
  performed_by?: string | null;
  certificate_number?: string | null;
  result: string;
  next_due_on?: string | null;
  cost?: number | null;
  notes?: string | null;
};

export type Consumable = {
  id: string;
  code: string;
  name: string;
  category?: string | null;
  unit: string;
  quantity: number;
  reorder_level?: number | null;
  storage_location_id?: string | null;
  expires_on?: string | null;
  is_active: boolean;
  is_public: boolean;
  created_at: string;
  [key: string]: unknown;
};

export type ConsumableDetail = Consumable & {
  storage_path?: string | null;
  needs_reorder: boolean;
  expired: boolean;
  can_edit: boolean;
  can_delete: boolean;
};

export type StockMovement = {
  id: string;
  consumable_id: string;
  change: number;
  balance_after: number;
  reason: string;
  project_id?: string | null;
  issued_to_label?: string | null;
  kit_id?: string | null;
  notes?: string | null;
  occurred_at: string;
  recorded_by_label?: string | null;
  /** Filled where the movement is shown away from its own stock line. */
  consumable_code?: string | null;
  consumable_name?: string | null;
  unit?: string | null;
};

export type KitTemplateLine = {
  id: string;
  position: number;
  equipment_id?: string | null;
  consumable_id?: string | null;
  equipment_category?: string | null;
  quantity: number;
  is_optional: boolean;
  notes?: string | null;
  label?: string | null;
};

export type KitTemplate = {
  id: string;
  name: string;
  description?: string | null;
  is_active: boolean;
  is_public: boolean;
  line_count: number;
  created_at: string;
};

export type KitTemplateDetail = KitTemplate & {
  lines: KitTemplateLine[];
  can_edit: boolean;
  can_delete: boolean;
};

/** One thing a build could not supply. Data, not prose, so it can be listed. */
export type KitShortfall = {
  line_id?: string | null;
  what: string;
  wanted: number;
  supplied: number;
  reason: string;
  is_optional: boolean;
};

export type Kit = {
  id: string;
  name: string;
  template_id?: string | null;
  project_id?: string | null;
  issued_to_label: string;
  destination?: string | null;
  issued_at: string;
  due_on?: string | null;
  returned_at?: string | null;
  is_public: boolean;
  created_at: string;
};

export type KitDetail = Kit & {
  notes?: string | null;
  shortfalls: KitShortfall[];
  checkouts: Checkout[];
  stock_movements: StockMovement[];
  outstanding_items: number;
  can_edit: boolean;
  can_delete: boolean;
};

/* --- Management ---------------------------------------------------------- */
export type Budget = {
  id: string;
  code: string;
  name: string;
  funder?: string | null;
  amount: number;
  currency: string;
  status: string;
  starts_on?: string | null;
  ends_on?: string | null;
  project_id?: string | null;
  is_public: boolean;
  created_at: string;

  /** Summed from the expenses on the server. Never sent back. */
  paid: number;
  committed: number;
  /** A forecast. Deliberately outside `available`. */
  planned: number;
  spent: number;
  available: number;
  used_percent: number;
  overspent: boolean;
  [key: string]: unknown;
};

export type CategoryLine = {
  category: string;
  label: string;
  amount: number;
  count: number;
  percent: number;
};

export type BudgetDetail = Budget & {
  description?: string | null;
  grant_reference?: string | null;
  manager_label?: string | null;
  notes?: string | null;
  project_name?: string | null;
  by_category: CategoryLine[];
  expense_count: number;
  expired_with_funds: boolean;
  can_edit: boolean;
  can_delete: boolean;
};

export type BudgetTotals = {
  total: number;
  spent: number;
  available: number;
  budget_count: number;
  by_currency: Record<string, number>;
  needing_attention: string[];
};

export type Expense = {
  id: string;
  budget_id: string;
  description: string;
  amount: number;
  currency: string;
  category: string;
  status: string;
  spent_on: string;
  paid_on?: string | null;
  supplier?: string | null;
  reference?: string | null;
  paid_by_label?: string | null;
  project_id?: string | null;
  notes?: string | null;
  created_at: string;
  budget_code?: string | null;
  budget_name?: string | null;
  /** Set on creation when the line took the fund over. Never a refusal. */
  overspent_by?: number | null;
  budget_available_after?: number;
};

export type Task = {
  id: string;
  title: string;
  description?: string | null;
  status: string;
  priority: string;
  assignee_id?: string | null;
  assignee_label?: string | null;
  project_id?: string | null;
  project_name?: string | null;
  due_on?: string | null;
  completed_at?: string | null;
  position: number;
  notes?: string | null;
  days_overdue?: number | null;
  created_at: string;
};

export type TaskBoard = {
  todo: Task[];
  in_progress: Task[];
  blocked: Task[];
  done: Task[];
  overdue_count: number;
};

export type CalendarEvent = {
  id: string;
  title: string;
  description?: string | null;
  kind?: string | null;
  starts_at: string;
  ends_at?: string | null;
  all_day: boolean;
  location?: string | null;
  project_id?: string | null;
  project_name?: string | null;
  created_at: string;
  activity_id?: string | null;
  activity_title?: string | null;
  activity_kind?: string | null;
  /** The calendar is open to everybody, so a screen has to be able to say
   *  which blocks are the reader's to move. */
  can_edit: boolean;
};

/* --- Building a Harris matrix from a spreadsheet -------------------------- */
export type MatrixProblem = { row: number; message: string };

export type MatrixPlan = {
  sheet_name: string;
  row_count: number;
  /** Which column was taken for which field, so a wrong guess is visible
   *  before it becomes a wrong matrix. */
  columns: Record<string, string | null>;
  usable: number;
  already_there: number;
  problems: MatrixProblem[];
  /** Loops in the sequence. A Harris matrix is acyclic by definition, so any
   *  entry here is a sheet describing something that could not have happened. */
  contradictions: string[][];
  can_apply: boolean;
  relationships: { row: number; context: string; relation: string; related: string }[];
};

export type MatrixResult = MatrixPlan & { written: number };

/* --- The activity hub ----------------------------------------------------- */
/**
 * One undertaking: a season, a survey, a school visit, a week in the store.
 *
 * Named `HubActivity` rather than `Activity` because `Activity` above is a
 * line in the audit log — a thing that *happened to a record*. These are the
 * things the institution did. Two different meanings of one English word, and
 * conflating them in the type names is how somebody ends up passing one to a
 * function expecting the other.
 */
export type HubActivity = {
  id: string;
  title: string;
  kind: string;
  status: string;
  starts_on?: string | null;
  ends_on?: string | null;
  location?: string | null;
  lead_label?: string | null;
  team_size?: number | null;
  project_id?: string | null;
  site_id?: string | null;
  is_public: boolean;
  owner_id?: string | null;
  created_at: string;
  duration_days?: number | null;
  project_name?: string | null;
  site_name?: string | null;
  photo_count: number;
  equipment_count: number;
  outstanding_count: number;
  cover_photo_id?: string | null;
};

export type ActivityEquipment = {
  id: string;
  activity_id: string;
  equipment_id?: string | null;
  label: string;
  quantity: number;
  unit?: string | null;
  source?: string | null;
  performance_notes?: string | null;
  was_essential?: boolean | null;
  position: number;
  notes?: string | null;
  equipment_name?: string | null;
  asset_number?: string | null;
  equipment_exists: boolean;
};

export type ActivityPermit = {
  id: string;
  activity_id: string;
  name: string;
  issuer?: string | null;
  reference?: string | null;
  status: string;
  applied_on?: string | null;
  granted_on?: string | null;
  expires_on?: string | null;
  cost?: number | null;
  currency?: string | null;
  lead_time_days?: number | null;
  contact?: string | null;
  position: number;
  notes?: string | null;
  /** Elapsed days from applying to being granted — the number the hub exists
   *  to be able to produce. */
  days_to_obtain?: number | null;
  days_until_expiry?: number | null;
};

export type ActivityPreparation = {
  id: string;
  activity_id: string;
  description: string;
  category?: string | null;
  lead_time_days?: number | null;
  due_on?: string | null;
  is_done: boolean;
  done_on?: string | null;
  responsible_label?: string | null;
  position: number;
  notes?: string | null;
  days_until_due?: number | null;
};

export type ActivityCost = {
  id: string;
  activity_id: string;
  description: string;
  category: string;
  unit_cost: number;
  quantity: number;
  unit?: string | null;
  currency: string;
  supplier?: string | null;
  is_estimate: boolean;
  expense_id?: string | null;
  position: number;
  notes?: string | null;
  total: number;
};

export type ActivityPhoto = {
  id: string;
  activity_id: string;
  photograph_id: string;
  caption?: string | null;
  is_cover: boolean;
  position: number;
  title?: string | null;
  thumbnail_url?: string | null;
  taken_at?: string | null;
  photographer?: string | null;
};

export type CurrencyLine = {
  currency: string;
  amount: number;
  estimated_amount: number;
};

export type CostSummary = {
  /** Never one figure. Adding a dinar to a dollar produces a number that is
   *  wrong in a way nobody notices until a funder does. */
  by_currency: CurrencyLine[];
  line_count: number;
  estimate_count: number;
  linked_to_expenses: number;
  any_estimates: boolean;
};

export type OutstandingSummary = {
  permits: string[];
  preparations: string[];
  /** Items whose usual lead time no longer fits before the start date. */
  too_late: string[];
  longest_lead_days?: number | null;
  is_clear: boolean;
  /** False once the activity is over. The same unticked box means a task
   *  before, and a record of something never done after. */
  is_actionable: boolean;
};

export type HubActivityDetail = HubActivity & {
  summary?: string | null;
  team_notes?: string | null;
  outcome?: string | null;
  lessons?: string | null;
  budget_id?: string | null;
  lead_id?: string | null;
  updated_at?: string | null;
  equipment: ActivityEquipment[];
  permits: ActivityPermit[];
  preparations: ActivityPreparation[];
  costs: ActivityCost[];
  photos: ActivityPhoto[];
  cost_summary: CostSummary;
  outstanding: OutstandingSummary;
  repeated_from_id?: string | null;
  repeated_from_title?: string | null;
  repeat_count: number;
  can_edit: boolean;
  can_delete: boolean;
};

export type ActivityOption = {
  id: string;
  title: string;
  kind: string;
  status: string;
  starts_on?: string | null;
  location?: string | null;
  label: string;
};

export type HubSummary = {
  total: number;
  by_kind: Record<string, number>;
  by_status: Record<string, number>;
  upcoming: HubActivity[];
  recent: HubActivity[];
  needing_attention: HubActivity[];
  expiring_permits: ActivityPermit[];
};

export type BriefResult = {
  sent: boolean;
  detail: string;
  recipients: string[];
  /** Returned whether or not the mail went out, so a machine with no outbound
   *  mail still leaves somebody something to copy. */
  brief: string;
};

/* --- Social media -------------------------------------------------------- */
export type SocialAccount = {
  id: string;
  platform: string;
  handle: string;
  display_name?: string | null;
  url?: string | null;
  description?: string | null;
  manager_label?: string | null;
  follower_count?: number | null;
  is_active: boolean;
  is_public: boolean;
  created_at: string;
  post_count: number;
  published_count: number;
  awaiting_approval: number;
};

export type LocationFinding = {
  kind: string;
  detail: string;
  photograph_id?: string | null;
};

export type LocationCheckResult = {
  clear: boolean;
  findings: LocationFinding[];
  summary?: string | null;
};

export type PostAsset = {
  id: string;
  photograph_id: string;
  position: number;
  alt_text?: string | null;
  credit?: string | null;
  filename?: string | null;
  thumbnail_url?: string | null;
  /** True when this image still carries the coordinates the camera wrote. */
  has_gps: boolean;
};

export type PostMetric = {
  id: string;
  post_id: string;
  recorded_at: string;
  impressions?: number | null;
  reach?: number | null;
  likes?: number | null;
  comments?: number | null;
  shares?: number | null;
  saves?: number | null;
  clicks?: number | null;
  source?: string | null;
};

export type Engagement = {
  recorded_at?: string | null;
  impressions?: number | null;
  likes?: number | null;
  comments?: number | null;
  shares?: number | null;
  interactions?: number | null;
  change?: number | null;
  readings: number;
};

export type SocialPost = {
  id: string;
  account_id: string;
  title: string;
  body?: string | null;
  hashtags?: string[] | null;
  kind: string;
  status: string;
  scheduled_for?: string | null;
  published_at?: string | null;
  external_url?: string | null;
  language?: string | null;
  project_id?: string | null;
  resource_type?: string | null;
  resource_id?: string | null;
  reveals_location: boolean;
  location_warning?: string | null;
  is_public: boolean;
  created_at: string;
  platform?: string | null;
  handle?: string | null;
  asset_count: number;
  engagement?: Engagement | null;
};

export type SocialPostDetail = SocialPost & {
  approved_by_id?: string | null;
  approved_at?: string | null;
  approval_note?: string | null;
  notes?: string | null;
  assets: PostAsset[];
  metrics: PostMetric[];
  project_name?: string | null;
  subject_label?: string | null;
  approved_by_label?: string | null;
  location_check?: LocationCheckResult | null;
  can_edit: boolean;
  can_delete: boolean;
  can_approve: boolean;
  /** What colleagues have said while it was being got right. */
  notes_thread?: PostNote[];
};

export type PostNote = {
  id: string;
  body: string;
  /** `approved` or `sent_back` when the note came with a decision. */
  decision?: string | null;
  author_label?: string | null;
  created_at: string;
};

export type OutreachSummary = {
  accounts: number;
  published: number;
  scheduled: number;
  awaiting_approval: number;
  with_location_warnings: number;
  by_platform: Record<string, number>;
};
