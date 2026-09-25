import { useRef } from "react";
import { useOutletContext } from "react-router-dom";
import { UploadIcon } from "./Icons.jsx";
import { formatDate } from "../format.js";

// Title on the left; day picker + upload button on the right (same on all three screens).
export default function PageHeader({ title, subtitle }) {
  const { days, date, setDate, onFile } = useOutletContext();
  const fileInput = useRef(null);

  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        <p className="muted">{subtitle}</p>
      </div>
      <div className="controls">
        <label className="select-wrap">
          <span className="sr-only">Choose a day</span>
          <select value={date} onChange={(e) => setDate(e.target.value)}>
            {days.map((d) => (
              <option key={d.clinic_id + d.business_date} value={d.business_date}>
                {formatDate(d.business_date)}
              </option>
            ))}
          </select>
        </label>
        <input ref={fileInput} type="file" accept="application/json,.json" hidden onChange={onFile} />
        <button className="btn" onClick={() => fileInput.current.click()}>
          <UploadIcon /> Upload log
        </button>
      </div>
    </header>
  );
}
