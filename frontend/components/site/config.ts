// Site-wide constants. Owner: fill in the placeholders marked TODO.

export const SITE_NAME = "HireReady AI";
export const TAGLINE = "Paste the job. Upload your CV. Walk into the interview ready.";
export const DESCRIPTION =
  "A free mock interview that shows its working: see which job skills your CV actually proves " +
  "(with quotes verified in code), scores with their formulas, the questions this role will ask " +
  "and a 7-day plan. Practice only, no sign-up.";

/** Canonical origin, used for absolute Open Graph URLs, robots and the sitemap. */
export const SITE_URL = (
  process.env.SITE_URL ??
  (process.env.VERCEL_PROJECT_PRODUCTION_URL
    ? `https://${process.env.VERCEL_PROJECT_PRODUCTION_URL}`
    : "https://hireready-ai-gray.vercel.app")
).replace(/\/$/, "");

export const GITHUB_URL = "https://github.com/husnainzahid050-hub/hireready-ai";

/**
 * TODO(owner): paste your LinkedIn profile URL here, e.g. "https://www.linkedin.com/in/your-name".
 * While it is null the LinkedIn link is hidden (no dead links on the live site).
 */
export const LINKEDIN_URL: string | null = null;

/**
 * TODO(owner): a contact address for privacy requests. While it is null, the privacy page
 * points to GitHub's private vulnerability/issue channels instead.
 */
export const CONTACT_EMAIL: string | null = null;
