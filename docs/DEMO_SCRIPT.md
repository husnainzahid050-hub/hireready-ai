# Demo script: 60–75 s video and 10 s GIF

The demo has one job: show that HireReady **shows its working**. Three proof moments carry it:

1. a skill verdict with a CV quote **verified** word for word,
2. a **follow-up** that refers to what the candidate just said,
3. the report score with **its formula** open.

Everything else is connective tissue. Follow-ups are not the headline (other tools have them);
the point of moment 2 is that the report later shows how the follow-up was handled.

## Setup

- Record on the **production site** after the release checklist passes, so the URL bar is real.
- Use **only the sample CV** ("Ali Raza", fictional) via **Try with a sample CV**. No real CVs,
  names or emails anywhere on screen.
- Browser: Chrome, window 1280×800, zoom 110–125%, bookmarks bar hidden, extensions hidden, a
  clean profile (no autofill). Light mode for the video; optionally record the GIF in both modes.
- Turn **practice mode off** (default) so no scores appear mid-interview, as in a real interview.
- Rehearse the shallow answer for shot 4 so it reliably triggers a follow-up, e.g. to a RAG
  question: *"I used a vector database and it worked well."*
- Screen recorder at 30 fps (OBS or the OS recorder). Record the mic for the voice answers;
  the interviewer's voice comes from the browser.
- Do several takes of shot 4; LLM output varies, so keep the take where the follow-up clearly
  quotes or paraphrases the answer.

## Video shot list (target 60–75 s)

Captions are burned in, bottom third, short. Any part played faster than real time **says so**
in its caption. Timings are the edited length.

| # | Shot | Length | On screen | Caption |
|---|---|---|---|---|
| 1 | Landing → click **Try with a sample CV** | 3 s | Hero, trust strip, cursor to the secondary CTA | "Free, no sign-up. This is a fictional sample CV." |
| 2 | Analysis streams in; zoom on one gap card with the green **verified** quote, then pan to a "no evidence found" card | 8 s | Score gauge filling, gap cards appearing | "Every verdict quotes the CV, checked word for word in code." then "No quote, no credit." (+ "sped up 3×" if sped up) |
| 3 | **Start interview**, Voice; question spoken with captions | 6 s | Interviewer panel, caption text, speaking indicator | "Questions are read aloud, with captions." |
| 4 | Record a deliberately shallow answer → "Transcribing…" → **follow-up that refers to it** | 10 s | Recorder timer + level meter, then the follow-up badge and text | "A shallow answer gets a follow-up about what you actually said." |
| 5 | Cut to the end: finish → report streams; hero band + readiness score | 6 s | Readiness hero | "6 questions later (cut)." |
| 6 | Open **How is this calculated?**; scroll to a question card with a highlighted transcript quote and the improved answer | 10 s | Formula expanded, dimension dots with reasons | "Every score shows its maths." then "Feedback quotes your own words." |
| 7 | Speech section: pace range bar, fillers incl. "matlab" | 5 s | Delivery section | "Pace, filler words (English and Urdu), long pauses. Audio is never stored." |
| 8 | Share sheet → copy link; print preview flash | 5 s | Share sheet (includes / excludes), print preview | "Read-only share link. Print or save as PDF." |
| 9 | Engineering page eval table | 6 s | `/engineering#evals` table | "Evals are published, including the misses." |
| 10 | End card | 4 s | Logo, `<FRONTEND_URL>`, GitHub URL | "Practice only. Never for live interviews." |

Total: about 63 s. Shots 5–8 use the report UI and shot 9 the eval table on
the Engineering page. `TODO(final)`: re-check labels ("How is this calculated?", share sheet) on
the production UI before recording.

No voice-over is needed; if you add one, keep it to the captions' words. Optional quiet
background music; the interviewer's spoken question in shot 3 should stay audible.

## GIF (about 10 s, the three proof moments only)

| Moment | From shot | Length | Caption (burned in) |
|---|---|---|---|
| Verified quote on a gap card | 2 | ~3.5 s | "CV quote, verified in code" |
| Follow-up that references the answer | 4 | ~3.5 s | "Follow-up on what you said" |
| Report formula open | 6 | ~3 s | "Every score shows its maths" |

- Cut hard between moments (no transitions); loop seamlessly back to moment 1.
- 900–1000 px wide, ≤ 12 fps, aim for a few MB so it loads on GitHub mobile. Example with ffmpeg:
  ```bash
  ffmpeg -i gif-source.mp4 -vf "fps=12,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4" -loop 0 docs/media/demo.gif
  ```
- If you record light and dark versions, embed them with `<picture>` and
  `media="(prefers-color-scheme: dark)"` (the `#gh-dark-mode-only` fragment is deprecated).
- Save as `docs/media/demo.gif` (the path the README already references).

## Stills

Also export 3 large screenshots for people who don't play media and for the LinkedIn post:
the analysis page (gap card with a verified quote), the report (score + formula open), and the
Engineering page (architecture + eval table). Save to `docs/media/`.

## Where it goes

- README top: the GIF. The MP4 dragged into the README on GitHub (it renders `.mp4`/`.webm`
  attachments inline); if it's too large, a hosted video link with a thumbnail.
- LinkedIn post: the 3 stills plus the MP4; live link in the first comment.

## 30-second live demo (for interviews)

"Click **Try with a sample CV**. Here's a gap with its quote, and this 'no evidence' is honest: the
model couldn't find it in the CV, so it doesn't pretend. Here's the follow-up it asked because my
answer was shallow. Here's the report formula: the model gives verdicts, code computes the number.
And here's the eval table, including what it gets wrong."
