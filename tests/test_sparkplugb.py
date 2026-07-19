"""Gate P5 — SparkplugB publisher (mocked MQTT client): births, deltas, rebirth, seq."""
from unittest.mock import MagicMock

import pytest

from simengine.engine.line import LineEngine
from simengine.publishers._sparkplug_pb import sparkplug_b_pb2 as pb2
from simengine.publishers.metrics import line_metrics, station_metrics
from simengine.publishers.sparkplugb import SparkplugBPublisher


def demo_config():
    return {
        "line_name": "Line1",
        "stations": [
            {"name": "Press01", "cycle_time": 3.0, "defect_rate": 0.05,
             "process_values": [
                 {"name": "OilTemp", "unit": "degC", "profile": "first_order_lag",
                  "setpoint": 55.0, "tau": 60, "initial": 20.0}]},
            {"name": "Pack02", "cycle_time": 2.0},
        ],
        "buffers": [{"name": "B1", "capacity": 5}],
    }


SPB_CFG = {"broker": "mqtt://localhost:1883", "group_id": "Area01",
           "edge_node_id": "Line1"}


@pytest.fixture
def pub_engine():
    engine = LineEngine(demo_config(), "demo", seed=1, run_id="spb_test")
    pub = SparkplugBPublisher(demo_config(), SPB_CFG)
    pub._client = MagicMock()
    pub._connected = True
    return pub, engine


def sent_messages(pub):
    """[(topic, parsed Payload)] from the mocked client."""
    out = []
    for call in pub._client.publish.call_args_list:
        topic = call.args[0]
        payload = pb2.Payload()
        payload.ParseFromString(call.args[1])
        out.append((topic, payload))
    return out


class TestBirths:
    def test_dbirth_metric_set_matches_snapshot(self, pub_engine):
        pub, engine = pub_engine
        snap = engine.snapshot()
        pub._publish_births(snap)
        msgs = dict(sent_messages(pub))

        dbirth = msgs["spBv1.0/Area01/DBIRTH/Line1/Press01"]
        names = {m.name for m in dbirth.metrics}
        expected = set(station_metrics(snap.stations["Press01"]).keys())
        assert names == expected
        assert "PV/OilTemp" in names
        # every metric declares name + alias + datatype
        assert all(m.alias > 0 for m in dbirth.metrics)
        assert all(m.datatype > 0 for m in dbirth.metrics)

    def test_nbirth_has_bdseq_and_rebirth_control(self, pub_engine):
        pub, engine = pub_engine
        pub._publish_births(engine.snapshot())
        msgs = dict(sent_messages(pub))
        nbirth = msgs["spBv1.0/Area01/NBIRTH/Line1"]
        assert nbirth.seq == 0
        names = {m.name for m in nbirth.metrics}
        assert "bdSeq" in names and "Node Control/Rebirth" in names
        assert names >= set(line_metrics(engine.snapshot()).keys())

    def test_aliases_stable_across_rebirth(self, pub_engine):
        pub, engine = pub_engine
        pub._publish_births(engine.snapshot())
        aliases_1 = dict(pub._aliases["Press01"])
        pub._client.publish.reset_mock()
        pub._publish_births(engine.snapshot())
        assert pub._aliases["Press01"] == aliases_1


class TestDelta:
    def test_ddata_contains_only_changed_aliases(self, pub_engine):
        pub, engine = pub_engine
        pub._publish_births(engine.snapshot())
        pub._client.publish.reset_mock()

        engine.step()  # something changes (state, PV, cycle metrics)
        snap = engine.snapshot()
        pub.publish(snap)

        msgs = sent_messages(pub)
        ddata = [p for (t, p) in msgs if t.startswith("spBv1.0/Area01/DDATA/")]
        assert ddata, "expected at least one DDATA"
        press_aliases = pub._aliases["Press01"]
        st_metrics = station_metrics(snap.stations["Press01"])
        for payload in ddata:
            for m in payload.metrics:
                assert m.name == ""  # delta by alias only
                assert m.alias > 0

        # publishing an identical snapshot again -> no DDATA at all
        pub._client.publish.reset_mock()
        pub.publish(snap)
        assert not [t for (t, _) in sent_messages(pub)
                    if "DDATA" in t or "NDATA" in t]

    def test_unchanged_metric_not_resent(self, pub_engine):
        pub, engine = pub_engine
        pub._publish_births(engine.snapshot())
        engine.step()
        snap = engine.snapshot()
        pub._client.publish.reset_mock()
        pub.publish(snap)
        msgs = sent_messages(pub)
        # PartsMade did not change after one step (cycle_time 3): its alias
        # must not appear in any DDATA for Press01
        parts_alias = pub._aliases["Press01"]["PartsMade"]
        for topic, payload in msgs:
            if topic.endswith("DDATA/Line1/Press01"):
                assert parts_alias not in {m.alias for m in payload.metrics}


class TestRebirth:
    def test_ncmd_rebirth_triggers_full_births(self, pub_engine):
        pub, engine = pub_engine
        pub._publish_births(engine.snapshot())
        pub._client.publish.reset_mock()

        ncmd = pb2.Payload()
        m = ncmd.metrics.add()
        m.name = "Node Control/Rebirth"
        m.datatype = 11
        m.boolean_value = True
        pub._handle_ncmd(ncmd.SerializeToString())

        pub.publish(engine.snapshot())
        topics = [t for (t, _) in sent_messages(pub)]
        assert "spBv1.0/Area01/NBIRTH/Line1" in topics
        assert "spBv1.0/Area01/DBIRTH/Line1/Press01" in topics
        assert "spBv1.0/Area01/DBIRTH/Line1/Pack02" in topics

    def test_malformed_ncmd_ignored(self, pub_engine):
        pub, _ = pub_engine
        pub._handle_ncmd(b"\xff\xfe garbage")
        assert not pub._rebirth_requested.is_set()


class TestSeq:
    def test_seq_wraps_at_255(self, pub_engine):
        pub, engine = pub_engine
        pub._publish_births(engine.snapshot())  # seq 0,1,2 (NBIRTH + 2 DBIRTH)
        seqs = []
        for _ in range(300):
            engine.step()
            pub.publish(engine.snapshot())
        for topic, payload in sent_messages(pub):
            seqs.append(payload.seq)
        assert max(seqs) == 255
        assert 0 in seqs
        # strictly cycling: every consecutive pair increments mod 256
        for a, b in zip(seqs, seqs[1:]):
            assert b == (a + 1) % 256

    def test_nbirth_resets_seq_to_zero(self, pub_engine):
        pub, engine = pub_engine
        pub._publish_births(engine.snapshot())
        for _ in range(5):
            engine.step()
            pub.publish(engine.snapshot())
        pub._client.publish.reset_mock()
        pub._publish_births(engine.snapshot())
        msgs = sent_messages(pub)
        assert msgs[0][1].seq == 0


class TestDeath:
    def test_on_run_end_sends_deaths(self, pub_engine):
        pub, engine = pub_engine
        snap = engine.snapshot()
        pub._publish_births(snap)
        pub.publish(snap)
        pub._client.publish.reset_mock()
        pub.on_run_end()
        topics = [t for (t, _) in sent_messages(pub)]
        assert "spBv1.0/Area01/NDEATH/Line1" in topics
        assert "spBv1.0/Area01/DDEATH/Line1/Press01" in topics

    def test_ndeath_carries_bdseq(self, pub_engine):
        pub, _ = pub_engine
        payload = pub._ndeath_payload()
        assert payload.metrics[0].name == "bdSeq"
        assert payload.metrics[0].long_value == pub._bd_seq
