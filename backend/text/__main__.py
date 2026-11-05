"""Text lane commands. ``download-ner`` is the only thing here that uses the network."""

import argparse

from backend.text.ner import MODEL_ID, MODEL_REVISION, download_model


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m backend.text")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("download-ner", help=f"download {MODEL_ID} at revision {MODEL_REVISION[:7]} (about 433 MB)")
    parser.parse_args()
    print(download_model())


if __name__ == "__main__":
    main()
