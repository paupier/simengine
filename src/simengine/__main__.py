"""simengine entry point: REST/UI on :8080, publishers per scenario comms.

Usage:
    python -m simengine                          # API/UI only; start runs via REST
    python -m simengine --scenario demo_line --seed 42
    python -m simengine --recipe monday_schedule --seed 42
    python -m simengine --scenario demo_line --speed-ratio 10 --port 8080
"""
import argparse
import logging
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(prog="simengine")
    parser.add_argument("--scenario", help="start this scenario immediately")
    parser.add_argument("--recipe", help="start this recipe immediately")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--speed-ratio", type=float, default=1.0,
                        help="sim seconds per wall second (1.0 = real time)")
    parser.add_argument("--port", type=int, default=8080, help="REST/UI port")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    logging.getLogger("opcua").setLevel(logging.WARNING)

    from simengine.api.rest import create_app
    from simengine.runtime.run_manager import RunManager

    run_manager = RunManager()

    if args.scenario and args.recipe:
        parser.error("--scenario and --recipe are mutually exclusive")
    if args.scenario:
        run_id = run_manager.start(args.scenario, seed=args.seed,
                                   speed_ratio=args.speed_ratio)
        print(f"run started: {run_id}")
    elif args.recipe:
        run_id = run_manager.start_recipe(args.recipe, seed=args.seed,
                                          speed_ratio=args.speed_ratio)
        print(f"recipe run started: {run_id}")

    app = create_app(run_manager)
    print(f"REST/UI listening on http://0.0.0.0:{args.port}/")
    try:
        app.run(host="0.0.0.0", port=args.port, threaded=True,
                use_reloader=False)
    except KeyboardInterrupt:
        pass
    finally:
        run_manager.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
