import os
import struct

from twisted.internet.task import LoopingCall

from ipv8.community import DEFAULT_MAX_PEERS
from ipv8.lazy_community import lazy_wrapper
from ipv8.peerdiscovery.community import DiscoveryCommunity
from ipv8.messaging.lazy_payload import VariablePayload
from ipv8.messaging.payload_headers import BinMemberAuthenticationPayload
from ipv8.requestcache import NumberCache

from .peer_selection import Option, PeerSelector, generate_reference


PREFERRED_COUNT = 128
K_WINDOW = 10


class ProposalPayload(VariablePayload):
    format_list = ['H', 'varlenH']
    names = ["nonce", 'peerid']


class ProposalAcceptPayload(VariablePayload):
    format_list = ['H', 'varlenH']
    names = ["nonce", 'peerid']


class ProposalRejectPayload(VariablePayload):
    format_list = ['H', 'varlenH']
    names = ["nonce", 'peerid']


class ProposalCache(NumberCache):

    def __init__(self, overlay, peer, nonce):
        super(ProposalCache, self).__init__(overlay.request_cache, u"proposal-cache",
                                            self.number_from_pk_nonce(peer.mid, nonce))
        self.overlay = overlay
        self.peer = peer

    @classmethod
    def number_from_pk_nonce(cls, public_key, nonce):
        number = nonce
        for c in public_key:
            number <<= 8
            number += c if isinstance(c, int) else ord(c)
        return number

    def on_timeout(self):
        self.overlay.open_proposals.remove(self.peer)


def generate_nonce():
    return struct.unpack(">H", os.urandom(2))[0]


class LatencyCommunity(DiscoveryCommunity):

    def __init__(self, my_peer, endpoint, network, max_peers=DEFAULT_MAX_PEERS, anonymize=False):
        super(LatencyCommunity, self).__init__(my_peer, endpoint, network, max_peers=max_peers, anonymize=anonymize)

        ping_time_bins = [x/10.0 for x in range(1, 10)]
        ping_reference_bins = generate_reference(lambda x: 1/x, ping_time_bins, PREFERRED_COUNT)
        self.peer_selector = PeerSelector(ping_reference_bins)

        self.peer_ranking = []  # Sorted list, based on preference
        self.acceptable_peers = set()  # Peers we want included in our next round

        self.open_proposals = set()
        self.accepted_proposals = set()

        self.decode_map.update({
            chr(5): self.on_proposal,
            chr(6): self.on_accept_proposal,
            chr(7): self.on_reject_proposal
        })

        self.request_cache.register_task("update_acceptable_peers",
                                         LoopingCall(self.update_acceptable_peers)).start(2.5, False)

    def check_payload(self, payload):
        if payload.peerid != self.my_peer.mid:
            raise RuntimeError("Someone is replay attacking us!")

    def update_acceptable_peers(self):
        open_for_proposal_count = PREFERRED_COUNT - len(self.accepted_proposals) - len(self.open_proposals)
        print "[DEBUG] Current partners", [str(p) for p in self.acceptable_peers]
        print "[DEBUG] I have room for", open_for_proposal_count
        if open_for_proposal_count > 0:
            # Send out proposals
            options = []
            for peer in self.peer_ranking:
                if (peer not in self.accepted_proposals
                        and peer not in self.open_proposals):
                    options.append(Option(peer.get_median_ping(), peer))
            for _ in range(K_WINDOW):
                choice = self.peer_selector.decide(options)
                if choice is not None:
                    options.remove(choice)
                if len(self.peer_selector.included) == (PREFERRED_COUNT - len(self.accepted_proposals)
                                                        - len(self.open_proposals)):
                    break
            self.acceptable_peers = [tup.obj for tup in options]
            for peer in self.acceptable_peers:
                print "[DEBUG] Sending proposal to", str(peer)
                self.send_proposal(peer)

    def send_proposal(self, peer):
        nonce = generate_nonce()
        self.open_proposals.add(peer)
        self.request_cache.add(ProposalCache(self, peer, nonce))
        auth = BinMemberAuthenticationPayload(self.my_peer.public_key.key_to_bin()).to_pack_list()
        payload = ProposalPayload(nonce, peer.mid).to_pack_list()
        self.endpoint.send(peer.address, self._ez_pack(self._prefix, 5, [auth, payload]))

    @lazy_wrapper(ProposalPayload)
    def on_proposal(self, peer, payload):
        self.check_payload(payload)
        auth = BinMemberAuthenticationPayload(self.my_peer.public_key.key_to_bin()).to_pack_list()
        if peer in self.acceptable_peers or peer in self.open_proposals or peer in self.accepted_proposals:
            plist = ProposalAcceptPayload(payload.nonce, peer.mid).to_pack_list()
            packet = self._ez_pack(self._prefix, 6, [auth, plist])
            self.accepted_proposals.add(peer)
            print "[DEBUG] Accepting proposal of", str(peer)
        else:
            plist = ProposalRejectPayload(payload.nonce, peer.mid).to_pack_list()
            packet = self._ez_pack(self._prefix, 7, [auth, plist])
            print "[DEBUG] Rejecting proposal of", str(peer)
        self.endpoint.send(peer.address, packet)
        print "[DEBUG] Current partners", [str(p) for p in self.acceptable_peers]

    @lazy_wrapper(ProposalAcceptPayload)
    def on_accept_proposal(self, peer, payload):
        self.check_payload(payload)
        request_cache = self.request_cache.pop(u"proposal-cache",
                                               ProposalCache.number_from_pk_nonce(peer.mid, payload.nonce))
        if request_cache:
            self.accepted_proposals.add(peer)
            self.open_proposals.remove(peer)

    @lazy_wrapper(ProposalRejectPayload)
    def on_reject_proposal(self, peer, payload):
        self.check_payload(payload)
        request_cache = self.request_cache.pop(u"proposal-cache",
                                               ProposalCache.number_from_pk_nonce(peer.mid, payload.nonce))
        if request_cache:
            self.open_proposals.remove(peer)

    def on_ping(self, source_address, data):
        # TODO: This is for testing only
        their_port = source_address[1]
        my_port = self.my_estimated_lan[1]
        from twisted.internet import reactor
        call = reactor.callLater(abs(my_port-their_port)/100.0, super(LatencyCommunity, self).on_ping, source_address, data)
        self.register_anonymous_task("ponglater", call)
