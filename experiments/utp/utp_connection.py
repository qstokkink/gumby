import random

from twisted.internet import reactor

from . import get_time_microseconds, MAX_UTP_DATA, MAX_UTP_IDLE, UTP_RETRY_TIME, UTP_WINDOW_SIZE
from .utp_enums import UTPConnectionStateEnum, UTPExtensionEnum, UTPTypeEnum


class UTPConnection(object):
    """
    A uTP connection between a sender and a receiver:
    this is a generic super type for either.
    """

    def __init__(self):
        # The connection id for receiving data
        self.conn_id_recv = 0
        # The connection id for sending data
        self.conn_id_send = 0
        # The next sequence number to use
        self.seq_nr = -1
        # The last ack'd received message
        self.ack_nr = 0
        # The last received timestamp
        self.last_timestamp = 0
        # The current state of this connection
        self.state = UTPConnectionStateEnum.CS_NONE
        # The timeout handler for connection dropping
        self._idle_deferred = reactor.callLater(MAX_UTP_IDLE, self.on_timeout)
        # The timeout handler for retransmissions
        self._retry_deferred = reactor.callLater(UTP_RETRY_TIME, self.try_retransmit)
        # Whether we have been hard killed
        self.killed = False

    def is_complete(self):
        """
        Has this connection been finalized AND are the frames confirmed to have been delivered.
        """
        return False

    def frame_is_valid(self, frame):
        """
        Check if a given frame (Dispersy payload) is valid.
        """
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
        """
        Schedule a new retransmission timeout.

        :returns: True iff no further timeouts are scheduled
        """
        if self.conn_id_recv == 0:
            return True
        if self.conn_id_send == 0:
            return True
        if self.state != UTPConnectionStateEnum.CS_FINALIZED:
            self._retry_deferred = reactor.callLater(UTP_RETRY_TIME, self.try_retransmit)

    def on_timeout(self):
        """
        Callback for when a connection has to be dropped.
        """
        self.state = UTPConnectionStateEnum.CS_FINALIZED
        self.killed = True

    def on_frame(self, payload):
        """
        Callback for when a frame is received (as a Dispersy payload).
        """
        # Record timestamp
        self.last_timestamp = payload.timestamp_microseconds
        # Reset/reschedule timeouts
        if self._idle_deferred.active():
            self._idle_deferred.reset(MAX_UTP_IDLE)
        if self._retry_deferred.active():
            self._retry_deferred.reset(UTP_RETRY_TIME)
        # Check if other end wants to hard-kill
        if payload.type == UTPTypeEnum.ST_RESET:
            self.killed = True
        # Check if other end wants to finalize
        if payload.type in [UTPTypeEnum.ST_RESET, UTPTypeEnum.ST_FIN]:
            self.state = UTPConnectionStateEnum.CS_FINALIZED
            if self._idle_deferred.active():
                self._idle_deferred.cancel()
            if self._retry_deferred.active():
                self._retry_deferred.cancel()
        return []

    def close(self):
        """
        Force kill this connection
        """
        self.killed = True
        # Cancel timeouts
        if self._idle_deferred.active():
            self._idle_deferred.cancel()
        if self._retry_deferred.active():
            self._retry_deferred.cancel()
        # If we are not done yet, signal the force kill to the other end
        if self.state != UTPConnectionStateEnum.CS_FINALIZED:
            current_time = get_time_microseconds()
            frame = {
                'type': UTPTypeEnum.ST_RESET,
                'version': 1,
                'extension': UTPExtensionEnum.EX_DATA,
                'connection_id': self.conn_id_send,
                'timestamp_microseconds': current_time,
                'timestamp_difference_microseconds': current_time - self.last_timestamp,
                'wnd_size': 0,
                'seq_nr': self.seq_nr,
                'ack_nr': self.ack_nr,
                'data': ""
            }
            self.state = UTPConnectionStateEnum.CS_FINALIZED
            return frame
        return None


class UTPSendingConnection(UTPConnection):
    """
    A uTP connection for the initiator, trying to send data.
    """

    def __init__(self, data):
        super(UTPSendingConnection, self).__init__()
        self.conn_id_recv = random.randint(0, 65535)
        self.conn_id_send = (self.conn_id_recv + 1) % 65536
        self.seq_nr = 1
        self.data = data
        # Keep track of the offset in the data we are sending
        self.data_offset = 0L
        # Keep track of all un-ack'd frames
        self.send_buffer = {}
        # If we have transmitted the final sequence number, we will store it
        self.final_seq = -1
        # The window size
        self.window_open = UTP_WINDOW_SIZE

    def is_complete(self):
        """
        A sending connection is complete when its state is finalized and there are no more un-ack'd frames.
        Or if it was hard-killed.
        """
        return ((self.state == UTPConnectionStateEnum.CS_FINALIZED) and (len(self.send_buffer.keys()) == 0))\
               or self.killed

    def create_syn(self):
        """
        Produce a syn frame.
        """
        self.state = UTPConnectionStateEnum.CS_SYN_SENT
        self.window_open -= 1
        frame = {
            'type': UTPTypeEnum.ST_SYN,
            'version': 1,
            'extension': UTPExtensionEnum.EX_DATA,
            'connection_id': self.conn_id_recv,
            'timestamp_microseconds': get_time_microseconds(),
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
        """
        Callback for when a frame is received (as a Dispersy payload).
        """
        super(UTPSendingConnection, self).on_frame(payload)
        # If we got a new ack, remove it from the outstanding frames
        if payload.ack_nr in self.send_buffer:
            del self.send_buffer[payload.ack_nr]
            # We have opened up a new spot in our window, we should not
            # grow the window past the remaining data however.
            if self.state == UTPConnectionStateEnum.CS_CONNECTED:
                self.window_open = min(self.window_open + 1, len(self.send_buffer.keys()))
            else:
                self.window_open += 1
            # If we receive the final ACK, we set our state to finalized.
            # Note that we may still have to perform some retransmissions.
            if payload.ack_nr == self.final_seq:
                self.state = UTPConnectionStateEnum.CS_FINALIZED
        # If we got hard-killed, don't respond.
        if self.killed:
            return []
        # Otherwise, handle the ACK from the receiver
        if payload.type == UTPTypeEnum.ST_STATE:
            return self.on_state(payload)
        # Or keep silent if this is some unexpected frame
        return []

    def _yield_data(self):
        """
        Generate more data to send.
        This is done by taking the next MAX_UTP_DATA bytes from self.data starting at self.data_offset.
        """
        if self.data_offset == len(self.data):
            return None
        end = self.data_offset + MAX_UTP_DATA
        data_slice = self.data[self.data_offset:end]
        self.data_offset += len(data_slice)
        return data_slice

    def on_state(self, payload):
        """
        We received an ACK.
        This may have a piggybacked request for retransmission.
        """
        if self.state != UTPConnectionStateEnum.CS_FINALIZED:
            self.state = UTPConnectionStateEnum.CS_CONNECTED
        self.ack_nr = payload.seq_nr

        current_time = get_time_microseconds()

        # Check if the receiver wants anything retransmitted
        retransmission = []
        if payload.extension_data and self.window_open == 0:
            retransmit_frame = self.send_buffer.get(int(payload.extension_data), None)
            if retransmit_frame:
                # Update the frame with current window size and timestamp statistics
                retransmit_frame['timestamp_microseconds'] = current_time
                retransmit_frame['timestamp_difference_microseconds'] = current_time - payload.timestamp_microseconds
                retransmit_frame['wnd_size'] = self.window_open
                retransmission = [retransmit_frame, ]

        # If our current window allows us to send more data, do so.
        frames = []
        while self.window_open > 0:
            data = self._yield_data()

            # We might be at the end of our data
            if not data:
                # If the receiver requests a retransmission, don't ST_FIN just yet
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
    """
    A uTP connection for a receiver.
    """

    def __init__(self, callback, retransmission_tuple):
        super(UTPReceivingConnection, self).__init__()
        # Keep track of our received frames
        self.receive_buffer = {}
        # The callback to call when this stream is complete
        self.callback = callback
        # The sequence number of the syn frame (SHOULD always be 1)
        self.syn_seq_nr = 0
        # The (callback, candidate) to use when we want to retransmit out of our own volition
        self.retransmisson_tuple = retransmission_tuple

    def is_complete(self):
        """
        A receiving connection is complete when (1) its state is finalized, (2) all received packets form a linearly
        increasing sequence from min to max and (3) the the final received frame is an ST_FIN.
        Or if it was hard-killed.
        """
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
        """
        Callback for when a frame is received (as a Dispersy payload).
        """
        self.receive_buffer[payload.seq_nr] = payload
        super(UTPReceivingConnection, self).on_frame(payload)
        if self.killed:
            return []
        out = []
        if (self.state == UTPConnectionStateEnum.CS_NONE) and (payload.type == UTPTypeEnum.ST_SYN):
            out = self.on_syn(payload)
        if (self.state != UTPConnectionStateEnum.CS_NONE) and (payload.type in [UTPTypeEnum.ST_DATA, UTPTypeEnum.ST_FIN]):
            out = self.on_data(payload)
        # Check for an uninterrupted and complete sequence of frames when the sender thinks he is done
        if self.state == UTPConnectionStateEnum.CS_FINALIZED:
            complete_data = ""
            pkey = None
            broken = False
            for key in sorted(self.receive_buffer.keys()):
                if (pkey is not None) and (((pkey + 1) % 65536) != key):
                    # Immediately ask for a retransmission if we are not done
                    self.try_retransmit()
                    broken = True
                    break
                complete_data = complete_data + self.receive_buffer[key].data
                pkey = key
            # If all is well, we are done: signal our callback
            if not broken and self.receive_buffer[key].type == UTPTypeEnum.ST_FIN:
                self.callback(self.retransmisson_tuple[1], complete_data)
                self.killed = True
        return out

    def try_retransmit(self):
        """
        Find the next missing frame and ask for a retransmission using our most recently sent ACK.
        """
        should_exit = super(UTPReceivingConnection, self).try_retransmit()
        if should_exit:
            return True
        for i in xrange(1, len(self.receive_buffer.keys()) + 2):
            if ((self.syn_seq_nr + i) % 65536) not in self.receive_buffer:
                current_time = get_time_microseconds()
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
        """
        Callback for when a syn frame is received. Answer with an ACK.
        """
        self.conn_id_recv = (payload.connection_id + 1) % 65536
        self.conn_id_send = payload.connection_id
        self.seq_nr = random.randint(0, 65535)
        self.ack_nr = payload.seq_nr
        self.state = UTPConnectionStateEnum.CS_SYN_RECV
        self.syn_seq_nr = payload.seq_nr

        current_time = get_time_microseconds()
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
        """
        Callback for when a data frame is received. Answer with an ACK.
        Check if this data is out of order/window, if so: piggyback a request for retransmission.
        """
        if payload.seq_nr in self.receive_buffer:
            return []
        self.ack_nr = payload.seq_nr
        if self.state == UTPConnectionStateEnum.CS_SYN_RECV:
            self.state = UTPConnectionStateEnum.CS_CONNECTED

        current_time = get_time_microseconds()

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
