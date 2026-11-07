import { ImageResponse } from "next/og";

// Rendered once at build time (no request data), then served as a static PNG from our origin.
export const alt = "HireReady AI: Paste the job. Upload your CV. Walk into the interview ready.";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpengraphImage() {
  return new ImageResponse(
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
        padding: "72px 80px",
        background: "linear-gradient(135deg, #1e1b4b 0%, #312e81 45%, #4f46e5 100%)",
        color: "white",
        fontFamily: "sans-serif",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
        <div
          style={{
            width: 64,
            height: 64,
            borderRadius: 16,
            background: "white",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          {/* Drawn as SVG: a "✓" glyph would make the renderer fetch a font over the network. */}
          <svg width="40" height="40" viewBox="0 0 24 24">
            <path
              d="M5 12.5l4.5 4.5L19 7.5"
              fill="none"
              stroke="#4f46e5"
              strokeWidth="3"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </div>
        <div style={{ fontSize: 36, fontWeight: 600, letterSpacing: -0.5 }}>HireReady AI</div>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
        <div style={{ fontSize: 68, fontWeight: 700, lineHeight: 1.08, letterSpacing: -1.5 }}>
          Paste the job. Upload your CV. Walk into the interview ready.
        </div>
        <div style={{ fontSize: 30, color: "#c7d2fe", lineHeight: 1.35 }}>
          Skill gaps with verified CV quotes, role-specific questions, AI mock interview
        </div>
      </div>

      <div style={{ display: "flex", gap: 16, fontSize: 24, color: "#e0e7ff" }}>
        {["Free", "No sign-up", "Audio never stored"].map((t) => (
          <div
            key={t}
            style={{
              display: "flex",
              padding: "8px 18px",
              borderRadius: 999,
              border: "2px solid rgba(255,255,255,0.35)",
            }}
          >
            {t}
          </div>
        ))}
      </div>
    </div>,
    size,
  );
}
