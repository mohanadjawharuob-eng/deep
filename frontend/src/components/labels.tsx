/**
 * Printing a label that goes in the box with the object.
 *
 * The first attempt at this did two things wrong, and both are worth naming
 * because they are the ordinary way label printing fails.
 *
 * **The QR code never loaded.** It was an `<img src="/api/v1/…/qr.png">`, and
 * a request the browser makes on its own carries no Authorization header. The
 * API answered as if nobody were signed in — a 404 for any record that is not
 * public — so the image was a broken box, or with an `onError` handler, an
 * empty space. The label looked fine on screen right up until it came out of
 * the printer with nothing on it. The fix is `api.imageUrl`, which fetches the
 * PNG through the same session as everything else.
 *
 * **Print meant "print the page".** `window.print()` on a record card prints
 * the record card: headings, navigation, buttons, the lot. A label is a
 * different document that happens to be reachable from the same screen, so it
 * is rendered as one — a sheet of its own, everything else hidden, sized in
 * millimetres rather than pixels because it is going onto a physical sticker.
 *
 * The sheet is rendered outside `#root` through a portal, which is what lets
 * the print stylesheet hide the entire application with a single rule instead
 * of a growing list of things to remember to hide.
 */

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { api } from "../lib/api";

/** What goes on the sticker. */
export type LabelDetails = {
  /** The number people read and quote. Printed largest, in monospace. */
  number: string;
  /** What the thing is: an object title, a find name, a site name. */
  name?: string | null;
  /** Where it belongs: a collection, a site, a project. */
  context?: string | null;
  /** Anything else worth two words — a period, a material, a box. */
  note?: string | null;
  /** Where to fetch the QR image. Fetched through the session, not by `<img>`. */
  qrPath: string;
};

/** Label sizes people actually buy, in millimetres. */
const SIZES = {
  small: { width: 50, height: 25, label: "50 x 25 mm" },
  medium: { width: 70, height: 37, label: "70 x 37 mm" },
  large: { width: 99, height: 57, label: "99 x 57 mm" },
} as const;

type SizeName = keyof typeof SIZES;

/**
 * A button that opens the label, and a sheet that prints.
 *
 * Copies matter more than they look like they should: a box of forty sherds
 * from one context wants forty identical labels, and printing the same page
 * forty times is forty trips to the printer.
 */
export function PrintLabelButton({
  details,
  className = "btn btn-sm",
  children = "Print label",
}: {
  details: LabelDetails;
  className?: string;
  children?: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" className={className} onClick={() => setOpen(true)}>
        {children}
      </button>
      {open && <LabelDialog details={details} onClose={() => setOpen(false)} />}
    </>
  );
}

/**
 * The QR code as it appears on the record card, at thumbnail size.
 *
 * Separate from the label because it has a different job — it is there so
 * somebody can check a scan against the record in front of them — but it has
 * the same authorisation problem, so it fetches the same way.
 */
export function QrThumbnail({ path, size = 52 }: { path: string; size?: number }) {
  const qr = useQrImage(path);
  return (
    <span
      className="qr-thumb"
      style={{ width: size, height: size }}
      title={qr.state === "failed" ? `QR code unavailable. ${qr.reason}` : undefined}
    >
      {qr.state === "ready" && <img src={qr.url} alt="" width={size} height={size} />}
    </span>
  );
}

function LabelDialog({ details, onClose }: { details: LabelDetails; onClose: () => void }) {
  const [size, setSize] = useState<SizeName>("medium");
  const [copies, setCopies] = useState(1);
  const [showName, setShowName] = useState(true);
  const qr = useQrImage(details.qrPath);

  // The application is hidden while the sheet is on screen, so that what the
  // print preview shows is what the paper gets. Removing the class on unmount
  // matters: leaving it behind would make every later print blank.
  useEffect(() => {
    document.body.classList.add("printing-label");
    return () => document.body.classList.remove("printing-label");
  }, []);

  const chosen = SIZES[size];

  return createPortal(
    <div className="label-sheet">
      <div className="label-controls">
        <div className="label-controls-row">
          <label>
            Label size
            <select value={size} onChange={(event) => setSize(event.target.value as SizeName)}>
              {Object.entries(SIZES).map(([key, value]) => (
                <option key={key} value={key}>
                  {value.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Copies
            <input
              type="number"
              min={1}
              max={60}
              value={copies}
              onChange={(event) =>
                setCopies(Math.min(60, Math.max(1, Number(event.target.value) || 1)))
              }
            />
          </label>
          <label className="label-check">
            <input
              type="checkbox"
              checked={showName}
              onChange={(event) => setShowName(event.target.checked)}
            />
            Include the name
          </label>
        </div>
        <div className="label-controls-row">
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={() => window.print()}
            disabled={qr.state === "loading"}
          >
            Print
          </button>
          <button type="button" className="btn btn-sm" onClick={onClose}>
            Close
          </button>
          {qr.state === "failed" && (
            <span className="label-warning">
              The QR code could not be fetched, so the label will print without one. {qr.reason}
            </span>
          )}
          {qr.state === "loading" && <span className="muted">Fetching the QR code…</span>}
        </div>
        <p className="muted label-hint">
          In the print dialog, set margins to none and scale to 100%, or the label comes out
          smaller than the sticker it is going on.
        </p>
      </div>

      <div className="label-page">
        {Array.from({ length: copies }, (_, index) => (
          <div
            key={index}
            className="label"
            style={{ width: `${chosen.width}mm`, height: `${chosen.height}mm` }}
          >
            <div className="label-text">
              <div className="label-number">{details.number}</div>
              {showName && details.name && <div className="label-name">{details.name}</div>}
              {details.context && <div className="label-context">{details.context}</div>}
              {details.note && <div className="label-note">{details.note}</div>}
            </div>
            {qr.state === "ready" && <img className="label-qr" src={qr.url} alt="" />}
          </div>
        ))}
      </div>
    </div>,
    document.body,
  );
}

type QrState =
  | { state: "loading" }
  | { state: "ready"; url: string }
  | { state: "failed"; reason: string };

/**
 * The QR image, fetched with the session's token and released afterwards.
 *
 * A failure here is reported rather than hidden. A label with no QR code is
 * still a usable label; a label that silently loses its QR code is how a whole
 * box gets relabelled twice.
 */
function useQrImage(path: string): QrState {
  const [state, setState] = useState<QrState>({ state: "loading" });

  useEffect(() => {
    let url: string | null = null;
    let live = true;

    api
      .imageUrl(path, { size: 8 })
      .then((created) => {
        url = created;
        if (live) setState({ state: "ready", url: created });
        else URL.revokeObjectURL(created);
      })
      .catch((error: unknown) => {
        if (live) {
          setState({
            state: "failed",
            reason: error instanceof Error ? error.message : "",
          });
        }
      });

    return () => {
      live = false;
      if (url) URL.revokeObjectURL(url);
    };
  }, [path]);

  return state;
}
