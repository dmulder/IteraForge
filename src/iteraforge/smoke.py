from __future__ import annotations

from .app import create_app
from .paths import config_home, data_home
from .tabs import list_tabs


def main() -> None:
    app = create_app()
    assert app.title == "IteraForge"
    assert config_home().exists()
    assert data_home().exists()
    assert isinstance(list_tabs(), list)
    print("IteraForge smoke check passed")


if __name__ == "__main__":
    main()
