from simengine.api.i3x_subscriptions import SubscriptionRegistry


class TestCreate:
    def test_create_returns_clientid_subscriptionid_displayname(self):
        reg = SubscriptionRegistry()
        result = reg.create("client-1", "my sub")
        assert result["clientId"] == "client-1"
        assert result["displayName"] == "my sub"
        assert isinstance(result["subscriptionId"], str) and result["subscriptionId"]

    def test_two_creates_get_different_ids(self):
        reg = SubscriptionRegistry()
        a = reg.create("client-1")
        b = reg.create("client-1")
        assert a["subscriptionId"] != b["subscriptionId"]


class TestRegisterUnregister:
    def test_register_known_elements_succeeds(self):
        reg = SubscriptionRegistry()
        sub = reg.create("client-1")
        results = reg.register("client-1", sub["subscriptionId"], ["a", "b"], known_element_ids={"a", "b"})
        assert all(r["success"] for r in results)

    def test_register_unknown_element_fails_with_404_shape(self):
        reg = SubscriptionRegistry()
        sub = reg.create("client-1")
        results = reg.register("client-1", sub["subscriptionId"], ["ghost"], known_element_ids={"a"})
        assert results[0]["success"] is False
        assert results[0]["responseDetail"]["status"] == 404

    def test_register_on_missing_subscription_returns_none(self):
        reg = SubscriptionRegistry()
        assert reg.register("client-1", "no-such-sub", ["a"], known_element_ids={"a"}) is None

    def test_register_scoped_to_owning_client(self):
        reg = SubscriptionRegistry()
        sub = reg.create("client-1")
        # client-2 doesn't own this subscription -- treated as not found
        assert reg.register("client-2", sub["subscriptionId"], ["a"], known_element_ids={"a"}) is None

    def test_unregister_removes_monitoring(self):
        reg = SubscriptionRegistry()
        sub = reg.create("client-1")
        reg.register("client-1", sub["subscriptionId"], ["a"], known_element_ids={"a"})
        reg.stage_update("a", 1.0, "Good", "2026-01-01T00:00:00.000000Z")
        reg.unregister("client-1", sub["subscriptionId"], ["a"])
        reg.stage_update("a", 2.0, "Good", "2026-01-01T00:00:01.000000Z")
        batches = reg.sync("client-1", sub["subscriptionId"], last_sequence_number=None)
        all_updates = [u for b in batches for u in b["updates"]]
        assert len(all_updates) == 1  # only the update staged before unregister
        assert all_updates[0]["value"] == 1.0


class TestStageAndSync:
    def test_sync_bundles_staged_updates_into_a_batch(self):
        reg = SubscriptionRegistry()
        sub = reg.create("client-1")
        reg.register("client-1", sub["subscriptionId"], ["a"], known_element_ids={"a"})
        reg.stage_update("a", 42.0, "Good", "2026-01-01T00:00:00.000000Z")

        batches = reg.sync("client-1", sub["subscriptionId"], last_sequence_number=None)
        assert len(batches) == 1
        assert batches[0]["sequenceNumber"] == 1
        assert batches[0]["updates"] == [
            {"elementId": "a", "value": 42.0, "quality": "Good", "timestamp": "2026-01-01T00:00:00.000000Z"}
        ]

    def test_sync_returns_no_new_batch_when_nothing_staged(self):
        reg = SubscriptionRegistry()
        sub = reg.create("client-1")
        reg.register("client-1", sub["subscriptionId"], ["a"], known_element_ids={"a"})
        first = reg.sync("client-1", sub["subscriptionId"], last_sequence_number=None)
        assert first == []

    def test_ack_removes_acknowledged_batches(self):
        reg = SubscriptionRegistry()
        sub = reg.create("client-1")
        reg.register("client-1", sub["subscriptionId"], ["a"], known_element_ids={"a"})
        reg.stage_update("a", 1.0, "Good", "t1")
        b1 = reg.sync("client-1", sub["subscriptionId"], last_sequence_number=None)
        assert b1[0]["sequenceNumber"] == 1

        reg.stage_update("a", 2.0, "Good", "t2")
        # Ack sequence 1 -- server must drop it and only return the new batch
        b2 = reg.sync("client-1", sub["subscriptionId"], last_sequence_number=1)
        assert [b["sequenceNumber"] for b in b2] == [2]

    def test_ack_sentinel_minus_one_acks_everything(self):
        reg = SubscriptionRegistry()
        sub = reg.create("client-1")
        reg.register("client-1", sub["subscriptionId"], ["a"], known_element_ids={"a"})
        reg.stage_update("a", 1.0, "Good", "t1")
        reg.sync("client-1", sub["subscriptionId"], last_sequence_number=None)
        reg.stage_update("a", 2.0, "Good", "t2")
        reg.sync("client-1", sub["subscriptionId"], last_sequence_number=None)

        result = reg.sync("client-1", sub["subscriptionId"], last_sequence_number=-1)
        assert result == []

    def test_sync_on_missing_subscription_returns_none(self):
        reg = SubscriptionRegistry()
        assert reg.sync("client-1", "no-such-sub", last_sequence_number=None) is None


class TestDeleteAndList:
    def test_delete_existing_subscription(self):
        reg = SubscriptionRegistry()
        sub = reg.create("client-1")
        results = reg.delete("client-1", [sub["subscriptionId"]])
        assert results[0]["success"] is True
        assert reg.find("client-1", sub["subscriptionId"]) is None

    def test_delete_unknown_subscription_fails_with_404_shape(self):
        reg = SubscriptionRegistry()
        results = reg.delete("client-1", ["ghost"])
        assert results[0]["success"] is False
        assert results[0]["responseDetail"]["status"] == 404

    def test_list_returns_monitored_objects(self):
        reg = SubscriptionRegistry()
        sub = reg.create("client-1", "my sub")
        reg.register("client-1", sub["subscriptionId"], ["a"], known_element_ids={"a"})
        results = reg.list("client-1", [sub["subscriptionId"]])
        assert results[0]["success"] is True
        assert results[0]["result"]["displayName"] == "my sub"
        assert results[0]["result"]["monitoredObjects"] == [{"elementId": "a"}]


class TestAllMonitoredElementIds:
    def test_union_across_subscriptions(self):
        reg = SubscriptionRegistry()
        s1 = reg.create("c1")
        s2 = reg.create("c1")
        reg.register("c1", s1["subscriptionId"], ["a"], known_element_ids={"a", "b"})
        reg.register("c1", s2["subscriptionId"], ["b"], known_element_ids={"a", "b"})
        assert reg.all_monitored_element_ids() == {"a", "b"}
