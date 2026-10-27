import random
import statistics
import sys
import time
import cProfile
import pstats
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from matching import RouterEta
from routing import IST, MultiVehicleRouter, TimeBuckets, VehicleType
from routing import osm_import
from routing.graph import haversine_m

DATA = Path("data/roads.pkl")
RIDER = (19.0176, 72.8562)      # Dadar, central Mumbai
RADIUS_M = 4000
N_DRIVERS = 10
RUNS = 7
NOW = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)


def main():
    if not DATA.exists():
        sys.exit("data/roads.pkl not found. Build it first (see README).")

    t = time.perf_counter()
    extract = osm_import.load(str(DATA))
    router = MultiVehicleRouter.local(extract, buckets=TimeBuckets(IST))
    print(f"Load + build router: {(time.perf_counter() - t):.1f} s (not part of the 200 ms target)")

    service = router.services[VehicleType.CAR]
    graph = service.backend.graph
    print(f"Nodes: {len(graph.nodes):,}; directed edges: {len(graph.edges):,}")

    rider_node = graph.nearest_node(RIDER, "end")
    rider = graph.nodes[rider_node]
    has_out = [n for n in graph.out if graph.out[n]]
    near = [n for n in has_out if haversine_m(graph.nodes[n], rider) <= RADIUS_M]
    print(f"Nodes within 4 km of rider: {len(near):,}")
    rng = random.Random(1)
    drivers = {f"d{i}": graph.nodes[n] for i, n in enumerate(rng.sample(near, N_DRIVERS))}

    eta = RouterEta(router)

    if "--profile" in sys.argv:
        # Warm up once so profiling focuses on a warm batch request.
        eta.pickup_etas_s(drivers, rider, VehicleType.CAR, NOW)

        profiler = cProfile.Profile()
        profiler.enable()
        eta.pickup_etas_s(drivers, rider, VehicleType.CAR, NOW)
        profiler.disable()

        print("\nTop 30 functions by cumulative time:")
        stats = pstats.Stats(profiler).strip_dirs()
        stats.sort_stats("cumulative").print_stats(30)
        return

    times = []
    for run in range(RUNS):
        t = time.perf_counter()
        batch = eta.pickup_etas_s(drivers, rider, VehicleType.CAR, NOW)
        ms = (time.perf_counter() - t) * 1000
        times.append(ms)
        if run == 0:
            print(f"\nBatch, first (cold) run: {ms:.1f} ms")
    warm = times[1:]
    print(f"Batch, warm median: {statistics.median(warm):.1f} ms; slowest: {max(warm):.1f} ms")

    t = time.perf_counter()
    single = {k: eta.pickup_eta_s(p, rider, VehicleType.CAR, NOW) for k, p in drivers.items()}
    print(f"10 single routes: {(time.perf_counter() - t) * 1000:.1f} ms (the old way)")

    worst = 0.0
    for k in drivers:
        if batch[k] is None or single[k] is None:
            print(f"  {k}: batch={batch[k]} single={single[k]}")
            continue
        worst = max(worst, abs(batch[k] - single[k]))
    print(f"Largest batch vs single difference: {worst:.2f} s")
    pool = rng.sample(near, 50)
    pool.sort(key=lambda n: haversine_m(graph.nodes[n], rider))
    close = {f"c{i}": graph.nodes[n] for i, n in enumerate(pool[:N_DRIVERS])}
    ctimes = []
    for _ in range(RUNS):
        t = time.perf_counter()
        eta.pickup_etas_s(close, rider, VehicleType.CAR, NOW)
        ctimes.append((time.perf_counter() - t) * 1000)
    print(f"\nNearest 10 of 50 drivers: first {ctimes[0]:.1f} ms, "
          f"warm median {statistics.median(ctimes[1:]):.1f} ms")
    print("Real Mumbai graph, one rider, one seed. Run on your machine only.")


if __name__ == "__main__":
    main()