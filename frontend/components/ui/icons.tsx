// Small inline SVG icon set (stroke icons on a 24px grid). No icon library: these ship as a
// few hundred bytes of markup and need no external requests (CSP: img-src 'self').
import type { ComponentProps } from "react";

type IconProps = ComponentProps<"svg">;

function Svg({ children, className = "size-5", ...props }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      className={className}
      {...props}
    >
      {children}
    </svg>
  );
}

export const ArrowRight = (p: IconProps) => (
  <Svg {...p}>
    <path d="M5 12h14M13 6l6 6-6 6" />
  </Svg>
);

export const Check = (p: IconProps) => (
  <Svg {...p}>
    <path d="M5 12.5l4.5 4.5L19 7.5" />
  </Svg>
);

export const FileText = (p: IconProps) => (
  <Svg {...p}>
    <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
    <path d="M14 3v5h5M9 13h6M9 17h6" />
  </Svg>
);

export const Upload = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 16V4M7 9l5-5 5 5" />
    <path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" />
  </Svg>
);

export const Scan = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="11" cy="11" r="6.5" />
    <path d="M20 20l-4.2-4.2M8.5 11h5" />
  </Svg>
);

export const Mic = (p: IconProps) => (
  <Svg {...p}>
    <rect x="9" y="3" width="6" height="11" rx="3" />
    <path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21" />
  </Svg>
);

export const Chart = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />
  </Svg>
);

export const Calendar = (p: IconProps) => (
  <Svg {...p}>
    <rect x="3.5" y="5" width="17" height="15.5" rx="2" />
    <path d="M3.5 10h17M8 3v4M16 3v4" />
  </Svg>
);

export const Share = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 7l8 6 8-6" />
    <rect x="3" y="5" width="18" height="14" rx="2" />
  </Svg>
);

export const Quote = (p: IconProps) => (
  <Svg {...p}>
    <path d="M9 7H6a2 2 0 0 0-2 2v3h5v5H4M20 7h-3a2 2 0 0 0-2 2v3h5v5h-5" />
  </Svg>
);

export const MessageQuestion = (p: IconProps) => (
  <Svg {...p}>
    <path d="M21 12a8.5 8.5 0 0 1-12.4 7.5L3 21l1.5-5.6A8.5 8.5 0 1 1 21 12z" />
    <path d="M9.8 9.5a2.3 2.3 0 0 1 4.4.9c0 1.5-2.2 2-2.2 3.1M12 16.3h.01" />
  </Svg>
);

export const Shield = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 3l8 3v6c0 4.5-3.4 8.2-8 9-4.6-.8-8-4.5-8-9V6z" />
    <path d="M8.5 12l2.5 2.5 4.5-5" />
  </Svg>
);

export const Alert = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 7.5v5.5M12 16.5h.01" />
  </Svg>
);

export const X = (p: IconProps) => (
  <Svg {...p}>
    <path d="M6 6l12 12M18 6L6 18" />
  </Svg>
);

export const Github = ({ className = "size-5", ...p }: IconProps) => (
  <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false" className={className} {...p}>
    <path
      fill="currentColor"
      d="M12 2a10 10 0 0 0-3.16 19.49c.5.09.68-.22.68-.48v-1.7c-2.78.6-3.37-1.34-3.37-1.34-.46-1.16-1.11-1.47-1.11-1.47-.91-.62.07-.6.07-.6 1 .07 1.53 1.03 1.53 1.03.9 1.52 2.34 1.08 2.91.83.09-.65.35-1.09.63-1.34-2.22-.25-4.55-1.11-4.55-4.94 0-1.09.39-1.98 1.03-2.68-.1-.25-.45-1.27.1-2.64 0 0 .84-.27 2.75 1.02a9.5 9.5 0 0 1 5 0c1.91-1.29 2.75-1.02 2.75-1.02.55 1.37.2 2.39.1 2.64.64.7 1.03 1.59 1.03 2.68 0 3.84-2.34 4.68-4.57 4.93.36.31.68.92.68 1.85v2.74c0 .27.18.58.69.48A10 10 0 0 0 12 2z"
    />
  </svg>
);

export const Linkedin = ({ className = "size-5", ...p }: IconProps) => (
  <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false" className={className} {...p}>
    <path
      fill="currentColor"
      d="M20.45 20.45h-3.56v-5.57c0-1.33-.02-3.04-1.85-3.04-1.85 0-2.13 1.45-2.13 2.94v5.67H9.35V9h3.41v1.56h.05c.48-.9 1.64-1.85 3.37-1.85 3.6 0 4.27 2.37 4.27 5.46v6.28zM5.34 7.43a2.06 2.06 0 1 1 0-4.13 2.06 2.06 0 0 1 0 4.13zM7.12 20.45H3.56V9h3.56v11.45zM22.22 0H1.77C.79 0 0 .77 0 1.73v20.54C0 23.23.79 24 1.77 24h20.45c.98 0 1.78-.77 1.78-1.73V1.73C24 .77 23.2 0 22.22 0z"
    />
  </svg>
);

/** Brand mark: a speech bubble with a check, drawn on the accent tile. */
export const LogoMark = ({ className = "size-8", ...p }: IconProps) => (
  <svg viewBox="0 0 32 32" aria-hidden="true" focusable="false" className={className} {...p}>
    <rect width="32" height="32" rx="8" fill="#4f46e5" />
    <path
      d="M9 9.5h14a2.5 2.5 0 0 1 2.5 2.5v7a2.5 2.5 0 0 1-2.5 2.5h-7.2L11 25v-3.5H9A2.5 2.5 0 0 1 6.5 19v-7A2.5 2.5 0 0 1 9 9.5z"
      fill="#fff"
    />
    <path
      d="M11.8 15.6l2.6 2.6 5.4-5.4"
      fill="none"
      stroke="#4f46e5"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export const ExternalLink = (p: IconProps) => (
  <Svg {...p}>
    <path d="M14 4h6v6M20 4l-9 9" />
    <path d="M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4" />
  </Svg>
);

export const ChevronDown = (p: IconProps) => (
  <Svg {...p}>
    <path d="M6 9l6 6 6-6" />
  </Svg>
);

export const Keyboard = (p: IconProps) => (
  <Svg {...p}>
    <rect x="2.5" y="6" width="19" height="12" rx="2" />
    <path d="M6.5 10h.01M10 10h.01M14 10h.01M17.5 10h.01M8 14h8" />
  </Svg>
);

export const Volume = (p: IconProps) => (
  <Svg {...p}>
    <path d="M11 5L6 9H3v6h3l5 4z" />
    <path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13" />
  </Svg>
);

export const VolumeOff = (p: IconProps) => (
  <Svg {...p}>
    <path d="M11 5L6 9H3v6h3l5 4z" />
    <path d="M16 9.5l5 5M21 9.5l-5 5" />
  </Svg>
);

export const Replay = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1" />
    <path d="M3.5 4v4.5H8" />
  </Svg>
);
