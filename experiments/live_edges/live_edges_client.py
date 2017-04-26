#!/usr/bin/env python2
import base64
import os
from sys import maxint

from experiments.multichain.multichain_client import MultiChainClient
from gumby.experiments.dispersyclient import main

from Tribler.community.multichain.community import PendingBytes


class LiveEdgesClient(MultiChainClient):

    def __init__(self, params):
        super(LiveEdgesClient, self).__init__(params)
        self.previous_trust = {}
        self.live_edges_candidates = {}

    def registerCallbacks(self):
        super(LiveEdgesClient, self).registerCallbacks()
        self.scenario_runner.register(self.stop_live_edge_listen)
        self.scenario_runner.register(self.clear_candidates_and_listen)

    def set_unlimited_pending(self, candidate):
        pk = candidate.get_member().public_key
        self.multichain_community.pending_bytes[pk] = PendingBytes(maxint/2, maxint/2)

    def stop_live_edge_listen(self):
        self.multichain_community.set_live_edge_callback(None)
        for id in self.live_edges_candidates:
            candidates = self.live_edges_candidates[id]
            members = []
            for candidate in candidates:
                if candidate.get_member():
                    members.append(base64.b64encode(candidate.get_member().mid))
                else:
                    members.append("?")
            self.live_edges_candidates[id] = members
        self.print_on_change("live_edges", {}, self.live_edges_candidates)

    def on_live_edge_update(self, id, candidates):
        self.live_edges_candidates.update({id: candidates})

    def clear_candidates_and_listen(self):
        # Reset candidates and live edges
        # (Walk again with previously established trust)
        self.multichain_community.candidates.clear()
        self.multichain_community._live_edge_id = 0
        self.multichain_community._live_edge = []
        self.multichain_community.set_live_edge_callback(self.on_live_edge_update)

        # Finalize network overview
        my_mid = base64.b64encode(self.multichain_community.my_member.mid)
        self.previous_trust = self.print_on_change("trust", {}, {my_mid: self.previous_trust})

    def request_signature_from_candidate(self, candidate, up, down):
        super(LiveEdgesClient, self).request_signature_from_candidate(candidate, up, down)
        self.set_unlimited_pending(candidate)

        # Log random trust between us and someone else
        short_id = base64.b64encode(candidate.get_member().mid)
        if short_id in self.previous_trust:
            trust = up + down + self.previous_trust[short_id]
        else:
            trust = up + down
        self.previous_trust.update({short_id: trust})


if __name__ == '__main__':
    LiveEdgesClient.scenario_file = os.environ.get('SCENARIO_FILE', 'live_edges.scenario')
    main(LiveEdgesClient)
