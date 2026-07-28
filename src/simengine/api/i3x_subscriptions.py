"""In-memory i3X subscription registry.

Deliberately simpler than the pinned reference server (docs/superpowers/specs/
2026-07-28-i3x-interface-design.md): no TTL auto-expiry, no queue-overflow
tracking. Those exist there to bound resource use under many concurrent
clients over long sessions -- not a concern for a single-operator test/
reference server. Sequence numbering and ack semantics, the actual wire
contract a client depends on, are implemented faithfully.
"""
import threading
import uuid
from typing import Any, Dict, List, Optional

from simengine.api.i3x_build import make_vqt


class _Subscription:
    def __init__(self, client_id: str, subscription_id: str, display_name: Optional[str]):
        self.client_id = client_id
        self.subscription_id = subscription_id
        self.display_name = display_name
        self.monitored_element_ids: set = set()
        self.staged_updates: List[dict] = []
        self.batches: List[dict] = []
        self.next_sequence = 1


class SubscriptionRegistry:
    def __init__(self):
        self._lock = threading.Lock()
        self._subs: List[_Subscription] = []

    def _find(self, client_id: str, subscription_id: str) -> Optional[_Subscription]:
        return next(
            (s for s in self._subs if s.subscription_id == subscription_id and s.client_id == client_id),
            None,
        )

    def find(self, client_id: str, subscription_id: str) -> Optional[_Subscription]:
        with self._lock:
            return self._find(client_id, subscription_id)

    def create(self, client_id: str, display_name: Optional[str] = None) -> dict:
        with self._lock:
            sub = _Subscription(client_id, str(uuid.uuid4()), display_name)
            self._subs.append(sub)
            return {"clientId": client_id, "subscriptionId": sub.subscription_id, "displayName": display_name}

    def register(self, client_id: str, subscription_id: str, element_ids: List[str],
                known_element_ids: set) -> Optional[List[dict]]:
        with self._lock:
            sub = self._find(client_id, subscription_id)
            if sub is None:
                return None
            results = []
            for eid in element_ids:
                if eid not in known_element_ids:
                    results.append({"success": False, "elementId": eid,
                                    "responseDetail": {"title": "Not Found", "status": 404,
                                                       "detail": f"Element not found: {eid}"}})
                    continue
                sub.monitored_element_ids.add(eid)
                results.append({"success": True, "elementId": eid, "result": None})
            return results

    def unregister(self, client_id: str, subscription_id: str, element_ids: List[str]) -> Optional[List[dict]]:
        with self._lock:
            sub = self._find(client_id, subscription_id)
            if sub is None:
                return None
            results = []
            for eid in element_ids:
                sub.monitored_element_ids.discard(eid)
                results.append({"success": True, "elementId": eid, "result": None})
            return results

    def stage_update(self, element_id: str, value: Any, quality: str, timestamp: str) -> None:
        with self._lock:
            vqt = make_vqt(value, quality, timestamp)
            for sub in self._subs:
                if element_id in sub.monitored_element_ids:
                    sub.staged_updates.append({"elementId": element_id, **vqt})

    def sync(self, client_id: str, subscription_id: str,
            last_sequence_number: Optional[int]) -> Optional[List[dict]]:
        with self._lock:
            sub = self._find(client_id, subscription_id)
            if sub is None:
                return None

            if last_sequence_number is not None:
                if last_sequence_number == -1:
                    sub.batches.clear()
                else:
                    sub.batches = [b for b in sub.batches if b["sequenceNumber"] > last_sequence_number]

            if sub.staged_updates:
                sub.batches.append({"sequenceNumber": sub.next_sequence, "updates": list(sub.staged_updates)})
                sub.next_sequence += 1
                sub.staged_updates.clear()

            return list(sub.batches)

    def delete(self, client_id: str, subscription_ids: List[str]) -> List[dict]:
        with self._lock:
            results = []
            for sid in subscription_ids:
                sub = self._find(client_id, sid)
                if sub is None:
                    results.append({"success": False, "subscriptionId": sid,
                                    "responseDetail": {"title": "Not Found", "status": 404,
                                                       "detail": f"Subscription not found: {sid}"}})
                    continue
                self._subs.remove(sub)
                results.append({"success": True, "subscriptionId": sid, "result": None})
            return results

    def list(self, client_id: str, subscription_ids: List[str]) -> List[dict]:
        with self._lock:
            results = []
            for sid in subscription_ids:
                sub = self._find(client_id, sid)
                if sub is None:
                    results.append({"success": False, "subscriptionId": sid,
                                    "responseDetail": {"title": "Not Found", "status": 404,
                                                       "detail": f"Subscription not found: {sid}"}})
                    continue
                results.append({"success": True, "subscriptionId": sid, "result": {
                    "subscriptionId": sub.subscription_id,
                    "displayName": sub.display_name,
                    "monitoredObjects": [{"elementId": e} for e in sorted(sub.monitored_element_ids)],
                }})
            return results
