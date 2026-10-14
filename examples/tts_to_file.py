"""Synthesize text and save it as an MP3.

    export VOICES_API_KEY=vz_live_...
    python examples/tts_to_file.py "Salam! Bu Voices.az ilə yaradılmış səsdir." -o salam.mp3

Synthesis is free; downloading the file charges your balance at the text-to-speech
per-minute rate (re-downloading the same project does not charge again). Use --preview-only
to stop after printing the listening link.
"""

from __future__ import annotations

import argparse
import sys

import voices_az


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("text", help="text to read (up to 7000 characters)")
    parser.add_argument("-o", "--output", default="speech.mp3", help="where to save the MP3")
    parser.add_argument("--language", default="az", help="language code (default: az)")
    parser.add_argument("--voice", type=int, help="voice id (see client.voices.list())")
    parser.add_argument("--speed", type=float, default=1, choices=[1, 1.5, 2, 2.5, 3])
    parser.add_argument("--preview-only", action="store_true",
                        help="do not download (and do not charge the balance)")
    args = parser.parse_args()

    with voices_az.Client() as client:  # reads VOICES_API_KEY
        try:
            result = client.tts.synthesize(
                args.text,
                language=args.language,
                voice=args.voice,
                speed=args.speed,
                on_progress=lambda s: print(f"  {s.status} {s.percentage or 0}%"),
            )
        except voices_az.ContentPolicyError as exc:
            print(f"The text was refused: {exc.message}", file=sys.stderr)
            return 1

        print(f"Project {result.project_id}: {result.duration:.1f} s")
        print(f"Listen: {result.preview_url}")
        if args.preview_only:
            return 0

        try:
            path = client.tts.download(result.project_id, args.output)  # charges the balance
        except voices_az.InsufficientBalanceError as exc:
            print(f"Not enough balance: {exc.missing} {exc.currency} missing. "
                  "Top up at https://app.voices.az", file=sys.stderr)
            return 1
        print(f"Saved {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
