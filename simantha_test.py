from simantha import Source, Machine, Buffer, Sink, System

source = Source()
m1 = Machine(name="M1", cycle_time=1)
b1 = Buffer(name="B1", capacity=5)
m2 = Machine(name="M2", cycle_time=1)
sink = Sink(collect_parts=True)

source.define_routing(downstream=[m1])
m1.define_routing(upstream=[source], downstream=[b1])
b1.define_routing(upstream=[m1], downstream=[m2])
m2.define_routing(upstream=[b1], downstream=[sink])

system = System(objects=[source, m1, b1, m2, sink])
system.simulate(simulation_time=100)
