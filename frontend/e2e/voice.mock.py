"""Real-browser test of voice answers on the interview page, against a mocked API.

Chrome runs with a fake microphone (--use-fake-device-for-media-stream: a beeping tone) and an
auto-accepted permission prompt. speechSynthesis is replaced by a recorder stub so the test can
check what the interviewer "says" without depending on the voices installed on the machine.
The fake API reuses the text-mode fake from interview.mock.py and adds multipart answers.

Usage (with the production build running):
    npm run build && npx next start -p 3001
    python e2e/voice.mock.py [screenshot_dir]   (E2E_BASE=... for another port)
"""

from __future__ import annotations

import importlib.util
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, Route, expect, sync_playwright

_spec = importlib.util.spec_from_file_location(
    "interview_mock", Path(__file__).with_name("interview.mock.py")
)
assert _spec and _spec.loader
im = importlib.util.module_from_spec(_spec)
sys.argv = sys.argv[:1] + (sys.argv[1:] or ["e2e-screenshots-voice"])  # shared SHOTS arg
_spec.loader.exec_module(im)

BASE, SID, SHOTS, PLAN = im.BASE, im.SID, im.SHOTS, im.PLAN
WEBM_MAGIC = b"\x1a\x45\xdf\xa3"
METRICS = {
    "duration_seconds": 14.2, "speaking_seconds": 13.5, "word_count": 31,
    "words_per_minute": 137.8, "filler_count": 3,
    "filler_breakdown": {"um": 2, "basically": 1}, "long_pauses": 1,
    "longest_pause_seconds": 2.6,
}  # fmt: skip

# speechSynthesis stub: records utterances, fires start/end like a real engine.
# getUserMedia wrapper: keeps every track so the test can assert none is left running.
INIT = """
(() => {
  window.__spoken = [];
  const synth = {
    speaking: false, pending: false, paused: false,
    getVoices: () => [{ name: 'Test English', lang: 'en-US', localService: true, default: true,
                        voiceURI: 'test' }],
    addEventListener() {}, removeEventListener() {},
    speak(u) {
      window.__spoken.push(u.text);
      this._u = u;
      setTimeout(() => u.onstart && u.onstart(new Event('start')), 20);
      this._t = setTimeout(() => { this._u = null; u.onend && u.onend(new Event('end')); }, 600);
    },
    cancel() {
      clearTimeout(this._t);
      const u = this._u; this._u = null;
      if (u && u.onend) u.onend(new Event('end'));
    },
    pause() {}, resume() {},
  };
  Object.defineProperty(window, 'speechSynthesis', { value: synth, configurable: true });
  window.SpeechSynthesisUtterance = window.SpeechSynthesisUtterance || function (t) { this.text = t; };
  window.__tracks = [];
  const md = navigator.mediaDevices;
  if (md && md.getUserMedia) {
    const orig = md.getUserMedia.bind(md);
    md.getUserMedia = async (c) => {
      if (window.__denyMic) throw new DOMException('Permission denied', 'NotAllowedError');
      const s = await orig(c);
      window.__tracks.push(...s.getTracks());
      return s;
    };
  }
  window.__liveTracks = () => window.__tracks.filter((t) => t.readyState === 'live').length;
})();
"""


class FakeVoiceInterview(im.FakeInterview):
    def __init__(self) -> None:
        super().__init__()
        self.uploads: list[bytes] = []
        self.voice_fail_next: list[tuple[int, str]] = []
        self.hold_voice = False

    def handle(self, route: Route) -> None:
        req = route.request
        ctype = req.headers.get("content-type", "")
        if req.method == "POST" and req.url.endswith("/answer") and "multipart" in ctype:
            return self.handle_voice(route)
        return super().handle(route)

    def handle_voice(self, route: Route) -> None:
        req = route.request
        assert req.headers.get("x-guest-token") == "tok-123"
        body = req.post_data_buffer or b""
        assert b'name="audio"; filename="answer.' in body, "audio part missing"
        m = re.search(rb'name="question_id"\r\n\r\n([^\r]+)\r\n', body)
        assert m, "question_id part missing"
        self.uploads.append(body)
        self.calls.append("POST voice")
        if self.voice_fail_next:
            status, code = self.voice_fail_next.pop(0)
            msg = ("We couldn't transcribe your recording right now. Your recording is kept on "
                   "this page: try uploading it again in a moment, or switch to typing.")
            return im._json(route, status, im._err(code, msg))
        if not self.queue or m.group(1).decode() != self.queue[0]["id"]:
            return im._json(route, 400, im._err("wrong_question", "Not the current question."))
        if self.hold_voice:
            self.hold_voice = False
            self.held.append(route)
            return None
        return self.answer_voice(route)

    def answer_voice(self, route: Route) -> None:
        n = len(self.history) + 1
        self.answer(f"Um, so basically this is my spoken answer number {n}.")
        assert self.last_answer is not None
        self.last_answer["speech_metrics"] = METRICS
        im._json(route, 200, self.turn(full_history=False))

    def release_voice(self) -> None:
        self.answer_voice(self.held.pop(0))


def new_page(browser, *, viewport, dark=False, mode="voice", extra_init="") -> Page:
    page = im.new_page(browser, viewport=viewport, dark=dark)
    page.context.add_init_script(INIT + extra_init)
    page.context.add_init_script(f"localStorage.setItem('hireready:mode:{SID}', '{mode}')")
    return page


def record_button(page: Page):
    return page.get_by_role("button", name="Start recording your answer")


def stop_button(page: Page):
    return page.get_by_role("button", name="Stop recording and send your answer")


def spoken(page: Page) -> list[str]:
    return page.evaluate("window.__spoken")


def record_for(page: Page, seconds: float, *, keyboard: bool = False) -> None:
    btn = record_button(page)
    expect(btn).to_be_enabled()
    if keyboard:
        btn.focus()
        page.keyboard.press("Space")
    else:
        btn.click()
    expect(stop_button(page)).to_be_visible()
    page.wait_for_timeout(int(seconds * 1000))
    if keyboard:
        page.keyboard.press("Enter")
    else:
        stop_button(page).click()


def started(page: Page, fake: FakeVoiceInterview, *, practice: bool) -> None:
    page.route("**/api/v1/**", fake.handle)
    page.goto(f"{BASE}/session/{SID}/interview")
    if practice:
        page.get_by_role("switch", name="Practice mode").check(force=True)
    page.get_by_role("button", name="Start interview").click()
    im.expect_question(page, PLAN[0][2])


# ---------------------------------------------------------------------- scenarios


def desktop_voice(browser) -> None:
    fake = FakeVoiceInterview()
    page = new_page(browser, viewport={"width": 1280, "height": 900})
    started(page, fake, practice=True)

    # Voice mode is on (session mode), the question is read aloud with the caption on screen.
    expect(page.get_by_role("radio", name="Voice")).to_be_checked()
    expect(record_button(page)).to_be_visible()
    expect(record_button(page)).to_be_focused()
    expect(page.get_by_text("Interviewer is speaking…")).to_be_visible()
    page.wait_for_function("window.__spoken.length >= 1")
    assert spoken(page)[-1].endswith(PLAN[0][2]), spoken(page)

    # Keyboard: Space starts, Enter stops. Timer runs, level meter moves, speech stops.
    fake.hold_voice = True
    record_btn = record_button(page)
    record_btn.focus()
    page.keyboard.press("Space")
    expect(stop_button(page)).to_be_focused()
    page.wait_for_timeout(2200)
    expect(page.get_by_text(re.compile(r"^0:0[2-9]"))).to_be_visible()
    level = float(page.locator("[data-testid=level-meter]").evaluate(
        "el => el.style.getPropertyValue('--level') || '0'"))
    assert level > 0, f"level meter did not move ({level})"
    assert page.evaluate("window.__liveTracks()") == 1
    page.screenshot(path=str(SHOTS / "voice-desktop-1-recording.png"), full_page=True)
    page.keyboard.press("Enter")

    expect(page.locator("#recorder-status")).to_have_text(
        re.compile(r"^(Sending your answer|Uploading|Transcribing your answer)"))
    expect(page.locator("#transcript-list").get_by_text("(voice answer, transcribing…)")).to_be_visible()
    page.wait_for_function("window.__liveTracks() === 0")  # mic released right after stop
    page.screenshot(path=str(SHOTS / "voice-desktop-2-transcribing.png"), full_page=True)
    fake.release_voice()

    im.expect_question(page, PLAN[1][2])
    assert WEBM_MAGIC in fake.uploads[0], "upload is not webm"
    expect(page.locator("#transcript-list").get_by_text(
        "Um, so basically this is my spoken answer number 1.")).to_be_visible()
    expect(page.get_by_role("heading", name="How you sounded")).to_be_visible()
    expect(page.get_by_text("138 words per minute")).to_be_visible()
    expect(page.get_by_text("Ideal pace is roughly 120–160 WPM", exact=False)).to_be_visible()
    expect(page.get_by_text("“um” ×2", exact=False)).to_be_visible()
    page.wait_for_function("window.__spoken.length >= 2")
    assert spoken(page)[-1] == PLAN[1][2]
    page.screenshot(path=str(SHOTS / "voice-desktop-3-metrics.png"), full_page=True)

    # Transcription outage: the recording is kept; "Retry upload" sends the same bytes again.
    fake.voice_fail_next.append((503, "stt_unavailable"))
    record_for(page, 1.5)
    expect(page.locator("main").get_by_role("alert")).to_contain_text("couldn't transcribe")
    expect(page.get_by_text("Your recording is saved on this page.")).to_be_visible()
    page.screenshot(path=str(SHOTS / "voice-desktop-4-stt-503.png"), full_page=True)
    page.get_by_role("button", name="Retry upload").first.click()
    im.expect_question(page, PLAN[2][2])
    assert fake.uploads[-1].split(b"\r\n\r\n", 2)[-1] == fake.uploads[-2].split(b"\r\n\r\n", 2)[-1]

    # Mute: persisted, so the next question (and a reload) stays silent; Replay still speaks.
    before = len(spoken(page))
    mute = page.get_by_role("button", name="Mute voice")
    mute.click()
    expect(mute).to_have_attribute("aria-pressed", "true")
    record_for(page, 1.2, keyboard=True)
    im.expect_question(page, PLAN[3][2])
    page.wait_for_timeout(300)
    assert len(spoken(page)) == before, "spoke while muted"
    page.reload()
    im.expect_question(page, PLAN[3][2])
    expect(page.get_by_role("button", name="Mute voice")).to_have_attribute("aria-pressed", "true")
    page.wait_for_timeout(300)
    assert spoken(page) == [], "spoke after reload while muted"
    page.get_by_role("button", name="Replay the question out loud").click()
    page.wait_for_function("window.__spoken.length === 1")
    page.get_by_role("button", name="Mute voice").click()  # unmute again

    # Switch to text mode and answer by typing: first-class alternative.
    page.get_by_text("Text", exact=True).click()
    expect(page.get_by_role("radio", name="Text")).to_be_checked()
    expect(im.answer_box(page)).to_be_focused()
    im.send(page, "A typed answer after switching modes.")
    im.expect_question(page, PLAN[4][2])
    expect(page.get_by_role("heading", name="How you sounded")).to_have_count(0)
    assert page.evaluate("window.__liveTracks()") == 0
    page.context.close()


def mic_denied(browser) -> None:
    fake = FakeVoiceInterview()
    page = new_page(browser, viewport={"width": 390, "height": 844},
                    extra_init="window.__denyMic = true;")
    started(page, fake, practice=False)
    record_button(page).click()
    alert = page.get_by_role("alert")
    expect(alert).to_contain_text("Microphone access is blocked")
    im.no_horizontal_scroll(page)
    page.screenshot(path=str(SHOTS / "voice-mic-denied.png"), full_page=True)
    page.get_by_role("button", name="Type your answer instead").click()
    expect(im.answer_box(page)).to_be_focused()
    im.send(page, "Typed because the microphone is blocked.")
    im.expect_question(page, PLAN[1][2])
    assert fake.uploads == []
    page.context.close()


def unsupported_browser(browser) -> None:
    fake = FakeVoiceInterview()
    page = new_page(browser, viewport={"width": 1280, "height": 900},
                    extra_init="delete window.MediaRecorder;")
    started(page, fake, practice=False)
    expect(page.get_by_role("radio", name="Voice")).to_be_disabled()
    expect(page.get_by_role("radio", name="Text")).to_be_checked()
    expect(page.get_by_text("This browser can't record audio", exact=False)).to_be_visible()
    expect(im.answer_box(page)).to_be_visible()
    page.context.close()


def mobile_voice(browser, *, dark: bool) -> None:
    fake = FakeVoiceInterview()
    page = new_page(browser, viewport={"width": 390, "height": 844}, dark=dark)
    started(page, fake, practice=True)
    tag = "voice-mobile-dark" if dark else "voice-mobile"
    expect(record_button(page)).to_be_visible()
    box = record_button(page).bounding_box()
    assert box and box["width"] >= 44 and box["height"] >= 44, box  # touch target
    im.no_horizontal_scroll(page)
    page.screenshot(path=str(SHOTS / f"{tag}-1-ready.png"), full_page=True)
    for i in range(2):
        record_for(page, 1.3)
        im.expect_question(page, PLAN[i + 1][2])
    expect(page.get_by_role("heading", name="How you sounded")).to_be_visible()
    im.no_horizontal_scroll(page)
    page.screenshot(path=str(SHOTS / f"{tag}-2-metrics.png"), full_page=True)
    assert page.evaluate("window.__liveTracks()") == 0
    page.context.close()


def main() -> int:
    t0 = time.time()
    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chrome",
            args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"],
        )
        for name, fn in [
            ("desktop voice: TTS, keyboard record, meter, upload, metrics, 503 retry, mute, text",
             desktop_voice),
            ("mic denied -> text fallback (390x844)", mic_denied),
            ("no MediaRecorder -> voice disabled", unsupported_browser),
            ("mobile 390x844 voice light", lambda b: mobile_voice(b, dark=False)),
            ("mobile 390x844 voice dark + reduced motion", lambda b: mobile_voice(b, dark=True)),
        ]:
            try:
                fn(browser)
            except Exception:
                print("console errors so far:", *im.console_errors, sep="\n  ")
                raise
            print(f"PASS  {name}")
        browser.close()
    if im.console_errors:
        print("FAIL  console errors:", *im.console_errors, sep="\n  ")
        return 1
    print(f"PASS  no console errors ({time.time() - t0:.1f}s); screenshots in {SHOTS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
