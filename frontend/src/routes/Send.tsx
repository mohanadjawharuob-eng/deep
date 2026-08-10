/**
 * The one page somebody with no account ever sees.
 *
 * A photographer, a contractor, a colleague at another institution. They did not
 * ask to be here, they have no idea what this platform is, and they have one
 * job: send some files. So the page answers, in this order, the questions they
 * actually have — what is being asked for, who is asking, what happens when I
 * drop a file here, and what this link can and cannot do.
 *
 * It carries the institution's own name and mark, because an unbranded page
 * asking a stranger to upload files is indistinguishable from a phishing page,
 * and they are right to hesitate over one.
 *
 * Each file is sent on its own request and reported on its own line. A batch
 * that fails as a unit tells somebody with ten files and one bad one that
 * nothing worked, which is both untrue and unhelpful.
 */

import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "../lib/api";
import { useBranding } from "../lib/hooks";
import { BrandMark } from "../components/Shell";
import { Loading, formatDate } from "../components/ui";

type Invite = {
  record_label: string;
  kind: string;
  asked_for: string;
  message?: string | null;
  requested_by?: string | null;
  organisation: string;
  expires_at: string;
  uploads_left: number;
  accepted_note: string;
};

type Sent = {
  name: string;
  state: "sending" | "done" | "failed";
  detail?: string;
};

export function SendFiles() {
  const { token = "" } = useParams();
  const { branding } = useBranding();

  const [invite, setInvite] = useState<Invite | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [sent, setSent] = useState<Sent[]>([]);
  const [dragging, setDragging] = useState(false);
  const chooser = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let live = true;
    setLoading(true);
    api
      .get<Invite>(`/data-requests/invite/${encodeURIComponent(token)}`)
      .then((data) => live && setInvite(data))
      .catch((error: Error) => live && setProblem(error.message))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [token]);

  const send = async (files: FileList | File[]) => {
    for (const file of Array.from(files)) {
      setSent((current) => [...current, { name: file.name, state: "sending" }]);
      try {
        const result = await api.upload<{ uploads_left: number; thanks: string }>(
          `/data-requests/invite/${encodeURIComponent(token)}`,
          file,
        );
        setSent((current) =>
          current.map((item) =>
            item.name === file.name && item.state === "sending"
              ? { ...item, state: "done" }
              : item,
          ),
        );
        setInvite((current) =>
          current ? { ...current, uploads_left: result.uploads_left } : current,
        );
      } catch (error) {
        const detail = error instanceof Error ? error.message : "Could not be sent";
        setSent((current) =>
          current.map((item) =>
            item.name === file.name && item.state === "sending"
              ? { ...item, state: "failed", detail }
              : item,
          ),
        );
      }
    }
  };

  if (loading) {
    return (
      <div className="send-shell">
        <div className="send-card">
          <Loading rows={3} label="Checking the link" />
        </div>
      </div>
    );
  }

  if (problem || !invite) {
    return (
      <div className="send-shell">
        <div className="send-card">
          <h1 className="send-title">This link cannot be used</h1>
          <p>{problem ?? "The link is not valid."}</p>
          <p className="muted small" style={{ marginBottom: 0 }}>
            Links stop working when they expire, when they have accepted as many files as they
            were allowed, or when whoever sent it withdrew it. Ask them for a new one.
          </p>
        </div>
      </div>
    );
  }

  const full = invite.uploads_left <= 0;
  const delivered = sent.filter((item) => item.state === "done").length;

  return (
    <div className="send-shell">
      <div className="send-card">
        <div className="send-brand">
          <span className="brand-mark">
            {branding.logo_url ? (
              <img className="brand-logo" src={branding.logo_url} alt="" />
            ) : (
              <BrandMark size={22} />
            )}
          </span>
          <strong>{invite.organisation}</strong>
        </div>

        <h1 className="send-title">
          {invite.requested_by ? `${invite.requested_by} is asking` : "You have been asked"} for the{" "}
          {invite.asked_for}
        </h1>
        <p className="send-record">{invite.record_label}</p>

        {invite.message && <blockquote className="send-message">{invite.message}</blockquote>}

        {full ? (
          <div className="alert alert-info">
            This link has accepted all the files it was allowed. If there is more to send, ask{" "}
            {invite.requested_by ?? invite.organisation} for a new link.
          </div>
        ) : (
          <>
            <div
              className={`dropzone ${dragging ? "dragging" : ""}`}
              onDragOver={(event) => {
                event.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(event) => {
                event.preventDefault();
                setDragging(false);
                if (event.dataTransfer.files.length) void send(event.dataTransfer.files);
              }}
              onClick={() => chooser.current?.click()}
              role="button"
              tabIndex={0}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") chooser.current?.click();
              }}
            >
              <strong>Drop files here, or click to choose them</strong>
              <span className="muted small">{invite.accepted_note}</span>
            </div>
            <input
              ref={chooser}
              type="file"
              multiple
              hidden
              onChange={(event) => {
                if (event.target.files?.length) void send(event.target.files);
                event.target.value = "";
              }}
            />
          </>
        )}

        {sent.length > 0 && (
          <ul className="send-list">
            {sent.map((item, index) => (
              <li key={`${item.name}-${index}`} className={`send-item send-${item.state}`}>
                <span className="truncate">{item.name}</span>
                <span className="small">
                  {item.state === "sending"
                    ? "sending…"
                    : item.state === "done"
                      ? "sent"
                      : (item.detail ?? "could not be sent")}
                </span>
              </li>
            ))}
          </ul>
        )}

        {delivered > 0 && (
          <p className="send-thanks">
            Thank you — {delivered} file{delivered === 1 ? "" : "s"} filed against{" "}
            <b>{invite.record_label}</b>. You can close this page.
          </p>
        )}

        <p className="send-foot muted small">
          This link works until {formatDate(invite.expires_at)} and can only be used to send files
          for this one record. It does not give access to anything else at {invite.organisation}.
        </p>
      </div>
    </div>
  );
}

export default SendFiles;
