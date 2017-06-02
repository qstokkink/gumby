import random
import struct
import time

from twisted.internet import reactor
from twisted.internet.task import LoopingCall

from Tribler.dispersy.authentication import MemberAuthentication
from Tribler.dispersy.community import Community
from Tribler.dispersy.conversion import DefaultConversion, BinaryConversion
from Tribler.dispersy.destination import CandidateDestination
from Tribler.dispersy.distribution import DirectDistribution
from Tribler.dispersy.message import Message, DropPacket, BatchConfiguration
from Tribler.dispersy.payload import Payload
from Tribler.dispersy.resolution import LinearResolution


MAX_UTP_DATA = 400  # bytes
MAX_UTP_IDLE = 10.0 # seconds
UTP_RETRY_TIME = .5 # seconds
UTP_WINDOW_SIZE = 10 # packets


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
    EX_SINGLE_ACK = 2

    @staticmethod
    def values():
        return [UTPExtensionEnum.EX_DATA, UTPExtensionEnum.EX_SELECTIVE_ACK, UTPExtensionEnum.EX_SINGLE_ACK]


class UTPConnection(object):
    def __init__(self):
        self.conn_id_recv = 0
        self.conn_id_send = 0
        self.seq_nr = -1
        self.ack_nr = 0
        self.last_timestamp = 0
        self.state = UTPConnectionStateEnum.CS_NONE
        self.frame_buffer = {}  # seq_nr: frame
        self._idle_deferred = reactor.callLater(MAX_UTP_IDLE, self.on_timeout)
        self._retry_deferred = reactor.callLater(UTP_RETRY_TIME, self.try_retransmit)
        self.killed = False

    def is_complete(self):
        return False

    def frame_is_valid(self, frame):
        if frame.type not in UTPTypeEnum.values():
            return False

        if frame.version != 1:
            return False

        if frame.extension not in UTPExtensionEnum.values():
            return False

        if (self.conn_id_recv != 0 and self.conn_id_send != 0) \
                and (frame.connection_id not in [self.conn_id_recv, self.conn_id_send]):
            return False

        return True

    def try_retransmit(self):
        if self.conn_id_recv == 0:
            return True
        if self.conn_id_send == 0:
            return True
        if self.state != UTPConnectionStateEnum.CS_FINALIZED:
            self._retry_deferred = reactor.callLater(UTP_RETRY_TIME, self.try_retransmit)

    def on_timeout(self):
        self.state = UTPConnectionStateEnum.CS_FINALIZED
        self.killed = True

    def on_frame(self, payload):
        self.last_timestamp = payload.timestamp_microseconds
        if self._idle_deferred.active():
            self._idle_deferred.reset(MAX_UTP_IDLE)
        if self._retry_deferred.active():
            self._retry_deferred.reset(UTP_RETRY_TIME)
        if payload.type == UTPTypeEnum.ST_RESET:
            self.killed = True
        if payload.type in [UTPTypeEnum.ST_RESET, UTPTypeEnum.ST_FIN]:
            self.state = UTPConnectionStateEnum.CS_FINALIZED
            if self._idle_deferred.active():
                self._idle_deferred.cancel()
            if self._retry_deferred.active():
                self._retry_deferred.cancel()
        return []

    def close(self):
        self.killed = True
        if self._idle_deferred.active():
            self._idle_deferred.cancel()
        if self._retry_deferred.active():
            self._retry_deferred.cancel()
        if self.state != UTPConnectionStateEnum.CS_FINALIZED:
            current_time = _get_time_microseconds()
            frame = {
                'type': UTPTypeEnum.ST_RESET,
                'version': 1,
                'extension': UTPExtensionEnum.EX_DATA,
                'connection_id': self.conn_id_send,
                'timestamp_microseconds': current_time,
                'timestamp_difference_microseconds': current_time - self.last_timestamp,
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
        self.send_buffer = {}
        self.final_seq = -1
        self.window_open = UTP_WINDOW_SIZE

    def is_complete(self):
        return ((self.state == UTPConnectionStateEnum.CS_FINALIZED) and (len(self.send_buffer.keys()) == 0)) or self.killed

    def create_syn(self):
        self.state = UTPConnectionStateEnum.CS_SYN_SENT
        self.window_open -= 1
        frame = {
            'type': UTPTypeEnum.ST_SYN,
            'version': 1,
            'extension': UTPExtensionEnum.EX_DATA,
            'connection_id': self.conn_id_recv,
            'timestamp_microseconds': _get_time_microseconds(),
            'timestamp_difference_microseconds': 0,
            'wnd_size': self.window_open,
            'seq_nr': self.seq_nr,
            'ack_nr': 0,
            'data': ""
        }
        self.seq_nr = (self.seq_nr + 1) % 65536
        self.send_buffer[frame['seq_nr']] = frame
        return frame

    def on_frame(self, payload):
        super(UTPSendingConnection, self).on_frame(payload)
        if payload.ack_nr in self.send_buffer:
            del self.send_buffer[payload.ack_nr]
            if self.state == UTPConnectionStateEnum.CS_CONNECTED:
                self.window_open = min(self.window_open + 1, len(self.send_buffer.keys()))
            else:
                self.window_open += 1
            if payload.ack_nr == self.final_seq:
                self.state = UTPConnectionStateEnum.CS_FINALIZED
        if self.killed:
            return []
        if payload.type == UTPTypeEnum.ST_STATE:
            return self.on_state(payload)
        return []

    def _yield_data(self):
        if self.data_offset == len(self.data):
            return None
        end = self.data_offset + MAX_UTP_DATA
        data_slice = self.data[self.data_offset:end]
        self.data_offset += len(data_slice)
        return data_slice

    def on_state(self, payload):
        if self.state != UTPConnectionStateEnum.CS_FINALIZED:
            self.state = UTPConnectionStateEnum.CS_CONNECTED
        self.ack_nr = payload.seq_nr

        current_time = _get_time_microseconds()

        retransmission = []
        if payload.extension_data and self.window_open == 0:
            retransmit_frame = self.send_buffer.get(int(payload.extension_data), None)
            if retransmit_frame:
                retransmit_frame['timestamp_microseconds'] = current_time
                retransmit_frame['timestamp_difference_microseconds'] = current_time - payload.timestamp_microseconds
                retransmit_frame['wnd_size'] = self.window_open
                retransmission = [retransmit_frame, ]

        frames = []
        while self.window_open > 0:
            data = self._yield_data()

            if not data:
                if not retransmission:
                    self.window_open -= 1
                    frame = {
                        'type': UTPTypeEnum.ST_FIN,
                        'version': 1,
                        'extension': UTPExtensionEnum.EX_DATA,
                        'connection_id': self.conn_id_send,
                        'timestamp_microseconds': current_time,
                        'timestamp_difference_microseconds': current_time - payload.timestamp_microseconds,
                        'wnd_size': self.window_open,
                        'seq_nr': self.seq_nr,
                        'ack_nr': self.ack_nr,
                        'data': ""
                    }
                    if self.final_seq != self.seq_nr:
                        self.send_buffer[frame['seq_nr']] = frame
                    self.final_seq = self.seq_nr
                break
            else:
                self.window_open -= 1
                frame = {
                    'type': UTPTypeEnum.ST_DATA,
                    'version': 1,
                    'extension': UTPExtensionEnum.EX_DATA,
                    'connection_id': self.conn_id_send,
                    'timestamp_microseconds': current_time,
                    'timestamp_difference_microseconds': current_time - payload.timestamp_microseconds,
                    'wnd_size': self.window_open,
                    'seq_nr': self.seq_nr,
                    'ack_nr': self.ack_nr,
                    'data': data
                }
                self.seq_nr = (self.seq_nr + 1) % 65536
                self.send_buffer[frame['seq_nr']] = frame
            frames.append(frame)
        return retransmission + frames


class UTPReceivingConnection(UTPConnection):
    def __init__(self, callback, retransmission_tuple):
        super(UTPReceivingConnection, self).__init__()
        self.receive_buffer = {}
        self.callback = callback
        self.syn_seq_nr = 0
        self.retransmisson_tuple = retransmission_tuple

    def is_complete(self):
        pkey = None
        broken = False
        for key in sorted(self.receive_buffer.keys()):
            if (pkey is not None) and (((pkey + 1) % 65536) != key):
                broken = True
                break
            pkey = key
        return ((self.state == UTPConnectionStateEnum.CS_FINALIZED) and (not broken) and
                self.receive_buffer[key].type == UTPTypeEnum.ST_FIN) or self.killed

    def on_frame(self, payload):
        self.receive_buffer[payload.seq_nr] = payload
        super(UTPReceivingConnection, self).on_frame(payload)
        if self.killed:
            return []
        out = []
        if (self.state == UTPConnectionStateEnum.CS_NONE) and (payload.type == UTPTypeEnum.ST_SYN):
            out = self.on_syn(payload)
        if (self.state != UTPConnectionStateEnum.CS_NONE) and (payload.type in [UTPTypeEnum.ST_DATA, UTPTypeEnum.ST_FIN]):
            out = self.on_data(payload)
        if self.state == UTPConnectionStateEnum.CS_FINALIZED:
            complete_data = ""
            pkey = None
            broken = False
            for key in sorted(self.receive_buffer.keys()):
                if (pkey is not None) and (((pkey + 1) % 65536) != key):
                    self.try_retransmit()
                    broken = True
                    break
                complete_data = complete_data + self.receive_buffer[key].data
                pkey = key
            if not broken and self.receive_buffer[key].type == UTPTypeEnum.ST_FIN:
                self.callback(complete_data)
                self.killed = True
        return out

    def try_retransmit(self):
        should_exit = super(UTPReceivingConnection, self).try_retransmit()
        if should_exit:
            return True
        for i in xrange(1, len(self.receive_buffer.keys()) + 2):
            if ((self.syn_seq_nr + i) % 65536) not in self.receive_buffer:
                current_time = _get_time_microseconds()
                frame = {
                    'type': UTPTypeEnum.ST_STATE,
                    'version': 1,
                    'extension': UTPExtensionEnum.EX_SINGLE_ACK,
                    'connection_id': self.conn_id_send,
                    'timestamp_microseconds': current_time,
                    'timestamp_difference_microseconds': current_time - self.last_timestamp,
                    'wnd_size': 0,
                    'seq_nr': self.seq_nr,
                    'ack_nr': self.ack_nr,
                    'data': "",
                    'extension_data': str((self.syn_seq_nr + i) % 65536)
                }
                self.retransmisson_tuple[0](self.retransmisson_tuple[1], frame)
                break

    def on_syn(self, payload):
        self.conn_id_recv = (payload.connection_id + 1) % 65536
        self.conn_id_send = payload.connection_id
        self.seq_nr = random.randint(0, 65535)
        self.ack_nr = payload.seq_nr
        self.state = UTPConnectionStateEnum.CS_SYN_RECV
        self.syn_seq_nr = payload.seq_nr

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
        return [frame, ]

    def on_data(self, payload):
        if payload.seq_nr in self.frame_buffer:
            return []
        self.ack_nr = payload.seq_nr
        if self.state == UTPConnectionStateEnum.CS_SYN_RECV:
            self.state = UTPConnectionStateEnum.CS_CONNECTED

        current_time = _get_time_microseconds()

        previous_seq = payload.seq_nr - 1 if payload.seq_nr != 0 else 65535
        if (payload.wnd_size == 0) and (previous_seq != self.syn_seq_nr) and (previous_seq not in self.receive_buffer):
            frame = {
                'type': UTPTypeEnum.ST_STATE,
                'version': 1,
                'extension': UTPExtensionEnum.EX_SINGLE_ACK,
                'connection_id': self.conn_id_send,
                'timestamp_microseconds': current_time,
                'timestamp_difference_microseconds': current_time - payload.timestamp_microseconds,
                'wnd_size': 0,
                'seq_nr': self.seq_nr,
                'ack_nr': self.ack_nr,
                'data': "",
                'extension_data': str(previous_seq)
            }
        else:
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
        return [frame, ]


class UTPCommunity(Community):
    def __init__(self, dispersy, master_member, my_member):
        super(UTPCommunity, self).__init__(dispersy, master_member, my_member)

        self._utp_connections = {}
        self.register_task("clean_finished_utp_connection",
                           LoopingCall(self.cleanup_connections), delay=0.0, interval=30.0)

    def unload_community(self):
        for member in self._utp_connections:
            for connection_id in self._utp_connections[member]:
                self._utp_connections[member][connection_id].close()
        super(UTPCommunity, self).unload_community()

    def cleanup_connections(self):
        cleanable = []
        for member in self._utp_connections:
            for connection_id in self._utp_connections[member]:
                connection = self._utp_connections[member][connection_id]
                idle_time = _get_time_microseconds() - connection.last_timestamp
                if connection.is_complete() and (idle_time/1000000.0 > MAX_UTP_IDLE):
                    cleanable.append((member, connection_id))
        for member, connection_id in cleanable:
            if connection_id in self._utp_connections[member]:
                del self._utp_connections[member][connection_id]
            if len(self._utp_connections[member].keys()) == 0:
                del self._utp_connections[member]

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
        print "Yay!", data, len(data)  # TODO DEBUG

    def _check_utp(self, messages):
        for message in messages:
            actual_cid = (message.payload.connection_id + 1) % 65536
            if message.authentication.member not in self._utp_connections:
                self._utp_connections[message.authentication.member] = {}
            if message.payload.connection_id not in self._utp_connections[message.authentication.member]:
                self._utp_connections[message.authentication.member][
                    actual_cid] = UTPReceivingConnection(self.on_utp_data, (self._send_utp_frame, message.candidate))
                yield message
            elif self._utp_connections[message.authentication.member][message.payload.connection_id].frame_is_valid(
                    message.payload):
                yield message

    def _on_utp(self, messages):
        for message in messages:
            try:
                if message.payload.type == UTPTypeEnum.ST_SYN:
                    connection = self._utp_connections[message.authentication.member][
                        (message.payload.connection_id + 1) % 65536]
                else:
                    connection = self._utp_connections[message.authentication.member][
                        message.payload.connection_id]
            except KeyError:
                self._logger.error("Data came in for dropped connection %d", message.payload.connection_id)
                continue

            responses = connection.on_frame(message.payload)
            if responses:
                candidate = message.candidate
                if not candidate.get_member():
                    candidate.associate(message.authentication.member)
                for response in responses:
                    self._send_utp_frame(candidate, response)

            if connection.is_complete():
                connection.close()
                del self._utp_connections[message.authentication.member][message.payload.connection_id]

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
                                  frame['data'],
                                  frame.get('extension_data', None)
                              ))]
        self.dispersy._forward(messages)


class UTPPayload(Payload):
    class Implementation(Payload.Implementation):
        def __init__(self, meta, typ, version, extension, connection_id, timestamp_microseconds,
                     timestamp_difference_microseconds, wnd_size, seq_nr, ack_nr, data, extension_data=None):
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
            self.extension_data = extension_data


class UTPConversion(BinaryConversion):
    def __init__(self, community):
        super(UTPConversion, self).__init__(community, "\x01")
        self.define_meta_message(
            chr(1),
            community.get_meta_message(u"utp"),
            self._encode_utp,
            self._decode_utp)

    def _encode_utp(self, message):
        ext_data = ""
        if message.payload.extension == UTPExtensionEnum.EX_SINGLE_ACK:
            ext_data += struct.pack("!BB", message.payload.extension, len(message.payload.extension_data))
            ext_data += message.payload.extension_data
        type_version = (message.payload.version << 4) | message.payload.type
        return struct.pack("!BBHIIIHHL",
                           type_version,
                           message.payload.extension,
                           message.payload.connection_id & 0xFFFF,
                           message.payload.timestamp_microseconds & 0xFFFFFFFF,
                           message.payload.timestamp_difference_microseconds & 0xFFFFFFFF,
                           message.payload.wnd_size,
                           message.payload.seq_nr & 0xFFFF,
                           message.payload.ack_nr & 0xFFFF,
                           len(ext_data) + len(message.payload.data)), ext_data + message.payload.data

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

        ext_data = None
        if extension != UTPExtensionEnum.EX_DATA:
            try:
                extension, ext_length = struct.unpack_from("!BB", packed_data[:2])
            except:
                raise DropPacket("Invalid packet extension format")
            if len(packed_data) < 2+ext_length:
                raise DropPacket("Truncated packet")
            ext_data = packed_data[2:2+ext_length]
            packed_data = packed_data[2+ext_length:]
            if extension != UTPExtensionEnum.EX_SINGLE_ACK:
                raise DropPacket("Unsupported extension")

        return offset, placeholder.meta.payload.implement(typ, version, extension, connection_id,
                                                          timestamp_microseconds, timestamp_difference_microseconds,
                                                          wnd_size, seq_nr, ack_nr, packed_data, ext_data)
