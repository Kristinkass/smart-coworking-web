"""Tests for /mapp page performance."""
import time


def test_mapp_page_loads_fast(auth_client, app):
    started = time.perf_counter()
    r = auth_client.get('/mapp')
    elapsed = time.perf_counter() - started
    assert r.status_code == 200
    assert elapsed < 1.0, f'/mapp слишком медленный: {elapsed:.2f}s'
    assert b'map_updated.js' in r.data
