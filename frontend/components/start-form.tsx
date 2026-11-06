"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { ApiError, createSession, uploadDocuments } from "@/lib/api";
import type { SessionOptions } from "@/lib/types";

const MAX_BYTES = 2 * 1024 * 1024;
const JD_MIN = 200;
const JD_MAX = 8000;
const ACCEPT =
  ".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document";

function validateFile(f: File): string | null {
  const name = f.name.toLowerCase();
  if (!name.endsWith(".pdf") && !name.endsWith(".docx")) return "Please upload a PDF or DOCX file.";
  if (f.size > MAX_BYTES) return "Your CV must be 2 MB or smaller.";
  if (f.size === 0) return "That file is empty.";
  return null;
}

type Option<T extends string> = { value: T; label: string };

function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: Option<T>[];
  onChange: (v: T) => void;
}) {
  return (
    <fieldset className="space-y-2">
      <legend className="text-sm font-medium">{label}</legend>
      <div className="flex flex-wrap gap-2">
        {options.map((o) => (
          <label
            key={o.value}
            className={`cursor-pointer rounded-lg border px-3 py-2 text-sm transition-colors has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-indigo-500 ${
              value === o.value
                ? "border-indigo-600 bg-indigo-50 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300"
                : "border-zinc-300 hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-900"
            }`}
          >
            <input
              type="radio"
              className="sr-only"
              name={label}
              value={o.value}
              checked={value === o.value}
              onChange={() => onChange(o.value)}
            />
            {o.label}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export function StartForm() {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [jd, setJd] = useState("");
  const [opts, setOpts] = useState<SessionOptions>({
    mode: "voice",
    difficulty: "junior",
    interview_type: "mixed",
    email: null,
    email_opt_in: false,
    consent: false,
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const jdLen = jd.trim().length;
  const fileError = file ? validateFile(file) : null;
  const canSubmit =
    !!file && !fileError && jdLen >= JD_MIN && jdLen <= JD_MAX && opts.consent && !busy;

  function pick(f: File | undefined | null) {
    if (!f) return;
    setFile(f);
    setError(validateFile(f));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit || !file) return;
    setBusy(true);
    setError(null);
    try {
      const { session_id } = await createSession({ ...opts, email: opts.email?.trim() || null });
      await uploadDocuments(session_id, file, jd);
      router.push(`/session/${session_id}/analysis`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-8" noValidate>
      {/* CV dropzone */}
      <div className="space-y-2">
        <label htmlFor="cv" className="text-sm font-medium">
          Your CV <span className="text-zinc-500">(PDF or DOCX, max 2 MB, 5 pages)</span>
        </label>
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            pick(e.dataTransfer.files[0]);
          }}
          onClick={() => inputRef.current?.click()}
          className={`flex cursor-pointer flex-col items-center justify-center gap-1 rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors ${
            dragging
              ? "border-indigo-500 bg-indigo-50 dark:bg-indigo-950"
              : "border-zinc-300 hover:border-zinc-400 dark:border-zinc-700"
          }`}
        >
          <input
            ref={inputRef}
            id="cv"
            type="file"
            accept={ACCEPT}
            className="sr-only"
            onChange={(e) => pick(e.target.files?.[0])}
          />
          {file ? (
            <>
              <p className="font-medium">{file.name}</p>
              <p className="text-sm text-zinc-500">
                {(file.size / 1024).toFixed(0)} KB · click to change
              </p>
            </>
          ) : (
            <>
              <p className="font-medium">Drop your CV here, or click to browse</p>
              <p className="text-sm text-zinc-500">Text-based PDFs work best (not scans)</p>
            </>
          )}
        </div>
        {fileError && (
          <p role="alert" className="text-sm text-red-600 dark:text-red-400">
            {fileError}
          </p>
        )}
      </div>

      {/* Job description */}
      <div className="space-y-2">
        <label htmlFor="jd" className="text-sm font-medium">
          Job description <span className="text-zinc-500">(paste the full posting)</span>
        </label>
        <textarea
          id="jd"
          value={jd}
          onChange={(e) => setJd(e.target.value)}
          rows={10}
          maxLength={JD_MAX + 500}
          placeholder="Paste the job title, responsibilities and requirements…"
          aria-describedby="jd-count"
          className="w-full rounded-xl border border-zinc-300 bg-transparent p-3 text-sm focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:outline-none dark:border-zinc-700"
        />
        <p
          id="jd-count"
          className={`text-right text-xs ${jdLen > JD_MAX || (jdLen > 0 && jdLen < JD_MIN) ? "text-red-600 dark:text-red-400" : "text-zinc-500"}`}
        >
          {jdLen.toLocaleString()} / {JD_MAX.toLocaleString()} characters
          {jdLen > 0 && jdLen < JD_MIN ? ` (at least ${JD_MIN})` : ""}
        </p>
      </div>

      {/* Options */}
      <div className="grid gap-6 sm:grid-cols-3">
        <Segmented
          label="Interview mode"
          value={opts.mode}
          onChange={(mode) => setOpts({ ...opts, mode })}
          options={[
            { value: "voice", label: "Voice" },
            { value: "text", label: "Text" },
          ]}
        />
        <Segmented
          label="Level"
          value={opts.difficulty}
          onChange={(difficulty) => setOpts({ ...opts, difficulty })}
          options={[
            { value: "junior", label: "Junior" },
            { value: "mid", label: "Mid" },
          ]}
        />
        <Segmented
          label="Interview type"
          value={opts.interview_type}
          onChange={(interview_type) => setOpts({ ...opts, interview_type })}
          options={[
            { value: "mixed", label: "Mixed" },
            { value: "technical", label: "Technical" },
            { value: "behavioral", label: "Behavioral" },
          ]}
        />
      </div>

      {/* Email (optional) */}
      <div className="space-y-2">
        <label htmlFor="email" className="text-sm font-medium">
          Email <span className="text-zinc-500">(optional: to receive your report)</span>
        </label>
        <input
          id="email"
          type="email"
          autoComplete="email"
          value={opts.email ?? ""}
          onChange={(e) => setOpts({ ...opts, email: e.target.value })}
          className="w-full rounded-lg border border-zinc-300 bg-transparent px-3 py-2 text-sm focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:outline-none dark:border-zinc-700"
        />
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={opts.email_opt_in}
            disabled={!opts.email}
            onChange={(e) => setOpts({ ...opts, email_opt_in: e.target.checked })}
          />
          Send me daily prep-plan reminders (unsubscribe anytime)
        </label>
      </div>

      <label className="flex items-start gap-2 text-sm">
        <input
          type="checkbox"
          className="mt-1"
          checked={opts.consent}
          onChange={(e) => setOpts({ ...opts, consent: e.target.checked })}
        />
        <span>
          I agree that my CV and answers are processed by AI services to generate feedback. Guest
          data is deleted automatically after 7 days, and audio is never stored.
        </span>
      </label>

      {error && (
        <p
          role="alert"
          className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950 dark:text-red-300"
        >
          {error}
        </p>
      )}

      <button
        type="submit"
        disabled={!canSubmit}
        className="w-full rounded-lg bg-indigo-600 px-5 py-3 font-medium text-white transition-colors hover:bg-indigo-700 focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50"
      >
        {busy ? "Uploading…" : "Analyze my CV"}
      </button>
    </form>
  );
}
