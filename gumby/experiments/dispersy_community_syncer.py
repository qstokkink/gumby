import json
import struct

from os import path
from sys import path as pythonpath

from twisted.internet import reactor
from twisted.internet.defer import Deferred, inlineCallbacks, returnValue

# TODO(emilon): Fix this crap
pythonpath.append(path.abspath(path.join(path.dirname(__file__), '..', '..', '..', "./tribler")))

from Tribler.dispersy.authentication import MemberAuthentication
from Tribler.dispersy.candidate import LoopbackCandidate
from Tribler.dispersy.community import Community
from Tribler.dispersy.conversion import DefaultConversion, BinaryConversion
from Tribler.dispersy.destination import CommunityDestination
from Tribler.dispersy.dispersy import Dispersy
from Tribler.dispersy.distribution import FullSyncDistribution
from Tribler.dispersy.endpoint import StandaloneEndpoint
from Tribler.dispersy.message import Message, DropPacket, DropMessage, BatchConfiguration
from Tribler.dispersy.payload import Payload
from Tribler.dispersy.resolution import PublicResolution


class DispersyCommunitySyncer(object):

    def __init__(self, node_count):
        self.node_count = node_count
        self.community = None
        self.conditions = {}

        endpoint = StandaloneEndpoint(65000)
        dispersy = Dispersy(endpoint, u".", u":memory:")

        reactor.callWhenRunning(dispersy.start, True)
        reactor.callFromThread(self.join_community, dispersy)

    def join_community(self, dispersy):
        master_member = DCSCommunity.get_master_members(dispersy)[0]
        my_member = dispersy.get_new_member()
        self.community = DCSCommunity.init_community(dispersy, master_member, my_member)
        self.community.propertymap_updated_cb = self.on_property_changed

    def on_property_changed(self, property):
        if property in self.conditions:
            condition = self.conditions[property]
            if condition[0](self.community.propertymap[property]):
                condition[1].callback(None)

    def pend_value(self, condition, value):
        if value not in self.conditions:
            d = Deferred()
            self.conditions[value] = (condition, d)
            self.community.share({value: True})
            return d
        else:
            return self.conditions[value][1]

    @inlineCallbacks
    def start(self):
        def condition(value_dict):
            return len(value_dict.keys()) == self.node_count

        yield self.pend_value(condition, "READY")

        returnValue(self.community.propertymap["READY"].keys())

    def stop(self):
        self.community.dispersy.stop()


class DCSCommunity(Community):

    """
    Share properties between different nodes in a Community.

    For example:

    share("READY", True)
    share("SEEDER", False)
    share("MAX_UPLOAD_RATE", 1.1)

    Retrieval:
    self.propertymap["READY"] -> {Candidate1: value1, Candidate2: value2, ..}
    """

    @classmethod
    def get_master_members(cls, dispersy):
        master_key = "MFIwEAYHKoZIzj0CAQYFK4EEABoDPgAEALvfb/SBDTHVK6+7N4dbWnnCL288EOn1" + \
                     "cLuYPXZrACblkpVLIJ+ipz9HLoeg+wSE1Aa8WYv+hKmlZnaK"
        master_key_hex = master_key.decode("BASE64")
        master = dispersy.get_member(public_key=master_key_hex)
        return [master]

    def __init__(self, dispersy, master_member, my_member):
        super(DCSCommunity, self).__init__(dispersy, master_member, my_member)
        self.propertymap = {}
        self.propertymap_updated_cb = None

    def initiate_conversions(self):
        return [DefaultConversion(self), DCSConversion(self)]

    @property
    def dispersy_auto_download_master_member(self):
        return False

    @property
    def dispersy_enable_fast_candidate_walker(self):
        return True

    def initiate_meta_messages(self):
        messages = super(DCSCommunity, self).initiate_meta_messages()
        our_messages = [Message(self,
                                u"dcsproperty",
                                MemberAuthentication(encoding="sha1"),
                                PublicResolution(),
                                FullSyncDistribution(
                                    enable_sequence_number=False,
                                    synchronization_direction=u"ASC",
                                    priority=128),
                                CommunityDestination(
                                    node_count=100),
                                DCSPropertyPayload(),
                                self.check_share,
                                self.on_share,
                                batch=BatchConfiguration(0.0))]
        messages.extend(our_messages)
        return messages

    def share(self, property_dict):
        encoded = json.dumps(property_dict)

        meta = self.get_meta_message(u"dcsproperty")
        msg = meta.impl(authentication=(self.my_member,),
                        distribution=(self.claim_global_time(),),
                        payload=(encoded,))

        self.dispersy.store_update_forward([msg], True, True, True)

    def check_share(self, messages):
        for message in messages:
            known_members = {c.get_member(): c for c in self.dispersy_yield_verified_candidates()}
            # We need to know who the candidate is
            if message.authentication.member not in known_members:
                yield DropMessage(message, "Unknown member signed this")
                continue

            message._candidate = known_members[message.authentication.member]
            yield message

    def on_share(self, messages):
        for message in messages:
            decoded = json.loads(message.payload.data)

            if not message.candidate:
                message._candidate = LoopbackCandidate()
                message.candidate.associate(self.my_member)

            for k, v in decoded.iteritems():
                if k not in self.propertymap:
                    self.propertymap[k] = {}
                self.propertymap[k][message.candidate] = v

                if self.propertymap_updated_cb:
                    self.propertymap_updated_cb(k)

class DCSConversion(BinaryConversion):

    def __init__(self, community):
        super(DCSConversion, self).__init__(community, "\x01")
        self.define_meta_message(
            chr(1),
            community.get_meta_message(u"dcsproperty"),
            self._encode_dcsproperty,
            self._decode_dcsproperty)

    def _encode_dcsproperty(self, message):
        return struct.pack("!L", len(message.payload.data)), message.payload.data

    def _decode_dcsproperty(self, placeholder, offset, data):
        if len(data) < offset + 4:
            raise DropPacket("Insufficient packet size")
        data_length, = struct.unpack_from("!L", data, offset)
        offset += 4

        if len(data) < offset + data_length:
            raise DropPacket("Insufficient packet size")
        data_payload = data[offset:offset + data_length]
        offset += data_length

        return offset, placeholder.meta.payload.implement(data_payload)

class DCSPropertyPayload(Payload):

    class Implementation(Payload.Implementation):
        def __init__(self, meta, data):
            super(DCSPropertyPayload.Implementation, self).__init__(meta)
            self.data = data

# TODO Move this into a Gumby experiment
if __name__ == "__main__":
    import logging
    from twisted.internet import threads
    logging.basicConfig(level=logging.WARNING)

    dcs = DispersyCommunitySyncer(2)

    def wait_for_members():
        members = threads.blockingCallFromThread(reactor, dcs.start)

        print "Experiment started!, MEMBERS:"
        print members

        reactor.callFromThread(reactor.stop)
    reactor.callInThread(wait_for_members)

    reactor.run()