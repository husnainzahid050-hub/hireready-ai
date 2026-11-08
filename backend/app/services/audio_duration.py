"""Cheap, header-only duration estimate for uploaded audio (security re-audit, finding S2-1).

Why: Groq bills (and rate-limits) Whisper by AUDIO SECONDS, not bytes. A 3 MB file encoded at a
very low bitrate (opus at 6 kbit/s, mp3 at 8 kbit/s, a silent FLAC) holds 30-60+ minutes of
audio, and our 120 s check used to run only AFTER Whisper had transcribed (and billed) all of
it. One such upload burns a large share of the free tier's hourly audio budget for every user.

This module reads the duration a container DECLARES in its headers (no decoding, no extra
dependency) so obviously long files are refused before the quota is charged and before Groq is
called. It is best effort: headers can lie, and some browser recordings carry no duration at
all (Chrome's WebM, fragmented MP4). Those return None ("unknown") and are allowed; the
per-session over-length strike limit in `app.services.voice_answer` bounds what a crafted file
can still cost.

All parsers are defensive: any malformed or truncated header just returns None.
"""

import struct
from typing import Final


class UnsupportedCodecError(ValueError):
    """A container we accept, holding a codec browsers never produce (e.g. ADPCM/GSM in WAV)."""


# WAVE format tags: PCM, IEEE float, WAVE_FORMAT_EXTENSIBLE (browsers / OS recorders).
_WAV_PCM_TAGS: Final = {0x0001, 0x0003, 0xFFFE}
_MP3_SEARCH_BYTES: Final = 64 * 1024
_WEBM_HEADER_BYTES: Final = 8 * 1024


def estimate_duration_s(data: bytes, container: str) -> float | None:
    """Declared duration in seconds, or None when the headers don't say (or can't be read).

    Raises UnsupportedCodecError for a compressed WAV (a cheap way to pack hours into 3 MB).
    """
    parser = _PARSERS.get(container)
    if parser is None:
        return None
    try:
        value = parser(data)
    except UnsupportedCodecError:
        raise
    except (struct.error, IndexError, ValueError, ZeroDivisionError, OverflowError):
        return None
    if value is None or value != value or value < 0 or value == float("inf"):  # NaN/negative
        return None
    return value


# ------------------------------------------------------------------ WAV


def _wav(data: bytes) -> float | None:
    pos = 12  # "RIFF" size "WAVE"
    rate = channels = bits = 0
    while pos + 8 <= len(data):
        cid = data[pos : pos + 4]
        size = struct.unpack_from("<I", data, pos + 4)[0]
        body = pos + 8
        if cid == b"fmt " and size >= 16:
            tag, channels, rate = struct.unpack_from("<HHI", data, body)
            bits = struct.unpack_from("<H", data, body + 14)[0]
            if tag not in _WAV_PCM_TAGS:
                raise UnsupportedCodecError(f"wav format 0x{tag:04x}")
        elif cid == b"data":
            frame = rate * channels * bits / 8
            if frame <= 0:
                return None
            # The declared size may be bogus (0, 0xFFFFFFFF for streams): use what we received.
            available = len(data) - body
            return float(min(size, available) / frame)
        pos = body + size + (size & 1)  # chunks are word-aligned
    return None


# ------------------------------------------------------------------ Ogg (opus / vorbis)


def _ogg(data: bytes) -> float | None:
    # First page: 27-byte header + segment table, then the codec's identification packet.
    segments = data[26]
    payload = 27 + segments
    head = data[payload : payload + 16]
    if head.startswith(b"OpusHead"):
        rate = 48_000  # Opus granule positions always count 48 kHz samples
    elif head.startswith(b"\x01vorbis"):
        rate = struct.unpack_from("<I", data, payload + 12)[0]
    else:
        return None
    last = data.rfind(b"OggS")
    if last <= 0 or last + 14 > len(data):
        return None
    granule = struct.unpack_from("<q", data, last + 6)[0]
    if granule <= 0 or rate <= 0:
        return None
    return float(granule / rate)


# ------------------------------------------------------------------ FLAC


def _flac(data: bytes) -> float | None:
    # "fLaC", then the mandatory STREAMINFO block (4-byte block header + 34 bytes).
    if data[4] & 0x7F != 0:
        return None
    info = data[8:42]
    packed = int.from_bytes(info[10:18], "big")
    rate = packed >> 44  # 20 bits
    total_samples = packed & ((1 << 36) - 1)  # 36 bits
    if rate <= 0 or total_samples <= 0:
        return None
    return total_samples / rate


# ------------------------------------------------------------------ MP4 / M4A


def _mp4(data: bytes) -> float | None:
    idx = data.find(b"mvhd")
    if idx < 4:
        return None
    version = data[idx + 4]
    if version == 1:
        timescale, duration = struct.unpack_from(">IQ", data, idx + 24)
    else:
        timescale, duration = struct.unpack_from(">II", data, idx + 16)
    if timescale <= 0 or duration <= 0 or duration == 0xFFFFFFFF:
        return None  # fragmented MP4 (Safari's recorder) may leave the duration unset
    return float(duration / timescale)


# ------------------------------------------------------------------ WebM / Matroska


def _webm(data: bytes) -> float | None:
    # Only look in the header area (before the first Cluster), so audio bytes can't match.
    head = data[:_WEBM_HEADER_BYTES]
    cluster = head.find(b"\x1f\x43\xb6\x75")
    if cluster > 0:
        head = head[:cluster]
    idx = head.find(b"\x44\x89")  # Segment Info > Duration (float, in TimecodeScale units)
    if idx < 0 or idx + 3 > len(head):
        return None
    size_byte = head[idx + 2]
    if size_byte == 0x84:
        (value,) = struct.unpack_from(">f", head, idx + 3)
    elif size_byte == 0x88:
        (value,) = struct.unpack_from(">d", head, idx + 3)
    else:
        return None
    scale = 1_000_000  # default TimecodeScale: 1 ms
    ts = head.find(b"\x2a\xd7\xb1")
    if ts >= 0 and ts + 4 <= len(head):
        n = head[ts + 3] & 0x0F if head[ts + 3] & 0xF0 == 0x80 else 0
        if 1 <= n <= 8 and ts + 4 + n <= len(head):
            scale = int.from_bytes(head[ts + 4 : ts + 4 + n], "big")
    return float(value) * scale / 1e9


# ------------------------------------------------------------------ MP3

# kbit/s for MPEG-1 Layer III and MPEG-2/2.5 Layer III (index 0 = free, 15 = bad).
_MP3_BITRATES: Final = {
    3: (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0),
    2: (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0),
}
_MP3_RATES: Final = {3: (44100, 48000, 32000), 2: (22050, 24000, 16000), 0: (11025, 12000, 8000)}


def _mp3(data: bytes) -> float | None:
    start = 0
    if data.startswith(b"ID3") and len(data) >= 10:
        b = data[6:10]  # syncsafe size
        start = 10 + ((b[0] & 0x7F) << 21 | (b[1] & 0x7F) << 14 | (b[2] & 0x7F) << 7 | b[3] & 0x7F)
    end = min(len(data) - 4, start + _MP3_SEARCH_BYTES)
    for i in range(start, max(start, end)):
        if data[i] != 0xFF or data[i + 1] & 0xE0 != 0xE0:
            continue
        version = (data[i + 1] >> 3) & 0x03  # 3 = MPEG-1, 2 = MPEG-2, 0 = MPEG-2.5
        layer = (data[i + 1] >> 1) & 0x03  # 1 = Layer III
        br_idx = data[i + 2] >> 4
        sr_idx = (data[i + 2] >> 2) & 0x03
        if version == 1 or layer != 1 or sr_idx == 3 or br_idx in (0, 15):
            continue
        rate = _MP3_RATES[version][sr_idx]
        kbps = _MP3_BITRATES[3 if version == 3 else 2][br_idx]
        samples_per_frame = 1152 if version == 3 else 576
        frames = _xing_frames(data, i, version, channel_mode=data[i + 3] >> 6)
        if frames:
            return frames * samples_per_frame / rate
        return (len(data) - i) * 8 / (kbps * 1000)
    return None


def _xing_frames(data: bytes, frame: int, version: int, channel_mode: int) -> int | None:
    mono = channel_mode == 3
    side_info = (17 if mono else 32) if version == 3 else (9 if mono else 17)
    pos = frame + 4 + side_info
    tag = data[pos : pos + 4]
    if tag not in (b"Xing", b"Info"):
        return None
    flags = struct.unpack_from(">I", data, pos + 4)[0]
    if not flags & 0x1:
        return None
    frames: int = struct.unpack_from(">I", data, pos + 8)[0]
    return frames


_PARSERS: Final = {
    "wav": _wav,
    "ogg": _ogg,
    "flac": _flac,
    "mp4": _mp4,
    "webm": _webm,
    "mp3": _mp3,
}
