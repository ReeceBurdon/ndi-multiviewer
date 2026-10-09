import argparse
import multiprocessing
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from .app import MainWindow


def main() -> int:
    # Packaged builds start the format helper process by re-running this executable.
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser(prog="ndi-multiviewer", description="Watch several NDI sources in a grid.")
    parser.add_argument("--layout", type=Path, help="layout file to open and autosave to (default: per-user config)")
    parser.add_argument(
        "--bandwidth",
        choices=["lowest", "highest"],
        default="lowest",
        help="'lowest' uses each sender's preview stream (default, best for many tiles); 'highest' asks for full quality",
    )
    parser.add_argument("--fullscreen", action="store_true", help="start fullscreen (F11 / Esc to toggle)")
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)  # used by CI on packaged builds
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setApplicationName("ndi-multiviewer")
    win = MainWindow(layout_path=args.layout, bandwidth=args.bandwidth)
    win.show()
    if args.fullscreen:
        win.fullscreen_action.setChecked(True)
    if args.smoke_test:
        # Proves the packaged app starts and the bundled NDI runtime loads.
        import cyndilib

        print(f"NDI runtime: {cyndilib.get_ndi_version()}", flush=True)

        def finish() -> None:
            # The format helper runs as a second copy of the app; make sure that works when packaged.
            ok = win.prober is None or win.prober.is_alive()
            print(f"Format helper running: {ok}", flush=True)
            app.exit(0 if ok else 1)

        QTimer.singleShot(4000, finish)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
