# -*- coding: utf-8 -*-
import socket
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rtcm_relay import (  # noqa: E402
    HexStreamDecoder,
    RtcmFrameParser,
    RtcmRelay,
    crc24q,
    decode_hex_chunk,
    detect_payload_format,
    rtcm_message_type,
    split_handshake,
    strip_prefix_before_frame,
)


def bytes_from(text):
    return bytes.fromhex(text.replace(' ', '').replace('\n', ''))


# 现场抓到的真实帧（UniCore UM980 基准站）
FRAME_1006 = bytes_from('''
D3 00 15 3E E0 00 03 BA 69 A1 E6 D2 8A 82 E4 54 4B 08 D9 3F
F1 CC 00 00 D1 1A 94
''')

FRAME_1033 = bytes_from('''
D3 00 44 40 90 00 0E 41 44 56 4E 55 4C 4C 41 4E 54 45 4E 4E 41
FF 05 61 30 30 30 31 0D 55 4E 49 43 4F 52 45 20 55 4D 39 38 30
0B 31 31 38 33 33 2D 32 36 35 36 32 10 66 66 33 62 37 64 37 33
37 64 30 39 34 31 31 64 46 CB 27
''')


def build_frame(msg_type, payload=b''):
    body = bytes(((msg_type >> 4) & 0xFF, (msg_type & 0x0F) << 4)) + payload
    header = bytes((0xD3, (len(body) >> 8) & 0x03, len(body) & 0xFF))
    return header + body + crc24q(header + body).to_bytes(3, 'big')


FRAME_1074 = build_frame(1074, bytes(range(1, 60)))
FRAME_1064 = build_frame(1064, b'\x00\x01\x02')


def free_ports(count):
    """一次性申请多个互不相同的空闲端口（申请期间保持占用，避免返回同一个端口）。"""
    holders = []
    try:
        ports = []
        for _ in range(count):
            holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            holder.bind(('127.0.0.1', 0))
            holders.append(holder)
            ports.append(holder.getsockname()[1])
        return ports
    finally:
        for holder in holders:
            holder.close()


def connect_with_retry(port, timeout=3.0):
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            return socket.create_connection(('127.0.0.1', port), timeout=1.0)
        except OSError as exc:
            last_error = exc
            time.sleep(0.02)
    raise AssertionError(f'无法连接端口 {port}: {last_error}')


def wait_for(predicate, timeout=3.0, interval=0.01):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def recv_until(sock, expected, timeout=3.0):
    sock.settimeout(0.2)
    data = b''
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            chunk = sock.recv(4096)
        except socket.timeout:
            continue
        if not chunk:
            break
        data += chunk
        if expected in data:
            break
    return data


class CrcTest(unittest.TestCase):
    def test_real_frames_have_valid_crc(self):
        for frame in (FRAME_1006, FRAME_1033, FRAME_1074):
            with self.subTest(frame=frame[:6].hex()):
                self.assertEqual(
                    crc24q(frame[:-3]), int.from_bytes(frame[-3:], 'big')
                )

    def test_message_type(self):
        self.assertEqual(rtcm_message_type(FRAME_1006), 1006)
        self.assertEqual(rtcm_message_type(FRAME_1033), 1033)
        self.assertEqual(rtcm_message_type(FRAME_1074), 1074)

    def test_corrupted_crc_is_rejected(self):
        broken = bytearray(FRAME_1006)
        broken[-1] ^= 0xFF
        parser = RtcmFrameParser()
        self.assertEqual(parser.feed(bytes(broken)), [])
        self.assertEqual(parser.crc_errors, 1)


class FrameParserTest(unittest.TestCase):
    def test_single_frame(self):
        parser = RtcmFrameParser()
        self.assertEqual(parser.feed(FRAME_1006), [FRAME_1006])

    def test_split_across_chunks(self):
        parser = RtcmFrameParser()
        collected = []
        stream = FRAME_1006 + FRAME_1033 + FRAME_1074
        for index in range(0, len(stream), 7):
            collected.extend(parser.feed(stream[index:index + 7]))
        self.assertEqual(collected, [FRAME_1006, FRAME_1033, FRAME_1074])

    def test_garbage_prefix_is_skipped(self):
        parser = RtcmFrameParser()
        frames = parser.feed(b'\x00\x11\x22JUNK' + FRAME_1033)
        self.assertEqual(frames, [FRAME_1033])

    def test_resync_after_bad_frame(self):
        broken = bytearray(FRAME_1033)
        broken[-2] ^= 0xFF
        parser = RtcmFrameParser()
        frames = parser.feed(bytes(broken) + FRAME_1006)
        self.assertEqual(frames, [FRAME_1006])

    def test_crc_check_can_be_disabled(self):
        broken = bytearray(FRAME_1006)
        broken[-1] ^= 0xFF
        parser = RtcmFrameParser(validate_crc=False)
        self.assertEqual(parser.feed(bytes(broken)), [bytes(broken)])


class HexDecoderTest(unittest.TestCase):
    def test_space_separated(self):
        decoder = HexStreamDecoder()
        self.assertEqual(decoder.feed('D3 00 15 3E'), bytes.fromhex('D300153E'))

    def test_compact(self):
        decoder = HexStreamDecoder()
        self.assertEqual(decoder.feed('D300153E'), bytes.fromhex('D300153E'))

    def test_lowercase_and_mixed_separators(self):
        decoder = HexStreamDecoder()
        self.assertEqual(decoder.feed('d3,00;15|3e'), bytes.fromhex('D300153E'))

    def test_odd_nibble_carry(self):
        decoder = HexStreamDecoder()
        self.assertEqual(decoder.feed('D3 00 1'), bytes.fromhex('D300'))
        self.assertEqual(decoder.feed('5 3E'), bytes.fromhex('153E'))

    def test_crlf_ignored(self):
        decoder = HexStreamDecoder()
        self.assertEqual(decoder.feed('D3 00 15 3E\r\n'), bytes.fromhex('D300153E'))


class DetectFormatTest(unittest.TestCase):
    def test_binary(self):
        self.assertEqual(detect_payload_format(FRAME_1006), 'binary')

    def test_hex(self):
        self.assertEqual(detect_payload_format(b'D3 00 15 3E E0 00\r\n'), 'hex')

    def test_plain_text(self):
        self.assertEqual(detect_payload_format(b'hello world, this is a dtu\r\n'), 'text')


class PrefixTest(unittest.TestCase):
    def test_prefix_before_frame_is_stripped(self):
        chunk = b'1,' + b'D3 00 15 3E'
        self.assertEqual(strip_prefix_before_frame(chunk), b'D3 00 15 3E')

    def test_key_value_prefix_is_stripped(self):
        chunk = b'device_id=2:' + b'D300153E'
        self.assertEqual(strip_prefix_before_frame(chunk), b'D300153E')

    def test_comma_separated_hex_is_untouched(self):
        self.assertIsNone(strip_prefix_before_frame(b'30,31,32,33'))

    def test_line_based_decode_with_prefix(self):
        """一帧一行的写法可以安全剥离每行前缀。"""
        decoder = HexStreamDecoder()
        line = ' '.join(f'{byte:02X}' for byte in FRAME_1006)
        text = f'1,{line}\r\n'.encode() + f'device_id=2,{line}\r\n'.encode()
        self.assertEqual(decode_hex_chunk(decoder, text), FRAME_1006 + FRAME_1006)

    def test_prefix_mid_frame_is_kept(self):
        """前缀出现在帧中间时不做剥离，避免破坏字节对齐。"""
        self.assertIsNone(strip_prefix_before_frame(b'2,3E E0 00'))

    def test_decode_without_newlines(self):
        decoder = HexStreamDecoder()
        self.assertEqual(decode_hex_chunk(decoder, b'D3 00 15 3E'), bytes.fromhex('D300153E'))


class HandshakeTest(unittest.TestCase):
    def test_base_line(self):
        rest, ident, role = split_handshake(b'BASE\nD3 00 15')
        self.assertEqual(rest, b'D3 00 15')
        self.assertIsNone(ident)
        self.assertEqual(role, 'source')

    def test_base_with_id(self):
        _, ident, role = split_handshake(b'BASE,base-01\r\n')
        self.assertEqual(ident, 'base-01')
        self.assertEqual(role, 'source')

    def test_rover_line(self):
        _, ident, role = split_handshake(b'ROVER,3\r\n')
        self.assertEqual(ident, '3')
        self.assertEqual(role, 'client')

    def test_rtcm_hex_is_not_a_handshake(self):
        chunk = b'D3 00 15 3E\n'
        rest, ident, role = split_handshake(chunk)
        self.assertEqual(rest, chunk)
        self.assertIsNone(role)


class EndToEndTest(unittest.TestCase):
    def setUp(self):
        self.port_in, self.port_out = free_ports(2)
        self.assertNotEqual(self.port_in, self.port_out)
        self.relay = RtcmRelay(
            port_in=self.port_in,
            port_out=self.port_out,
            frame_detect_bytes=5000,
            logger=lambda *args, **kwargs: None,
        )
        self.relay.start()
        self.addCleanup(self.relay.stop)

    def _connect_base(self):
        return connect_with_retry(self.port_in)

    def _connect_rover(self):
        before = self.relay.snapshot()['rover_count']
        rover = connect_with_retry(self.port_out)
        self.addCleanup(rover.close)
        self.assertTrue(
            wait_for(lambda: self.relay.snapshot()['rover_count'] > before),
            '流动站没有被中继登记',
        )
        return rover

    def test_hex_stream_is_forwarded_as_binary(self):
        base = self._connect_base()
        self.addCleanup(base.close)
        rover = self._connect_rover()

        hex_text = ' '.join(f'{byte:02X}' for byte in FRAME_1006) + '\r\n'
        base.sendall(hex_text.encode('ascii'))

        received = recv_until(rover, FRAME_1006)
        self.assertIn(FRAME_1006, received)

    def test_raw_binary_stream_is_forwarded(self):
        base = self._connect_base()
        self.addCleanup(base.close)
        rover = self._connect_rover()

        base.sendall(FRAME_1033)
        received = recv_until(rover, FRAME_1033)
        self.assertIn(FRAME_1033, received)

    def test_multiple_rovers_get_same_frames(self):
        base = self._connect_base()
        self.addCleanup(base.close)
        first = self._connect_rover()
        second = self._connect_rover()

        base.sendall(FRAME_1074)
        self.assertIn(FRAME_1074, recv_until(first, FRAME_1074))
        self.assertIn(FRAME_1074, recv_until(second, FRAME_1074))

    def test_new_rover_receives_last_epoch_backlog(self):
        base = self._connect_base()
        self.addCleanup(base.close)

        stream = FRAME_1006 + FRAME_1033 + FRAME_1006
        base.sendall(stream)
        self.assertTrue(
            wait_for(lambda: self.relay.snapshot()['epochs'] >= 1),
            '没有识别出完整历元',
        )

        rover = self._connect_rover()
        received = recv_until(rover, FRAME_1033)
        self.assertIn(FRAME_1006, received)
        self.assertIn(FRAME_1033, received)

    def test_snapshot_reports_base_and_message_types(self):
        base = self._connect_base()
        self.addCleanup(base.close)
        base.sendall(FRAME_1006 + FRAME_1033 + FRAME_1064 + FRAME_1006)

        self.assertTrue(wait_for(lambda: (self.relay.snapshot()['base'] or {}).get('frames')))

        snapshot = self.relay.snapshot()
        self.assertTrue(snapshot['base_online'])
        self.assertEqual(snapshot['port_in'], self.port_in)
        self.assertEqual(snapshot['port_out'], self.port_out)
        self.assertGreaterEqual(snapshot['frames_total'], 4)
        self.assertIn(1006, snapshot['message_types'])
        self.assertIn(1033, snapshot['message_types'])
        self.assertEqual(snapshot['message_type_names']['1033'], '接收机/天线描述')

    def test_prefixed_one_frame_per_line(self):
        """基准站若按 "1,D3 00 .." 一帧一行发送，流动站仍收到纯净帧。"""
        base = self._connect_base()
        self.addCleanup(base.close)
        rover = self._connect_rover()

        line = ' '.join(f'{byte:02X}' for byte in FRAME_1006)
        base.sendall(f'1,{line}\r\n'.encode('ascii'))

        received = recv_until(rover, FRAME_1006)
        self.assertIn(FRAME_1006, received)
        self.assertEqual(self.relay.snapshot()['frames_total'], 1)

    def test_handshake_split_across_tcp_chunks(self):
        base = self._connect_base()
        self.addCleanup(base.close)
        rover = self._connect_rover()

        base.sendall(b'BAS')
        time.sleep(0.05)
        base.sendall(b'E,base-01\r\n')
        base.sendall(FRAME_1006)

        self.assertIn(FRAME_1006, recv_until(rover, FRAME_1006))
        self.assertEqual(self.relay.snapshot()['base']['ident'], 'base-01')

    def test_degrade_to_raw_when_not_rtcm(self):
        self.relay.frame_detect_bytes = 8
        base = self._connect_base()
        self.addCleanup(base.close)
        rover = self._connect_rover()

        payload = bytes((0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08))
        base.sendall(' '.join(f'{byte:02X}' for byte in payload).encode('ascii'))

        received = recv_until(rover, payload)
        self.assertIn(payload, received)
        self.assertIn('降级', self.relay.snapshot()['warning'])


if __name__ == '__main__':
    unittest.main()
