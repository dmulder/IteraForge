from __future__ import annotations

import time


def main() -> None:
    # The web container currently owns job execution so it can stream state to the UI.
    # This process is installed as the stable host-side integration point for moving
    # agent execution out of the web process without changing the UI or API.
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
