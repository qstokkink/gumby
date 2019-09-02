import os
import struct
import time

from twisted.internet.task import LoopingCall

from ipv8.community import DEFAULT_MAX_PEERS
from ipv8.lazy_community import lazy_wrapper
from ipv8.peerdiscovery.community import DiscoveryCommunity
from ipv8.messaging.lazy_payload import VariablePayload
from ipv8.messaging.payload_headers import BinMemberAuthenticationPayload
from ipv8.requestcache import NumberCache

from .peer_selection import Option, PeerSelector, generate_reference


PREFERRED_COUNT = 30*2
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


class BreakMatchPayload(VariablePayload):
    format_list = ['I', 'varlenH']
    names = ["time", 'peerid']


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
        try:
            self.overlay.open_proposals.remove(self.peer)
        except KeyError:
            self.overlay.logger.debug("Proposal timed out, but peer already removed.")


def generate_nonce():
    return struct.unpack(">H", os.urandom(2))[0]


class LatencyCommunity(DiscoveryCommunity):

    def __init__(self, my_peer, endpoint, network, max_peers=DEFAULT_MAX_PEERS, anonymize=False):
        super(LatencyCommunity, self).__init__(my_peer, endpoint, network, max_peers=max_peers, anonymize=anonymize)

        ping_time_bins = [x/10.0 for x in range(1, 20)]
        self.ping_reference_bins = generate_reference(lambda x: 1/x, ping_time_bins, PREFERRED_COUNT)

        self.peer_ranking = []  # Sorted list, based on preference
        self.acceptable_peers = set()  # Peers we want included in our next round

        self.open_proposals = set()
        self.accepted_proposals = set()

        self.decode_map.update({
            chr(5): self.on_proposal,
            chr(6): self.on_accept_proposal,
            chr(7): self.on_reject_proposal,
            chr(8): self.on_break_match
        })

        self.request_cache.register_task("update_acceptable_peers",
                                         LoopingCall(self.update_acceptable_peers)).start(2.5, False)

    def check_payload(self, payload):
        if payload.peerid != self.my_peer.mid:
            raise RuntimeError("Someone is replay attacking us!")

    def update_acceptable_peers(self):
        # Clean up mappings
        peer_set = self.get_peers()
        self.open_proposals = set(p for p in self.open_proposals if p in peer_set)
        self.accepted_proposals = set(p for p in self.accepted_proposals if p in peer_set)
        # If necessary, send out new proposals
        open_for_proposal_count = PREFERRED_COUNT - len(self.accepted_proposals) - len(self.open_proposals)
        if open_for_proposal_count > 0:
            peer_selector = PeerSelector(self.ping_reference_bins)
            options = []
            # Only consider peers that are not already accepted or proposed to
            for peer in self.peer_ranking:
                if (peer not in self.accepted_proposals
                        and peer not in self.open_proposals):
                    options.append(Option(peer.get_median_ping(), peer))
            # Maximally send out K_WINDOW proposals at the same time
            for _ in range(K_WINDOW):
                choice = peer_selector.decide(options)
                if choice is not None:
                    options.remove(choice)
                # If the K_WINDOW goes over the PREFERRED_COUNT, stop
                if len(peer_selector.included) == (PREFERRED_COUNT - len(self.accepted_proposals)
                                                        - len(self.open_proposals)):
                    break
            self.acceptable_peers = [tup.obj for tup in options]
            for peer in self.acceptable_peers:
                self.send_proposal(peer)
        else:
            # TODO: Possibly in the future we can swap out existing matches with a bad fit.
            pass

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
        if ((len(self.open_proposals) + len(self.accepted_proposals) < PREFERRED_COUNT
             and peer in self.acceptable_peers)
                or peer in self.open_proposals or peer in self.accepted_proposals):
            plist = ProposalAcceptPayload(payload.nonce, peer.mid).to_pack_list()
            packet = self._ez_pack(self._prefix, 6, [auth, plist])
            self.accepted_proposals.add(peer)
        else:
            plist = ProposalRejectPayload(payload.nonce, peer.mid).to_pack_list()
            packet = self._ez_pack(self._prefix, 7, [auth, plist])
        self.endpoint.send(peer.address, packet)

    @lazy_wrapper(ProposalAcceptPayload)
    def on_accept_proposal(self, peer, payload):
        self.check_payload(payload)
        try:
            request_cache = self.request_cache.pop(u"proposal-cache",
                                                   ProposalCache.number_from_pk_nonce(peer.mid, payload.nonce))
            if request_cache:
                if len(self.open_proposals) + len(self.accepted_proposals) < PREFERRED_COUNT:
                    self.accepted_proposals.add(peer)
                else:
                    auth = BinMemberAuthenticationPayload(self.my_peer.public_key.key_to_bin()).to_pack_list()
                    plist = BreakMatchPayload(time.time()/10, peer.mid).to_pack_list()
                    packet = self._ez_pack(self._prefix, 8, [auth, plist])
                    self.endpoint.send(peer.address, packet)
                self.open_proposals.remove(peer)
            else:
                self.logger.debug("Got timed out or unwanted proposal response.")
        except KeyError:
            self.logger.debug("Got timed out or unwanted proposal response.")

    @lazy_wrapper(ProposalRejectPayload)
    def on_reject_proposal(self, peer, payload):
        self.check_payload(payload)
        try:
            request_cache = self.request_cache.pop(u"proposal-cache",
                                                   ProposalCache.number_from_pk_nonce(peer.mid, payload.nonce))
            if request_cache:
                self.open_proposals.remove(peer)
            else:
                self.logger.debug("Got timed out or unwanted proposal response.")
        except KeyError:
            self.logger.debug("Got timed out or unwanted proposal response.")

    @lazy_wrapper(BreakMatchPayload)
    def on_break_match(self, peer, payload):
        self.check_payload(payload)  # Peer id is correct
        current_time = time.time()/10
        if not (current_time - 1 <= payload.time <= current_time):
            self.logger.debug("Got timed out match break.")
            return
        try:
            self.accepted_proposals.remove(peer)
        except KeyError:
            self.logger.debug("Tried to match break a non-accepted peer.")

    def on_ping(self, source_address, data):
        # TODO: This is for testing only
        their_port = source_address[1]
        my_port = self.my_estimated_lan[1]
        from twisted.internet import reactor
        call = reactor.callLater(abs(my_port-their_port)/100.0,
                                 super(LatencyCommunity, self).on_ping, source_address, data)
        self.register_anonymous_task("ponglater", call)
