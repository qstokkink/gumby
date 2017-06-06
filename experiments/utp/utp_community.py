import struct

from twisted.internet.task import LoopingCall

from Tribler.dispersy.authentication import MemberAuthentication
from Tribler.dispersy.community import Community
from Tribler.dispersy.conversion import DefaultConversion, BinaryConversion
from Tribler.dispersy.destination import CandidateDestination
from Tribler.dispersy.distribution import DirectDistribution
from Tribler.dispersy.message import Message, DropPacket, BatchConfiguration
from Tribler.dispersy.payload import Payload
from Tribler.dispersy.resolution import LinearResolution

from . import get_time_microseconds, MAX_UTP_IDLE
from .utp_enums import UTPExtensionEnum, UTPTypeEnum
from .utp_connection import UTPReceivingConnection, UTPSendingConnection


class UTPCommunity(Community):
    """
    The UTPCommunity exposes functionality to send and receive messages over uTP streams.
    This uTP overlay is built on top of the Dispersy infrastructure.

    To receive data, set the community's ``utp_data_callback`` to your handler function.
    This function should take two arguments: a candidate and the data.

    To send data, call ``send_utp_message`` with the target candidate and the data to send
    to the candidate.
    """

    def __init__(self, dispersy, master_member, my_member):
        super(UTPCommunity, self).__init__(dispersy, master_member, my_member)

        self._utp_connections = {}
        self.utp_data_callback = None
        self.register_task("clean_finished_utp_connection",
                           LoopingCall(self.cleanup_connections), delay=0.0, interval=30.0)

    def unload_community(self):
        for member in self._utp_connections:
            for connection_id in self._utp_connections[member]:
                self._utp_connections[member][connection_id].close()
        super(UTPCommunity, self).unload_community()

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

    def cleanup_connections(self):
        """
        (Periodically) delete finished connections.

        Once a connection has been either (1) dropped or (2) finished,
        make sure it stays around until the idle time has passed, before discarding it.
        This ensures that no new connections are made for finalized connections with
        delayed data.
        """
        cleanable = []
        for member in self._utp_connections:
            for connection_id in self._utp_connections[member]:
                connection = self._utp_connections[member][connection_id]
                idle_time = get_time_microseconds() - connection.last_timestamp
                if connection.is_complete() and (idle_time / 1000000.0 > MAX_UTP_IDLE):
                    cleanable.append((member, connection_id))
        for member, connection_id in cleanable:
            if connection_id in self._utp_connections[member]:
                del self._utp_connections[member][connection_id]
            if len(self._utp_connections[member].keys()) == 0:
                del self._utp_connections[member]

    def on_utp_data(self, candidate, data):
        """
        Callback for when a uTP stream has been finalized and the data has been reconstructed.
        This forwards the candidate and data to the utp_data_callback if it is set.
        """
        if self.utp_data_callback:
            self.utp_data_callback(candidate, data)

    def _check_utp(self, messages):
        """
        Check if a uTP message is valid and create a receiving stream to handle the message if necessary.
        """
        for message in messages:
            # On syn, the receiving (our) connection_id is (1 + message.connection_id) mod 65536
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
        """
        Handle a uTP message.
        If signalled by the message handling connection, will immediately send a response.
        """
        for message in messages:
            # Retrieve the Connection object (sending or receiving)
            # This may have been dropped between the checker and the handler
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
            # Handle the message in the connection and gather response(s)
            responses = connection.on_frame(message.payload)
            if responses:
                candidate = message.candidate
                if not candidate.get_member():
                    candidate.associate(message.authentication.member)
                for response in responses:
                    self._send_utp_frame(candidate, response)
            # If this message caused a clean exit: remove the connection from the connection dict
            if connection.is_complete():
                connection.close() # No need to transmit a hard-kill frame, this was planned
                del self._utp_connections[message.authentication.member][message.payload.connection_id]

    def send_utp_message(self, candidate, data):
        """
        Send a uTP message to a candidate

        :param candidate: the candidate (with member) to send to
        :param data: the data to transmit to the candidate
        """
        assert candidate.get_member(), "You can only send uTP messages to candidates with members!"

        connection = UTPSendingConnection(data)
        if candidate.get_member() not in self._utp_connections:
            self._utp_connections[candidate.get_member()] = {}
        self._utp_connections[candidate.get_member()][connection.conn_id_recv] = connection
        self._send_utp_frame(candidate, connection.create_syn())

    def _send_utp_frame(self, candidate, frame):
        """
        Pack a uTP frame (dict) into a Dispersy message and send it.
        """
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
    """
    Raw Dispersy uTP frame container
    """

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
    """
    Payload to wire conversion for uTP frames.
    """

    def __init__(self, community):
        super(UTPConversion, self).__init__(community, "\x01")
        self.define_meta_message(
            chr(234),
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

        # Note: big endian
        typ = type_version & 0x0F
        version = type_version >> 4

        # The timestamp in microseconds actually does not fit in an integer
        # So, we send the LSBs and fill in the MSBs at the receiver.
        current_time = get_time_microseconds()
        current_time_mask = current_time & 0xFFFFFFFF
        timestamp_microseconds |= current_time ^ current_time_mask

        offset += 24

        if len(data) < offset + data_length:
            raise DropPacket("Truncated packet")

        packed_data = data[offset:offset + data_length]
        offset += data_length

        # There can be an optional extension present (extesion != EX_DATA).
        # In this case the data element starts with two bytes: extension, extension_length, extension_data.
        # The data is then the remainder of the frame.
        # Currently we drop the packet if the extension is unknown (protocol is actually to ignore).
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
