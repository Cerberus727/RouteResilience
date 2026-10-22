"""OSM ingestion on a tiny synthetic .osm.pbf written with pyosmium (skipped if pyosmium is absent)."""

import importlib.util
import time

import pytest

pytestmark = pytest.mark.skipif(importlib.util.find_spec("osmium") is None, reason="pyosmium not installed")


def write_pbf(path):
    import osmium

    w = osmium.SimpleWriter(str(path))
    try:
        coords = {1: (80.000, 13.000), 2: (80.001, 13.000), 3: (80.002, 13.000), 4: (80.001, 13.001),
                  5: (85.000, 15.000), 6: (85.001, 15.000), 7: (80.0015, 13.0005)}
        for nid, (lon, lat) in coords.items():
            tags = {"place": "suburb", "name": "Testpet"} if nid == 7 else {}
            w.add_node(osmium.osm.mutable.Node(id=nid, location=(lon, lat), tags=tags))
        w.add_way(osmium.osm.mutable.Way(id=100, nodes=[1, 2, 3], tags={"highway": "residential", "name": "Main Street"}))
        w.add_way(osmium.osm.mutable.Way(id=101, nodes=[2, 4], tags={"highway": "primary", "oneway": "yes"}))
        w.add_way(osmium.osm.mutable.Way(id=102, nodes=[1, 4], tags={"highway": "footway"}))  # not drivable
        w.add_way(osmium.osm.mutable.Way(id=103, nodes=[3, 4], tags={"highway": "service", "service": "parking_aisle"}))  # excluded
        w.add_way(osmium.osm.mutable.Way(id=104, nodes=[5, 6], tags={"highway": "primary"}))  # outside extent
    finally:
        w.close()


def test_build_index_from_pbf(tmp_path):
    from app.geo.network import split_ways
    from app.geo.osm_index import Extent, IndexJob, connect, extents, query_ways, run_isolated, search_places

    pbf = tmp_path / "tiny.osm.pbf"
    write_pbf(pbf)
    db = tmp_path / "cache" / "osm_roads.sqlite"
    job = IndexJob(state="running", started_at=time.time())
    run_isolated(pbf, db, Extent(79.99, 12.99, 80.01, 13.01), job, tmp_path / "cache" / "tmp")  # same path as the API/CLI
    assert job.roads_kept == 2 and job.places_kept == 1
    con = connect(db)
    ways = query_ways(con, Extent(79.99, 12.99, 80.01, 13.01))
    assert [w.id for w in ways] == [100, 101]
    main = ways[0]
    assert main.node_ids == [1, 2, 3] and main.tags["name"] == "Main Street"
    assert main.coords[1] == pytest.approx((80.001, 13.0))  # real lon/lat preserved
    assert ways[1].tags["oneway"] == "yes"
    assert extents(con)[0]["roads"] == 2
    assert search_places(con, "testp")[0]["name"] == "Testpet"
    segs = split_ways(ways)
    assert sorted(s.id for s in segs) == ["100:0", "100:1", "101:0"]  # split at shared node 2
    con.close()
    # the temporary node-location file must not be left behind
    assert not list((tmp_path / "cache" / "tmp").glob("node_locations*.bin")), job.log


def test_isolated_build_reports_errors(tmp_path):
    from app.geo.osm_index import Extent, IndexError_, IndexJob, run_isolated

    bad = tmp_path / "broken.osm.pbf"
    bad.write_bytes(b"this is not a pbf")
    job = IndexJob(state="running", started_at=time.time())
    with pytest.raises(IndexError_):
        run_isolated(bad, tmp_path / "db.sqlite", Extent(79.99, 12.99, 80.01, 13.01), job, tmp_path / "tmp")
