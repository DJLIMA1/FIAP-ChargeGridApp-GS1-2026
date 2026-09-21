import flet as ft

from .app import ASSETS_DIR, main


def run():
    ft.run(main, assets_dir=ASSETS_DIR)


if __name__ == '__main__':
    run()
