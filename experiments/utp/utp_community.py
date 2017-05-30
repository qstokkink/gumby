import random
import struct
import time

from Tribler.dispersy.authentication import MemberAuthentication
from Tribler.dispersy.community import Community
from Tribler.dispersy.conversion import DefaultConversion, BinaryConversion
from Tribler.dispersy.destination import CandidateDestination
from Tribler.dispersy.distribution import DirectDistribution
from Tribler.dispersy.message import Message, DropPacket, BatchConfiguration
from Tribler.dispersy.payload import Payload
from Tribler.dispersy.resolution import LinearResolution


MAX_UTP_DATA = 400  # bytes


def _get_time_microseconds():
    seconds = time.time()
    return long(seconds * 1000000)


class UTPTypeEnum(object):
    ST_DATA = 0
    ST_FIN = 1
    ST_STATE = 2
    ST_RESET = 3
    ST_SYN = 4

    @staticmethod
    def values():
        return [UTPTypeEnum.ST_DATA, UTPTypeEnum.ST_FIN, UTPTypeEnum.ST_STATE, UTPTypeEnum.ST_RESET, UTPTypeEnum.ST_SYN]


class UTPConnectionStateEnum(object):
    CS_NONE = 0
    CS_SYN_SENT = 1
    CS_SYN_RECV = 2
    CS_CONNECTED = 3
    CS_FINALIZED = 4

    @staticmethod
    def values():
        return [UTPConnectionStateEnum.CS_NONE, UTPConnectionStateEnum.CS_SYN_SENT, UTPConnectionStateEnum.CS_SYN_RECV,
                UTPConnectionStateEnum.CS_CONNECTED, UTPConnectionStateEnum.CS_FINALIZED]


class UTPExtensionEnum(object):
    EX_DATA = 0
    EX_SELECTIVE_ACK = 1

    @staticmethod
    def values():
        return [UTPExtensionEnum.EX_DATA, UTPExtensionEnum.EX_SELECTIVE_ACK]


class UTPConnection(object):
    def __init__(self):
        self.conn_id_recv = 0
        self.conn_id_send = 0
        self.seq_nr = -1
        self.ack_nr = 0
        self.state = UTPConnectionStateEnum.CS_NONE
        self.frame_buffer = {}  # seq_nr: frame

    def frame_is_valid(self, frame):
        if frame.type not in UTPTypeEnum.values():
            return False

        if frame.version != 1:
            return False

        if frame.extension not in UTPExtensionEnum.values():
            return False

        # TODO Support selective ACK/window
        if frame.extension != 0:
            return False

        if (self.conn_id_recv != 0 and self.conn_id_send != 0) \
                and (frame.connection_id not in [self.conn_id_recv, self.conn_id_send]):
            return False

        return True

    def on_frame(self, payload):
        if payload.type in [UTPTypeEnum.ST_RESET, UTPTypeEnum.ST_FIN]:
            self.state = UTPConnectionStateEnum.CS_FINALIZED
        return None

    def close(self):
        if self.state != UTPConnectionStateEnum.CS_FINALIZED:
            current_time = _get_time_microseconds()
            frame = {
                'type': UTPTypeEnum.ST_RESET,
                'version': 1,
                'extension': UTPExtensionEnum.EX_DATA,
                'connection_id': self.conn_id_send,
                'timestamp_microseconds': current_time,
                'timestamp_difference_microseconds': current_time - payload.timestamp_microseconds,
                'wnd_size': 0,  # TODO Implement window
                'seq_nr': self.seq_nr,
                'ack_nr': self.ack_nr,
                'data': ""
            }
            self.state = UTPConnectionStateEnum.CS_FINALIZED
            return frame
        return None


class UTPSendingConnection(UTPConnection):
    def __init__(self, data):
        super(UTPSendingConnection, self).__init__()
        self.conn_id_recv = random.randint(0, 65535)
        self.conn_id_send = (self.conn_id_recv + 1) % 65536
        self.seq_nr = 1
        self.data = data
        self.data_offset = 0L

    def create_syn(self):
        self.state = UTPConnectionStateEnum.CS_SYN_SENT
        frame = {
            'type': UTPTypeEnum.ST_SYN,
            'version': 1,
            'extension': UTPExtensionEnum.EX_DATA,
            'connection_id': self.conn_id_recv,
            'timestamp_microseconds': _get_time_microseconds(),
            'timestamp_difference_microseconds': 0,
            'wnd_size': 0,  # TODO Implement window
            'seq_nr': self.seq_nr,
            'ack_nr': 0,
            'data': ""
        }
        self.seq_nr = (self.seq_nr + 1) % 65536
        return frame

    def on_frame(self, payload):
        super(UTPSendingConnection, self).on_frame(payload)
        if self.state == UTPConnectionStateEnum.CS_FINALIZED:
            return None
        if (self.state in [UTPConnectionStateEnum.CS_SYN_SENT, UTPConnectionStateEnum.CS_CONNECTED]) and\
                (payload.type == UTPTypeEnum.ST_STATE):
            return self.on_state(payload)
        return None

    def _yield_data(self):
        if self.data_offset == len(self.data):
            return None
        end = self.data_offset + MAX_UTP_DATA
        data_slice = self.data[self.data_offset:end]
        self.data_offset += len(data_slice)
        return data_slice

    def on_state(self, payload):
        self.state = UTPConnectionStateEnum.CS_CONNECTED
        self.ack_nr = payload.seq_nr

        data = self._yield_data()
        current_time = _get_time_microseconds()

        if not data:
            frame = {
                'type': UTPTypeEnum.ST_FIN,
                'version': 1,
                'extension': UTPExtensionEnum.EX_DATA,
                'connection_id': self.conn_id_send,
                'timestamp_microseconds': current_time,
                'timestamp_difference_microseconds': current_time - payload.timestamp_microseconds,
                'wnd_size': 0,  # TODO Implement window
                'seq_nr': self.seq_nr,
                'ack_nr': self.ack_nr,
                'data': ""
            }
            self.state = UTPConnectionStateEnum.CS_FINALIZED
        else:
            frame = {
                'type': UTPTypeEnum.ST_DATA,
                'version': 1,
                'extension': UTPExtensionEnum.EX_DATA,
                'connection_id': self.conn_id_send,
                'timestamp_microseconds': current_time,
                'timestamp_difference_microseconds': current_time - payload.timestamp_microseconds,
                'wnd_size': 0,  # TODO Implement window
                'seq_nr': self.seq_nr,
                'ack_nr': self.ack_nr,
                'data': data
            }
        self.seq_nr = (self.seq_nr + 1) % 65536
        return frame


class UTPReceivingConnection(UTPConnection):
    def __init__(self, callback):
        super(UTPReceivingConnection, self).__init__()
        self.data_buffer = ""
        self.callback = callback

    def on_frame(self, payload):
        super(UTPReceivingConnection, self).on_frame(payload)
        if self.state == UTPConnectionStateEnum.CS_FINALIZED:
            if payload.type == UTPTypeEnum.ST_FIN:
                self.callback(self.data_buffer)
            return None
        if (self.state == UTPConnectionStateEnum.CS_NONE) and (payload.type == UTPTypeEnum.ST_SYN):
            return self.on_syn(payload)
        if (self.state in [UTPConnectionStateEnum.CS_SYN_RECV, UTPConnectionStateEnum.CS_CONNECTED]) and (
            payload.type == UTPTypeEnum.ST_DATA):
            return self.on_data(payload)
        return None

    def on_syn(self, payload):
        self.conn_id_recv = (payload.connection_id + 1) % 65536
        self.conn_id_send = payload.connection_id
        self.seq_nr = random.randint(0, 65535)
        self.ack_nr = payload.seq_nr
        self.state = UTPConnectionStateEnum.CS_SYN_RECV

        current_time = _get_time_microseconds()
        frame = {
            'type': UTPTypeEnum.ST_STATE,
            'version': 1,
            'extension': UTPExtensionEnum.EX_DATA,
            'connection_id': self.conn_id_send,
            'timestamp_microseconds': current_time,
            'timestamp_difference_microseconds': current_time - payload.timestamp_microseconds,
            'wnd_size': 0,
            'seq_nr': self.seq_nr,
            'ack_nr': self.ack_nr,
            'data': ""
        }
        self.seq_nr = (self.seq_nr + 1) % 65536
        return frame

    def on_data(self, payload):
        self.ack_nr = payload.seq_nr
        self.state = UTPConnectionStateEnum.CS_CONNECTED

        self.data_buffer = self.data_buffer + payload.data

        current_time = _get_time_microseconds()
        frame = {
            'type': UTPTypeEnum.ST_STATE,
            'version': 1,
            'extension': UTPExtensionEnum.EX_DATA,
            'connection_id': self.conn_id_send,
            'timestamp_microseconds': current_time,
            'timestamp_difference_microseconds': current_time - payload.timestamp_microseconds,
            'wnd_size': 0,
            'seq_nr': self.seq_nr,
            'ack_nr': self.ack_nr,
            'data': ""
        }
        self.seq_nr = (self.seq_nr + 1) % 65536
        return frame


class UTPCommunity(Community):
    def __init__(self, dispersy, master_member, my_member):
        super(UTPCommunity, self).__init__(dispersy, master_member, my_member)

        self._utp_connections = {}

    def initiate_conversions(self):
        return [DefaultConversion(self), UTPConversion(self)]

    def initiate_meta_messages(self):
        messages = super(UTPCommunity, self).initiate_meta_messages()
        ourmessages = [Message(self,
                               u"utp",
                               MemberAuthentication(),
                               LinearResolution(),
                               DirectDistribution(),
                               CandidateDestination(),
                               UTPPayload(),
                               self._check_utp,
                               self._on_utp,
                               batch=BatchConfiguration(0.0))]
        messages.extend(ourmessages)
        return messages

    def on_utp_data(self, data):
        print "Yay!", data  # TODO DEBUG

    def _check_utp(self, messages):
        for message in messages:
            actual_cid = (message.payload.connection_id + 1) % 65536
            if message.authentication.member not in self._utp_connections:
                self._utp_connections[message.authentication.member] = {}
            if message.payload.connection_id not in self._utp_connections[message.authentication.member]:
                self._utp_connections[message.authentication.member][
                    actual_cid] = UTPReceivingConnection(self.on_utp_data)
                yield message
            elif self._utp_connections[message.authentication.member][message.payload.connection_id].frame_is_valid(
                    message.payload):
                yield message

    def _on_utp(self, messages):
        for message in messages:
            if message.payload.type == UTPTypeEnum.ST_SYN:
                response = self._utp_connections[message.authentication.member][
                    (message.payload.connection_id + 1) % 65536].on_frame(message.payload)
            else:
                response = self._utp_connections[message.authentication.member][
                    message.payload.connection_id].on_frame(message.payload)

            if response:
                candidate = message.candidate
                if not candidate.get_member():
                    candidate.associate(message.authentication.member)
                self._send_utp_frame(candidate, response)

    def send_utp_message(self, candidate, data):
        connection = UTPSendingConnection(data)
        if candidate.get_member() not in self._utp_connections:
            self._utp_connections[candidate.get_member()] = {}
        self._utp_connections[candidate.get_member()][connection.conn_id_recv] = connection
        self._send_utp_frame(candidate, connection.create_syn())

    def _send_utp_frame(self, candidate, frame):
        meta = self.get_meta_message(u"utp")
        messages = [meta.impl(authentication=(self.my_member,),
                              destination=(candidate,),
                              distribution=(self.claim_global_time(),),
                              payload=(
                                  frame['type'],
                                  frame['version'],
                                  frame['extension'],
                                  frame['connection_id'],
                                  frame['timestamp_microseconds'],
                                  frame['timestamp_difference_microseconds'],
                                  frame['wnd_size'],
                                  frame['seq_nr'],
                                  frame['ack_nr'],
                                  frame['data']
                              ))]
        self.dispersy._forward(messages)


class UTPPayload(Payload):
    class Implementation(Payload.Implementation):
        def __init__(self, meta, typ, version, extension, connection_id, timestamp_microseconds,
                     timestamp_difference_microseconds, wnd_size, seq_nr, ack_nr, data):
            super(UTPPayload.Implementation, self).__init__(meta)
            self.type = typ
            self.version = version
            self.extension = extension
            self.connection_id = connection_id
            self.timestamp_microseconds = timestamp_microseconds
            self.timestamp_difference_microseconds = timestamp_difference_microseconds
            self.wnd_size = wnd_size
            self.seq_nr = seq_nr
            self.ack_nr = ack_nr
            self.data = data


class UTPConversion(BinaryConversion):
    def __init__(self, community):
        super(UTPConversion, self).__init__(community, "\x01")
        self.define_meta_message(
            chr(1),
            community.get_meta_message(u"utp"),
            self._encode_utp,
            self._decode_utp)

    def _encode_utp(self, message):
        type_version = (message.payload.version << 4) | message.payload.type
        return struct.pack("!BBHIIIHHL",
                           type_version,
                           message.payload.extension,
                           message.payload.connection_id,
                           message.payload.timestamp_microseconds & 0xFFFFFFFF,
                           message.payload.timestamp_difference_microseconds,
                           message.payload.wnd_size,
                           message.payload.seq_nr,
                           message.payload.ack_nr,
                           len(message.payload.data)), message.payload.data

    def _decode_utp(self, placeholder, offset, data):
        try:
            type_version, extension, connection_id, timestamp_microseconds, timestamp_difference_microseconds, wnd_size, seq_nr, ack_nr, data_length = struct.unpack_from(
                "!BBHIIIHHL", data[offset:])
        except:
            raise DropPacket("Invalid packet format")

        typ = type_version & 0x0F
        version = type_version >> 4

        current_time = _get_time_microseconds()
        current_time_mask = current_time & 0xFFFFFFFF
        timestamp_microseconds |= current_time ^ current_time_mask

        offset += 24

        if len(data) < offset + data_length:
            raise DropPacket("Truncated packet")

        packed_data = data[offset:offset + data_length]
        offset += data_length

        return offset, placeholder.meta.payload.implement(typ, version, extension, connection_id,
                                                          timestamp_microseconds, timestamp_difference_microseconds,
                                                          wnd_size, seq_nr, ack_nr, packed_data)
