from __future__ import annotations

from urllib.request import urlopen

from scientific_extraction_harness.expert_app import create_server


def test_tutorial_route_and_main_link():
    server = create_server(("127.0.0.1", 0))
    try:
        with server:
            import threading
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                with urlopen(f"http://127.0.0.1:{server.server_port}/tutorial") as response:
                    tutorial = response.read().decode("utf-8")
                with urlopen(f"http://127.0.0.1:{server.server_port}/") as response:
                    main_page = response.read().decode("utf-8")
            finally:
                server.shutdown()
                thread.join()
        assert "Руководство эксперта для Windows" in tutorial
        assert "hf auth login" in tutorial
        assert "значение скрыто" in tutorial
        assert "href='/tutorial'" in main_page
    finally:
        server.server_close()
