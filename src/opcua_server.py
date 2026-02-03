import time

from opcua import Server
from simantha import Source, Machine, Buffer, Sink, System


def build_simantha_system():
    source = Source()
    m1 = Machine(name="M1", cycle_time=1)
    b1 = Buffer(name="B1", capacity=10)
    m2 = Machine(name="M2", cycle_time=1)
    sink = Sink(collect_parts=True)

    source.define_routing(downstream=[m1])
    m1.define_routing(upstream=[source], downstream=[b1])
    b1.define_routing(upstream=[m1], downstream=[m2])
    m2.define_routing(upstream=[b1], downstream=[sink])

    system = System(objects=[source, m1, b1, m2, sink])
    return system, source, sink, b1, m1, m2


def build_opcua_server():
    server = Server()
    server.set_endpoint("opc.tcp://0.0.0.0:4840/simantha/")

    uri = "http://simantha.nist.gov/"
    idx = server.register_namespace(uri)

    objects = server.get_objects_node()

    # Top-level line object
    line1 = objects.add_object(idx, "Line1")

    # System / KPIs under the line
    system_node = line1.add_object(idx, "System")
    var_simtime = system_node.add_variable(idx, "SimTime", 0.0)
    var_throughput = system_node.add_variable(idx, "Throughput", 0)

    # Line-level KPIs
    line_kpi_node = line1.add_object(idx, "LineKPIs")
    var_total_wip = line_kpi_node.add_variable(idx, "TotalWIP", 0)

    # System controls (inputs into Simantha)
    controls_node = system_node.add_object(idx, "Controls")
    var_pause_line = controls_node.add_variable(idx, "PauseLine", False)
    var_interarrival = controls_node.add_variable(idx, "InterarrivalTime", 0.0)

    # Station 1 (M1)
    station1_node = line1.add_object(idx, "Station1")
    var_m1_state = station1_node.add_variable(idx, "State", "IDLE")
    var_m1_partcount = station1_node.add_variable(idx, "PartCount", 0)
    var_m1_util = station1_node.add_variable(idx, "Utilisation", 0.0)

    # Buffer between Station1 and Station2
    buffer1_node = line1.add_object(idx, "Buffer1")
    var_b1_level = buffer1_node.add_variable(idx, "CurrentLevel", 0)
    var_b1_capacity = buffer1_node.add_variable(idx, "Capacity", 10)

    # Make all variables writable so client can change controls (and metrics if needed)
    for v in (
        var_simtime,
        var_throughput,
        var_total_wip,
        var_pause_line,
        var_interarrival,
        var_m1_state,
        var_m1_partcount,
        var_m1_util,
        var_b1_level,
        var_b1_capacity,
    ):
        v.set_writable()

    variables = {
        # KPIs
        "simtime": var_simtime,
        "throughput": var_throughput,
        "total_wip": var_total_wip,
        # Controls
        "pause_line": var_pause_line,
        "interarrival_time": var_interarrival,
        # Station / buffer
        "m1_state": var_m1_state,
        "m1_partcount": var_m1_partcount,
        "m1_utilisation": var_m1_util,
        "b1_level": var_b1_level,
        "b1_capacity": var_b1_capacity,
    }

    return server, variables, idx


def main():
    system, source, sink, b1, m1, m2 = build_simantha_system()

    server, vars_, idx = build_opcua_server()

    sim_time = 0.0
    sim_step = 1.0
    real_step = 1.0

    server.start()
    print("OPC UA server started at opc.tcp://localhost:4840/simantha/")
    print("Press Ctrl+C to stop.")

    try:
        while True:
            # --- Read controls from OPC UA ---
            pause_line = bool(vars_["pause_line"].get_value())
            interarrival = float(vars_["interarrival_time"].get_value())

            # Push interarrival time into Simantha source
            # 0.0 means "never starved" per Simantha docs; >0 slows arrivals.[web:181]
            source.interarrival_time = interarrival

            if not pause_line:
                # Advance simulation only when not paused
                sim_time += sim_step
                system.simulate(simulation_time=sim_time)

            # --- Compute simple metrics (still placeholders) ---
            current_sim_time = sim_time
            current_throughput = int(sim_time)  # placeholder for parts out
            m1_partcount = current_throughput

            try:
                b1_level = len(b1.queue)
            except AttributeError:
                b1_level = 0

            b1_capacity = b1.capacity

            # Very rough utilisation: running whenever not paused and sim_time > 0
            if pause_line or sim_time <= 0:
                m1_utilisation = 0.0
                m1_state = "PAUSED" if pause_line else "IDLE"
            else:
                m1_utilisation = 1.0
                m1_state = "RUNNING"

            total_wip = b1_level

            # --- Write KPIs back to OPC UA ---
            vars_["simtime"].set_value(current_sim_time)
            vars_["throughput"].set_value(current_throughput)
            vars_["total_wip"].set_value(total_wip)
            vars_["m1_partcount"].set_value(m1_partcount)
            vars_["b1_level"].set_value(b1_level)
            vars_["b1_capacity"].set_value(b1_capacity)
            vars_["m1_state"].set_value(m1_state)
            vars_["m1_utilisation"].set_value(m1_utilisation)

            time.sleep(real_step)

    except KeyboardInterrupt:
        print("Stopping server...")
    finally:
        server.stop()
        print("Server stopped.")


if __name__ == "__main__":
    main()
