from enum import IntEnum


SOF1 = 0xA5
SOF2 = 0x5A

MAX_PAYLOAD = 128
HEADER_SIZE = 8
CRC_SIZE = 2
MAX_FRAME_SIZE = HEADER_SIZE + MAX_PAYLOAD + CRC_SIZE


class Node(IntEnum):
    PI = 0x01
    P4 = 0x02
    WROOM = 0x03
    S3 = 0x04


class Service(IntEnum):
    SYSTEM = 0x00
    LED = 0x01
    MUSIC = 0x02
    SD = 0x03
    RADAR = 0x04
    AUDIO = 0x05
    EMERGENCY = 0x06
    POWER = 0x07
    PROJECTOR = 0x08
    DETECTION = 0x09
    SLEEP = 0x0A


class Command(IntEnum):
    PING = 0x01
    PONG = 0x02

    ECHO = 0x03
    ECHO_RESPONSE = 0x04

    STATUS_REQUEST = 0x10
    STATUS_RESPONSE = 0x11

    START = 0x20
    STOP = 0x21
    SET = 0x22
    DATA = 0x23
    PAUSE = 0x24
    RESUME = 0x25
    NEXT = 0x26
    PREVIOUS = 0x27
    APPLY = 0x28
    APPLY_RESULT = 0x29
    CALL_KEEPALIVE = 0x2A
    EVENT_POLL = 0x2B
    EVENT_REPLY = 0x2C
    MUSIC_INFO = 0x30
    MUSIC_CATALOG = 0x31
    MUSIC_TRACK = 0x32
    MUSIC_PLAY = 0x33
    MUSIC_TIMELINE = 0x34
    MUSIC_SEEK = 0x35


class EmergencySource(IntEnum):
    BUTTON = 0x01


class EmergencyAction(IntEnum):
    ACK = 0x01


class AudioDirection(IntEnum):
    FIELD_TX = 0x01
    CONTROL_TX = 0x02


class AudioDataType(IntEnum):
    EVENT = 0x01
    CODEC2 = 0x02
    CONTROL_WINDOW = 0x03


class AudioEvent(IntEnum):
    CALL_STARTED = 0x01
    CALL_ENDED = 0x02
    DIRECTION_CHANGED = 0x03
    PREPARATION_FAILED = 0x04
    ENDPOINT_FAILED = 0x05


class CallOrigin(IntEnum):
    NORMAL = 0x00
    EMERGENCY = 0x01


class EmergencyEvent(IntEnum):
    ACKED = 0x01



class Codec2Mode(IntEnum):
    MODE_2400 = 0x01


CODEC2_2400_BYTES_PER_FRAME = 6
CODEC2_MAX_FRAMES_PER_PACKET = 8
AUDIO_CODEC2_META_SIZE = 11
