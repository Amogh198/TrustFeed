"""Text lane commands. The downloads are the only things here that use the network."""

import argparse

from backend.text.ner import MODEL_ID, MODEL_REVISION
from backend.text.ner import download_model as download_ner
from backend.text.verify_models import download_models as download_verification


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m backend.text")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("download-ner", help=f"download {MODEL_ID} at revision {MODEL_REVISION[:7]} (about 433 MB)")
    commands.add_parser("download-verification", help="download the two claim comparison models (about 470 MB)")
    args = parser.parse_args()
    if args.command == "download-ner":
        print(download_ner())
    else:
        print("\n".join(download_verification()))


if __name__ == "__main__":
    main()
