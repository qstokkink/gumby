#!/usr/bin/env python2
import base64

from experiments.multichain.multichain_module import MultichainModule

from gumby.experiment import experiment_callback
from gumby.modules.experiment_module import static_module


@static_module
class LiveEdgesModule(MultichainModule):

    def __init__(self, experiment):
        super(LiveEdgesModule, self).__init__(experiment)
        self.previous_trust = {}
        self.live_edges_candidates = {}

    @experiment_callback
    def stop_live_edge_listen(self):
        self.community.set_live_edge_callback(None)
        for id in self.live_edges_candidates:
            candidates = self.live_edges_candidates[id]
            members = []
            for candidate in candidates:
                if candidate.get_member():
                    members.append(base64.b64encode(candidate.get_member().mid))
                else:
                    members.append("?")
            self.live_edges_candidates[id] = members
        self.print_dict_changes("live_edges", {}, self.live_edges_candidates)

    def on_live_edge_update(self, id, candidates):
        self.live_edges_candidates.update({id: candidates})

    @experiment_callback
    def clear_candidates_and_listen(self):
        # Reset candidates and live edges
        # (Walk again with previously established trust)
        self.community.candidates.clear()
        self.community._live_edge_id = 0
        self.community._live_edge = []
        self.community.set_live_edge_callback(self.on_live_edge_update)

        # Finalize network overview
        my_mid = base64.b64encode(self.community.my_member.mid)
        self.previous_trust = self.print_dict_changes("trust", {}, {my_mid: self.previous_trust})

    def request_signature_from_candidate(self, candidate, up, down):
        super(LiveEdgesModule, self).request_signature_from_candidate(candidate, up, down)

        # Log random trust between us and someone else
        short_id = base64.b64encode(candidate.get_member().mid)
        if short_id in self.previous_trust:
            trust = up + down + self.previous_trust[short_id]
        else:
            trust = up + down
        self.previous_trust.update({short_id: trust})
