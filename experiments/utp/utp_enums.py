class Enum(object):
    """
    Enumeration class base.

    Subclasses can define class variables which will be interpreted as Enum values, for example:

        .. sourcecode:: none

            class MyEnum(Enum):
                SomeName = 0
                SomeOtherName = "hello"

            # All equal:
            MyEnum.SomeName # == 0
            MyEnum('SomeName') # == 0
            MyEnum()['SomeName'] # == 0
            MyEnum.dict()['SomeName'] # == 0

    Note that it is the subclass's responsibility to assign unique values to each name.
    """

    def __init__(self, value=None):
        """
        Get an Enum instance with a certain enum value.
        """
        if value:
            getattr(self, value) # throws AttributeError if this is a bogus value
        self.value = value

    def __getitem__(self, key):
        """
        Dict style access to the value of a certain name for this **instance**.
        """
        return getattr(self, key)

    def __cmp__(self, other):
        """
        Compare this Enum **instance** to another object.

        Returns:
            -1 if self < other
            0 if self == other
            1 if self > other
        """
        if self.__lt__(other):
            return -1
        elif self.__eq__(other):
            return 0
        else:
            return 1

    def __lt__(self, other):
        """
        Check if the value of this Enum **instance**'s name is
        less than the other Enum instance OR some other value.
        """
        if isinstance(other, Enum):
            return self[self.value] < other[other.value]
        else:
            return self[self.value] < other

    def __le__(self, other):
        """
        Check if the value of this Enum **instance**'s name is
        less than or equal to the other Enum instance OR some other value.
        """
        if isinstance(other, Enum):
            return self[self.value] <= other[other.value]
        else:
            return self[self.value] <= other

    def __eq__(self, other):
        """
        Check if the value of this Enum **instance**'s name is
        equal to the other Enum instance OR some other value.
        """
        if isinstance(other, Enum):
            return self[self.value] == other[other.value]
        else:
            return self[self.value] == other

    def __ne__(self, other):
        """
        Check if the value of this Enum **instance**'s name is
        not equal to the other Enum instance OR some other value.
        """
        if isinstance(other, Enum):
            return self[self.value] != other[other.value]
        else:
            return self[self.value] != other

    def __gt__(self, other):
        """
        Check if the value of this Enum **instance**'s name is
        greater than the other Enum instance OR some other value.
        """
        if isinstance(other, Enum):
            return self[self.value] > other[other.value]
        else:
            return self[self.value] > other

    def __ge__(self, other):
        """
        Check if the value of this Enum **instance**'s name is
        greater than or equal to the other Enum instance OR some other value.
        """
        if isinstance(other, Enum):
            return self[self.value] >= other[other.value]
        else:
            return self[self.value] >= other

    @classmethod
    def dict(cls):
        """
        Return a mapping of names to values for this Enum **class**.
        """
        parent = dir(cls)
        base = dir(Enum)
        return {attr: getattr(cls, attr) for attr in parent if attr not in base and not callable(getattr(cls, attr))}

    @classmethod
    def names(cls):
        """
        Return all registered names for this Enum **class**.
        """
        return cls.dict().keys()

    @classmethod
    def values(cls):
        """
        Return all values for this Enum **class**.
        """
        return cls.dict().values()


class UTPTypeEnum(Enum):
    """
    Enumerator for uTP frame types.

    ST_DATA: A data frame
    ST_FIN: Frame signaling the end of the uTP transmission
    ST_STATE: ACK of a data frame
    ST_RESET: Hard kill of a connection
    ST_SYN: Request for connection
    """

    ST_DATA = 0
    ST_FIN = 1
    ST_STATE = 2
    ST_RESET = 3
    ST_SYN = 4


class UTPConnectionStateEnum(Enum):
    """
    Enumerator for uTP connection states

    CS_NONE: No frames have been sent
    CS_SYN_SENT: Sender sent a syn frame to receiver, but not ACK'd yet
    CS_SYN_RECV: Receiver got a syn frame, but no data yet
    CS_CONNECTED: Data is being sent between sender and receiver
    CS_FINALIZED: The connection *should* not be getting any further data
    """

    CS_NONE = 0
    CS_SYN_SENT = 1
    CS_SYN_RECV = 2
    CS_CONNECTED = 3
    CS_FINALIZED = 4


class UTPExtensionEnum(Enum):
    """
    Enumerator for uTP frame extension types.

    EX_DATA: Frame without extension
    EX_SELECTIVE_ACK: Frame with selective ACK extension (UNSUPPORTED)
    EX_SINGLE_ACK: Frame with custom retransmission extension
    """

    EX_DATA = 0
    EX_SELECTIVE_ACK = 1
    EX_SINGLE_ACK = 2
