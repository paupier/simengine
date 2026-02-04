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

    # Existing global controls
    var_pause_line = controls_node.add_variable(idx, "PauseLine", False)
    var_interarrival = controls_node.add_variable(idx, "InterarrivalTime", 0.0)

    # New station-level pause controls
    var_pause_line1 = controls_node.add_variable(idx, "PauseLine1", False)
    var_pause_line2 = controls_node.add_variable(idx, "PauseLine2", False)

    # New per-machine cycle time controls
    var_m1_cycle = controls_node.add_variable(idx, "M1_CycleTime", 1.0)
    var_m2_cycle = controls_node.add_variable(idx, "M2_CycleTime", 1.0)

    # Station 1 (M1)
    station1_node = line1.add_object(idx, "Station1")
    var_m1_state = station1_node.add_variable(idx, "State", "IDLE")
    var_m1_partcount = station1_node.add_variable(idx, "PartCount", 0)
    var_m1_util = station1_node.add_variable(idx, "Utilisation", 0.0)

    # Buffer between Station1 and Station2
    buffer1_node = line1.add_object(idx, "Buffer1")
    var_b1_level = buffer1_node.add_variable(idx, "CurrentLevel", 0)
    var_b1_capacity = buffer1_node.add_variable(idx, "Capacity", 10)

    # New Station 2 (M2)
    station2_node = line1.add_object(idx, "Station2")
    var_m2_state = station2_node.add_variable(idx, "State", "IDLE")
    var_m2_partcount = station2_node.add_variable(idx, "PartCount", 0)
    var_m2_util = station2_node.add_variable(idx, "Utilisation", 0.0)

    # Make all variables writable so client can change controls (and metrics if needed)
    for v in (
        var_simtime,
        var_throughput,
        var_total_wip,
        var_pause_line,
        var_interarrival,
        var_pause_line1,
        var_pause_line2,
        var_m1_cycle,
        var_m2_cycle,
        var_m1_state,
        var_m1_partcount,
        var_m1_util,
        var_b1_level,
        var_b1_capacity,
        var_m2_state,
        var_m2_partcount,
        var_m2_util,
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
        "pause_line1": var_pause_line1,
        "pause_line2": var_pause_line2,
        "m1_cycle": var_m1_cycle,
        "m2_cycle": var_m2_cycle,
        # Station / buffer
        "m1_state": var_m1_state,
        "m1_partcount": var_m1_partcount,
        "m1_utilisation": var_m1_util,
        "b1_level": var_b1_level,
        "b1_capacity": var_b1_capacity,
        # Station 2
        "m2_state": var_m2_state,
        "m2_partcount": var_m2_partcount,
        "m2_utilisation": var_m2_util,
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
            pause_line1 = bool(vars_["pause_line1"].get_value())
            pause_line2 = bool(vars_["pause_line2"].get_value())
            interarrival = float(vars_["interarrival_time"].get_value())
            m1_cycle = float(vars_["m1_cycle"].get_value())
            m2_cycle = float(vars_["m2_cycle"].get_value())

            # Basic safety clamps
            if interarrival < 0.0:
                interarrival = 0.0
            if m1_cycle <= 0.0:
                m1_cycle = 1.0
            if m2_cycle <= 0.0:
                m2_cycle = 1.0

            # Push into Simantha
            # 0.0 means "never starved"; >0 slows arrivals.[web:16][web:17]
            source.interarrival_time = interarrival
            m1.cycle_time = m1_cycle
            m2.cycle_time = m2_cycle

            # --- Stepping: same pattern as before ---
            if not pause_line:
                # Advance simulation only when not paused
                sim_time += sim_step
                system.simulate(simulation_time=sim_time)

            # --- Compute metrics using Simantha ---
            current_sim_time = sim_time

            # Throughput from sink
            parts_produced = sink.level  # finished parts in sink[web:16][web:17]
            current_throughput = parts_produced

            # Simple station part counts (series line: both see same outflow)
            m1_partcount = parts_produced
            m2_partcount = parts_produced

            # Buffer WIP from B1
            try:
                b1_level = b1.level  # or len(b1.contents)[web:17]
            except AttributeError:
                b1_level = 0

            b1_capacity = b1.capacity
            total_wip = b1_level

            # Utilisation and state, using global + station pauses
            if pause_line or sim_time <= 0:
                m1_utilisation = 0.0
                m2_utilisation = 0.0
                m1_state = "PAUSED" if pause_line else "IDLE"
                m2_state = "PAUSED" if pause_line else "IDLE"
            else:
                # Line not globally paused; apply station pauses
                if pause_line1:
                    m1_utilisation = 0.0
                    m1_state = "PAUSED"
                else:
                    m1_utilisation = 1.0
                    m1_state = "RUNNING"

                if pause_line2:
                    m2_utilisation = 0.0
                    m2_state = "PAUSED"
                else:
                    m2_utilisation = 1.0
                    m2_state = "RUNNING"

            # --- Write KPIs back to OPC UA ---
            vars_["simtime"].set_value(current_sim_time)
            vars_["throughput"].set_value(current_throughput)
            vars_["total_wip"].set_value(total_wip)

            vars_["m1_partcount"].set_value(m1_partcount)
            vars_["m1_state"].set_value(m1_state)
            vars_["m1_utilisation"].set_value(m1_utilisation)

            vars_["b1_level"].set_value(b1_level)
            vars_["b1_capacity"].set_value(b1_capacity)

            vars_["m2_partcount"].set_value(m2_partcount)
            vars_["m2_state"].set_value(m2_state)
            vars_["m2_utilisation"].set_value(m2_utilisation)

            time.sleep(real_step)

    except KeyboardInterrupt:
        print("Stopping server...")
    finally:
        server.stop()
        print("Server stopped.")



if __name__ == "__main__":
    main()