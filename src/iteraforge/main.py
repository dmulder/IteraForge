from __future__ import annotations

import os

import uvicorn


def main() -> None:
    port = int(os.environ.get("ITERAFORGE_PORT", "8765"))
    uvicorn.run("iteraforge.app:create_app", factory=True, host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
