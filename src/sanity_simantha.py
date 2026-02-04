from simantha import Source, Machine, Buffer, Sink, System


def main():
    source = Source()
    M1 = Machine(name="M1", cycle_time=1)
    B1 = Buffer(name="B1", capacity=5)
    M2 = Machine(name="M2", cycle_time=1)
    sink = Sink(collect_parts=True)

    source.define_routing(downstream=[M1])
    M1.define_routing(upstream=[source], downstream=[B1])
    B1.define_routing(upstream=[M1], downstream=[M2])
    M2.define_routing(upstream=[B1], downstream=[sink])
    sink.define_routing(upstream=[M2])  # important[web:15][web:20]

    system = System(objects=[source, M1, B1, M2, sink])
    system.simulate(simulation_time=100)
    print("Parts produced:", sink.level)


if __name__ == "__main__":
    main()
