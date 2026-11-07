"""Ponto de entrada do aplicativo."""


def launch_app() -> None:
    from .ui import launch_app as run_ui

    run_ui()


def main() -> None:
    launch_app()


if __name__ == "__main__":
    main()
