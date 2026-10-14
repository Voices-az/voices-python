"""Transcribe an audio or video file and print the text (optionally save subtitles).

    export VOICES_API_KEY=vz_live_...
    python examples/transcribe_file.py interview.mp3 --language az --speakers 2 --srt out.srt

Recognition charges your balance when it starts, at the speech-to-text per-minute rate.
"""

from __future__ import annotations

import argparse
import sys

import voices_az


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("file", help="audio or video file")
    parser.add_argument("--language", default="az", help="language spoken (default: az)")
    parser.add_argument("--speakers", type=int, default=1, help="speakers to separate (1-10)")
    parser.add_argument("--remove-background", action="store_true",
                        help="strip music and noise first (slower, better on noisy audio)")
    parser.add_argument("--srt", help="also save SRT subtitles to this path")
    args = parser.parse_args()

    with voices_az.Client() as client:
        try:
            transcript = client.stt.recognize(
                args.file,
                language=args.language,
                speakers=args.speakers,
                remove_background=args.remove_background,
                on_progress=lambda t: print(f"  {t.percentage or 0}%", file=sys.stderr),
            )
        except voices_az.InsufficientBalanceError as exc:
            print(f"Not enough balance: {exc.missing} {exc.currency} missing.", file=sys.stderr)
            return 1

        for segment in transcript.segments:
            print(f"[{segment.start:7.2f} - {segment.end:7.2f}] {segment.text}")

        if args.srt:
            path = client.stt.download(transcript.project_id, args.srt, format="srt")
            print(f"Saved {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
