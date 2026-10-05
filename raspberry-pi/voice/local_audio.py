"""Optional Pi USB mic/AUX endpoint. Compressed relay stays independent.

Audio callbacks only enqueue or copy PCM. Encoding, decoding and PLC writes
run in workers. PTT tokens invalidate buffered samples during transitions.
"""
from __future__ import annotations
from array import array
import logging
import queue
import threading
import time

from protocol import AudioDirection, Codec2Mode
from .packet import VoicePacket
from .playback import Codec2Encoder, Codec2Decoder, PlaybackBuffer, upsample

LOG = logging.getLogger(__name__)


def downsample(pcm, rate):
    samples = array('h')
    samples.frombytes(bytes(pcm))
    factor = rate // 8000
    if len(samples) != 160 * factor:
        raise ValueError('Expected one 20ms capture frame')
    return array('h', (sum(samples[i:i + factor]) // factor
                       for i in range(0, len(samples), factor))).tobytes()


def device_id(value):
    return int(value) if isinstance(value, str) and value.isdecimal() else value


class LocalAudio:
    def __init__(self, relay, railing_id=1, mic_device=None,
                 speaker_device='bcm2835 Headphones', rate=48000, buffer_ms=600):
        self.relay = relay
        self.railing_id = railing_id
        self.mic_device = device_id(mic_device)
        self.speaker_device = device_id(speaker_device)
        self.rate = rate
        self.buffer = PlaybackBuffer(rate, buffer_ms)
        self.capture = queue.Queue(maxsize=8)
        self.field = queue.Queue(maxsize=12)
        self.stop = threading.Event()
        self.threads = []
        self.streams = []
        self.encoder = self.decoder = None
        self.play_token = None
        self.sent_packets = self.received_packets = 0
        self.capture_drops = self.field_drops = self.missing_packets = 0
        self.input_overflows = 0
        self.error = None

    def _token(self, direction):
        return self.relay.audio_token(self.railing_id, direction)

    def _capture_callback(self, indata, frames, time_info, status):
        if status.input_overflow:
            self.input_overflows += 1
        token = self._token(AudioDirection.CONTROL_TX)
        if token is None or self.stop.is_set():
            return
        try:
            self.capture.put_nowait((token, bytes(indata)))
        except queue.Full:
            self.capture_drops += 1

    def _output_callback(self, outdata, frames, time_info, status):
        token = self._token(AudioDirection.FIELD_TX)
        if self.stop.is_set() or token is None or token != self.play_token:
            outdata[:] = bytes(len(outdata))
            self.buffer.clear()
            return
        self.buffer.callback(outdata, frames, time_info, status)

    def enqueue_field(self, packet):
        if packet.railing_id != self.railing_id or self.stop.is_set():
            return
        token = self._token(AudioDirection.FIELD_TX)
        if token is None:
            return
        try:
            self.field.put_nowait((token, packet))
        except queue.Full:
            self.field_drops += 1

    def start(self, sd=None):
        if self.threads:
            return
        if sd is None:
            import sounddevice as sd
        self.stop.clear()
        try:
            sd.check_input_settings(device=self.mic_device, channels=1,
                                    dtype='int16', samplerate=self.rate)
            sd.check_output_settings(device=self.speaker_device, channels=1,
                                     dtype='int16', samplerate=self.rate)
            self.encoder = Codec2Encoder()
            self.decoder = Codec2Decoder()
            self.streams.append(sd.RawInputStream(device=self.mic_device, channels=1,
                dtype='int16', samplerate=self.rate, blocksize=self.rate // 50,
                callback=self._capture_callback))
            self.streams.append(sd.RawOutputStream(device=self.speaker_device, channels=1,
                dtype='int16', samplerate=self.rate, blocksize=self.rate // 50,
                callback=self._output_callback))
            self.relay.set_local_source(self.railing_id)
            self.relay.set_field_handler(self.enqueue_field)
            for target in (self._send_loop, self._receive_loop):
                thread = threading.Thread(target=self._worker, args=(target,), daemon=True,
                                          name='local-' + target.__name__)
                self.threads.append(thread)
                thread.start()
            for stream in self.streams:
                stream.start()
            LOG.info('Local audio ready rail=%d USB mic=%s AUX output=%s rate=%d; PTT gated',
                     self.railing_id, self.mic_device, self.speaker_device, self.rate)
        except Exception:
            self.close()
            raise

    def _worker(self, target):
        try:
            target()
        except Exception as exc:
            self.error = str(exc)
            self.stop.set()
            LOG.exception('Local audio failed; compressed relay remains available')

    def _send_loop(self):
        previous_token = None
        encoded = bytearray()
        sequence = 0
        while not self.stop.is_set():
            try:
                captured_token, pcm = self.capture.get(timeout=0.05)
            except queue.Empty:
                continue
            token = self._token(AudioDirection.CONTROL_TX)
            if token is None or token != captured_token:
                continue
            if token != previous_token:
                encoded.clear()
                self.encoder.close()
                self.encoder = Codec2Encoder()
                previous_token = token
            encoded.extend(self.encoder.encode(downsample(pcm, self.rate)))
            if len(encoded) == 48:
                packet = VoicePacket(self.railing_id, int(AudioDirection.CONTROL_TX),
                    int(Codec2Mode.MODE_2400), sequence, 8, 6, bytes(encoded))
                if self.relay.forward_control_packet(packet, token=token):
                    self.sent_packets += 1
                    sequence = (sequence + 1) & 0xffff
                encoded.clear()

    def _receive_loop(self):
        previous = last_packet = None
        previous_token = None
        while not self.stop.is_set():
            try:
                received_token, packet = self.field.get(timeout=0.05)
            except queue.Empty:
                if self._token(AudioDirection.FIELD_TX) is None:
                    self.buffer.clear()
                    self.play_token = None
                continue
            token = self._token(AudioDirection.FIELD_TX)
            if token is None or received_token != token:
                continue
            if token != previous_token:
                self.buffer.clear()
                previous = last_packet = None
                previous_token = token
                self.decoder.close()
                self.decoder = Codec2Decoder()
                self.play_token = token
            now = time.monotonic()
            if last_packet is not None and now - last_packet > 1:
                self.buffer.clear()
                previous = None
                self.decoder.close()
                self.decoder = Codec2Decoder()
            if previous is not None:
                delta = (packet.sequence - previous) & 0xffff
                if delta == 0 or delta >= 0x8000:
                    continue
                if delta > 1:
                    self.missing_packets += delta - 1
                    if delta <= 11:
                        self.buffer.push(bytes((delta - 1) * packet.frame_count * 320 * (self.rate // 8000)))
                    else:
                        self.buffer.clear()
                        self.decoder.close()
                        self.decoder = Codec2Decoder()
            pcm = self.decoder.decode(packet.data)
            if token == self._token(AudioDirection.FIELD_TX):
                self.buffer.push(upsample(pcm, self.rate // 8000))
                self.received_packets += 1
                previous, last_packet = packet.sequence, now

    def status(self):
        return dict(railing=self.railing_id, sent_packets=self.sent_packets,
                    received_packets=self.received_packets, capture_drops=self.capture_drops,
                    field_drops=self.field_drops, missing_packets=self.missing_packets,
                    input_overflows=self.input_overflows, error=self.error, **self.buffer.status())

    def close(self):
        self.stop.set()
        self.relay.set_field_handler(None)
        self.relay.set_local_source(None)
        for stream in self.streams:
            try:
                stream.stop()
            except Exception:
                LOG.exception("Failed to stop local audio stream")
            try:
                stream.close()
            except Exception:
                LOG.exception("Failed to close local audio stream")
        self.streams.clear()
        for thread in self.threads:
            thread.join(timeout=2)
        # Never free a ctypes Codec2 state while its worker is still using it.
        if any(thread.is_alive() for thread in self.threads):
            LOG.error('Local audio worker did not exit; retaining codec state')
            return
        self.threads.clear()
        for codec in (self.encoder, self.decoder):
            if codec:
                codec.close()
        self.encoder = self.decoder = None
        self.buffer.clear()
