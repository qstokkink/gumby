import random
import struct

from Tribler.dispersy.authentication import MemberAuthentication
from Tribler.dispersy.community import Community
from Tribler.dispersy.conversion import BinaryConversion, DefaultConversion
from Tribler.dispersy.destination import CandidateDestination, CommunityDestination
from Tribler.dispersy.distribution import FullSyncDistribution, DirectDistribution
from Tribler.dispersy.message import BatchConfiguration, Message
from Tribler.dispersy.payload import Payload
from Tribler.dispersy.resolution import PublicResolution


class BenalohCommunity(Community):

    def __init__(self, dispersy, master_member, my_member):
        super(BenalohCommunity, self).__init__(dispersy, master_member, my_member)

        self.modulus = 1000
        self.n = 5
        self.my_secret_share = random.randint(0, self.modulus-1)

        # Generate random values
        self.random_values = [random.randint(0, self.modulus-1) for _ in range(self.n - 1)]
        self.random_values.append((self.my_secret_share - sum(self.random_values)) % self.modulus)
        if self.random_values[-1] < 0:
            self.random_values[-1] += self.modulus
        random.shuffle(self.random_values)

        # Collect responses
        self.subset_sum = self.my_secret_share
        self.total_sum = 0

    def initiate_conversions(self):
        return [DefaultConversion(self), BenalohCommunityConversion(self)]

    def initiate_meta_messages(self):
        messages = super(BenalohCommunity, self).initiate_meta_messages()

        ourmessages = [Message(self,
                               u"broadcast-share",
                               MemberAuthentication(),
                               PublicResolution(),
                               FullSyncDistribution(u"ASC", 128, False),
                               CommunityDestination(10),
                               LocalSharePayload(),
                               self._generic_timeline_check,
                               self.on_broadcast_share,
                               batch=BatchConfiguration(0.0)),
                       Message(self,
                               u"local-share",
                               MemberAuthentication(),
                               PublicResolution(),
                               DirectDistribution(),
                               CandidateDestination(),
                               LocalSharePayload(),
                               self._generic_timeline_check,
                               self.on_local_share,
                               batch=BatchConfiguration(0.0))
                       ]
        messages.extend(ourmessages)

        return messages

    def on_local_share(self, messages):
        for message in messages:
            self.subset_sum += message.payload.value
            self.subset_sum %= self.modulus

    def on_broadcast_share(self, messages):
        for message in messages:
            self.total_sum += message.payload.value
            self.total_sum %= self.modulus

    def share_local(self):
        meta = self.get_meta_message(u"local-share")
        messages = []
        for candidate in self.dispersy_yield_verified_candidates():
            messages.append(meta.impl(authentication=(self._my_member,),
                                      distribution=(self.claim_global_time(),),
                                      destination=(candidate,),
                                      payload=(self.random_values.pop(),)))
        self.dispersy.store_update_forward(messages, False, False, True)

    def share_subset_sum(self):
        meta = self.get_meta_message(u"broadcast-share")
        message = meta.impl(authentication=(self._my_member,),
                            distribution=(self.claim_global_time(),),
                            payload=(self.subset_sum,))
        self.dispersy.store_update_forward([message], False, False, True)


class LocalSharePayload(Payload):

    class Implementation(Payload.Implementation):
        def __init__(self, meta, value):
            super(LocalSharePayload.Implementation, self).__init__(meta)
            self.value = value


class BroadcastSharePayload(Payload):

    class Implementation(Payload.Implementation):
        def __init__(self, meta, value):
            super(BroadcastSharePayload.Implementation, self).__init__(meta)
            self.value = value


class BenalohCommunityConversion(BinaryConversion):

    share_format = struct.Struct('>Q')

    def __init__(self, community):
        super(BenalohCommunityConversion, self).__init__(community, "\x01")
        self.define_meta_message(
            chr(1),
            community.get_meta_message(u"local-share"),
            self._encode_share,
            self._decode_share)
        self.define_meta_message(
            chr(2),
            community.get_meta_message(u"broadcast-share"),
            self._encode_share,
            self._decode_share)

    def _encode_share(self, message):
        return self.share_format.pack(message.payload.value),

    def _decode_share(self, placeholder, offset, data):
        value, = self.share_format.unpack_from(data, offset)
        offset += self.share_format.size
        return offset, placeholder.meta.payload.implement(value)
