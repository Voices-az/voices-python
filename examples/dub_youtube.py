"""Dub a YouTube video into another language and download the result.

    export VOICES_API_KEY=vz_live_...
    python examples/dub_youtube.py "https://www.youtube.com/watch?v=..." --to az -o dubbed.mp4

Creating the project and the first previews are free; the full dub charges your balance
at the dubbing per-minute rate (the quote is printed before you confirm). Downloading a
paid dub is free.
"""

from __future__ import annotations

import argparse
import sys

import voices_az


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("url", help="YouTube watch URL")
    parser.add_argument("--to", default="az", help="language to dub into (default: az)")
    parser.add_argument("--from", dest="source", help="spoken language (detected if omitted)")
    parser.add_argument("-o", "--output", default="dubbed.mp4", help="where to save the mp4")
    parser.add_argument("--preview", action="store_true",
                        help="make a short preview first and print its link")
    parser.add_argument("--yes", action="store_true", help="do not ask before charging")
    args = parser.parse_args()

    def progress(status: voices_az.types.DubbingStatus) -> None:
        print(f"  {status.stage or status.status} {status.percentage or 0}%", file=sys.stderr)

    with voices_az.Client() as client:
        draft = client.dubbing.create(youtube_url=args.url, target_language=args.to,
                                      source_language=args.source)
        price = f"{draft.price.amount} {draft.price.currency}" if draft.price else "unknown"
        print(f"Project {draft.project_id} created; full dub price: {price}")

        if args.preview:
            run = client.dubbing.preview(draft.project_id)
            status = client.dubbing.wait(run.request_id, on_progress=progress)
            print(f"Preview: {status.preview_audio_url or status.audio_url}")

        if not args.yes and input("Dub the whole video and charge the balance? [y/N] ") != "y":
            print("Stopped. The draft stays in your projects.")
            return 0

        try:
            run = client.dubbing.generate(draft.project_id)  # charges the balance
        except voices_az.InsufficientBalanceError as exc:
            print(f"Not enough balance: {exc.missing} {exc.currency} missing.", file=sys.stderr)
            return 1
        client.dubbing.wait(run.request_id, on_progress=progress)

        path = client.dubbing.download(draft.project_id, args.output)
        print(f"Saved {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
