import time

# The maximum amount of bytes sent in a UTP UDP frame
MAX_UTP_DATA = 400
# The maximum amount of time a connection can spend without receiving data, before being declared dead
MAX_UTP_IDLE = 10.0
# The maximum amount of time a connection can spend without receiving data, before a retransmission is sent
UTP_RETRY_TIME = .5
# The number of packets in a UTP connection window
UTP_WINDOW_SIZE = 10


def get_time_microseconds():
    """
    Get the current time (since epoch) in microseconds.
    """
    seconds = time.time()
    return long(seconds * 1000000)
