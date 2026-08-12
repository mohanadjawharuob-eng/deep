/**
 * The download page for somebody who was sent files.
 *
 * The person opening this has no account and did not ask to learn anything
 * about how the institution stores its archive. So the page says four things
 * and nothing else: who sent it, what it is, how big, and a button. No
 * navigation, no sign-in prompt, no branding of the platform itself beyond a
 * line at the bottom saying where it came from.
 *
 * An expired or wrong link gets one message, deliberately the same for both.
 * Telling an anonymous caller which of the two it was turns the page into a way
 * of testing tokens.
 */

import { useParams } from "react-router-dom";

import { api } from "../lib/api";
import { useAction, useQuery } from "../lib/hooks";
import { ErrorNote, Loading, formatDate } from "../components/ui";

type Collection = {
  title: string;
  note?: string | null;
  from_organisation: string;
  file_count: number;
  size_bytes: number;
  expires_at?: string | null;
};

function size(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function Collect() {
  const { token = "" } = useParams();

  const bundle = useQuery<Collection>(
    (signal) => api.get(`/deliveries/collect/${token}`, undefined, signal),
    [token],
  );

  const download = useAction(async () => {
    await api.download(`/deliveries/collect/${token}/download`, undefined, "files.zip");
  });

  return (
    <div className="collect-page">
      <div className="collect-card">
        {bundle.loading ? (
          <Loading rows={3} />
        ) : bundle.error ? (
          <>
            <h1 className="collect-title">This link no longer works</h1>
            <p className="muted">{bundle.error}</p>
          </>
        ) : bundle.data ? (
          <>
            <p className="muted small collect-from">From {bundle.data.from_organisation}</p>
            <h1 className="collect-title">{bundle.data.title}</h1>

            {bundle.data.note && <p className="collect-note">{bundle.data.note}</p>}

            <p className="muted">
              {bundle.data.file_count} file{bundle.data.file_count === 1 ? "" : "s"} ·{" "}
              {size(bundle.data.size_bytes)}
              {bundle.data.expires_at && (
                <> · available until {formatDate(bundle.data.expires_at)}</>
              )}
            </p>

            {download.error && <ErrorNote message={download.error} />}

            <button
              type="button"
              className="btn btn-primary btn-lg"
              disabled={download.running}
              onClick={() => void download.run()}
            >
              {download.running ? "Downloading…" : "Download"}
            </button>

            <p className="muted small collect-foot">
              A zip file, with the files in named folders. You do not need an account.
            </p>
          </>
        ) : null}
      </div>
    </div>
  );
}

export default Collect;
