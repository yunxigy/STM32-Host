# -*- coding: utf-8 -*-
"""RTCM3 差分数据中继服务。

链路：

    基准站 4G 模块 --(8017, 十六进制文本或原始二进制)--> 本服务 --(8018, 原始二进制)--> 多台流动站

设计要点：

1. 8017 同时只保留一个基准站，新连接会顶替旧连接；
2. 8018 允许多台流动站同时接入，全部被动接收，不做鉴权；
3. 基准站发来的十六进制文本先还原成字节，再按 RTCM3 结构
   (0xD3 + 10bit 长度 + 负载 + CRC24Q) 切帧。切帧保证每个流动站
   收到的都是完整帧，不会从一帧中间开始，也顺带挡掉了串口里的脏字节；
4. 新流动站接入时先补发上一个完整历元，缩短首次 RTK 固定的时间；
5. 每台流动站有独立发送队列，慢连接只丢自己的包，不会阻塞基准站；
6. 如果收到的数据长期解析不出合法 RTCM3 帧，自动降级成原始字节透传，
   避免因为基准站配置不同导致整条链路完全不通。
"""

import collections
import re
import select
import socket
import threading
import time

RTCM3_PREAMBLE = 0xD3
RTCM3_MAX_PAYLOAD = 1023
RTCM3_HEADER_BYTES = 3
RTCM3_CRC_BYTES = 3
RTCM3_MAX_MESSAGE = RTCM3_HEADER_BYTES + RTCM3_MAX_PAYLOAD + RTCM3_CRC_BYTES
CRC24Q_POLY = 0x1864CFB

_HEX_DIGITS = frozenset('0123456789abcdefABCDEF')
_HEX_SEPARATORS = frozenset(' \t\r\n,;:|')
_HANDSHAKE_PATTERN = re.compile(r'^(BASE|SOURCE|ROVER|CLIENT)[\s,:;]*(.*)$', re.IGNORECASE)
_PREFIX_PATTERNS = (
    re.compile(rb'^[A-Za-z_][A-Za-z0-9_]{0,15}\s*=\s*[0-9A-Za-z_.\-]{1,16}\s*[,:;]\s*'),
    re.compile(rb'^\d{1,6}\s*[,:;]\s*'),
)


def _build_crc24q_table():
    table = []
    for index in range(256):
        crc = index << 16
        for _ in range(8):
            crc <<= 1
            if crc & 0x1000000:
                crc ^= CRC24Q_POLY
        table.append(crc & 0xFFFFFF)
    return tuple(table)


_CRC24Q_TABLE = _build_crc24q_table()


def crc24q(data):
    """RTCM3 帧尾使用的 CRC-24Q，多项式 0x1864CFB，初值 0。"""
    crc = 0
    table = _CRC24Q_TABLE
    for byte in data:
        crc = ((crc << 8) & 0xFFFFFF) ^ table[((crc >> 16) ^ byte) & 0xFF]
    return crc


def rtcm_message_type(frame):
    """取 RTCM3 帧的 12 位报文号，例如 1005 / 1006 / 1074 / 1124。"""
    if len(frame) < 5:
        return 0
    return (frame[3] << 4) | (frame[4] >> 4)


def describe_message_type(msg_type):
    """给前端用的电文中文说明，未知类型返回空串。"""
    return RTCM_MESSAGE_NAMES.get(msg_type, '')


RTCM_MESSAGE_NAMES = {
    1005: '基准站坐标',
    1006: '基准站坐标+天线高',
    1007: '天线描述',
    1032: '接收机描述',
    1033: '接收机/天线描述',
    1074: 'GPS MSM4',
    1077: 'GPS MSM7',
    1084: 'GLONASS MSM4',
    1087: 'GLONASS MSM7',
    1094: 'Galileo MSM4',
    1097: 'Galileo MSM7',
    1114: 'QZSS MSM4',
    1124: 'BDS MSM4',
    1127: 'BDS MSM7',
    1230: 'GLONASS 码偏差',
}


def _now_ms():
    return int(time.time() * 1000)


class RtcmFrameParser:
    """从连续字节流里切出完整的、CRC 正确的 RTCM3 帧。"""

    def __init__(self, validate_crc=True, max_buffer=32768):
        self.validate_crc = validate_crc
        self.max_buffer = max_buffer
        self.crc_errors = 0
        self.discarded = 0
        self._buffer = bytearray()

    def reset(self):
        self._buffer.clear()

    def feed(self, data):
        frames = []
        buffer = self._buffer
        buffer.extend(data)
        while len(buffer) >= RTCM3_HEADER_BYTES:
            if buffer[0] != RTCM3_PREAMBLE:
                index = buffer.find(bytes((RTCM3_PREAMBLE,)))
                if index < 0:
                    self.discarded += len(buffer)
                    buffer.clear()
                    break
                self.discarded += index
                del buffer[:index]
                continue

            length = ((buffer[1] & 0x03) << 8) | buffer[2]
            total = length + RTCM3_HEADER_BYTES + RTCM3_CRC_BYTES
            if len(buffer) < total:
                break

            frame = bytes(buffer[:total])
            if self.validate_crc and crc24q(frame[:-RTCM3_CRC_BYTES]) != int.from_bytes(
                frame[-RTCM3_CRC_BYTES:], 'big'
            ):
                self.crc_errors += 1
                del buffer[0]
                continue

            frames.append(frame)
            del buffer[:total]

        if len(buffer) > self.max_buffer:
            self.discarded += len(buffer)
            buffer.clear()
        return frames


class HexStreamDecoder:
    """把 "D3 00 15 3E" / "D300153E" / "d3,00,15" 之类的十六进制文本还原成字节。

    允许任意分隔符，也允许分片落在半个字节上（进位保留到下一次）。
    """

    __slots__ = ('_carry',)

    def __init__(self):
        self._carry = ''

    def reset(self):
        self._carry = ''

    def feed(self, text):
        digits = ''.join(ch for ch in text if ch in _HEX_DIGITS)
        if not digits:
            return b''
        if self._carry:
            digits = self._carry + digits
            self._carry = ''
        if len(digits) % 2:
            self._carry = digits[-1]
            digits = digits[:-1]
        if not digits:
            return b''
        try:
            return bytes.fromhex(digits)
        except ValueError:
            return b''


def _looks_like_hex(sample):
    if not sample:
        return False
    usable = sum(1 for byte in sample if chr(byte) in _HEX_DIGITS or chr(byte) in _HEX_SEPARATORS)
    return usable >= len(sample) * 0.95


def detect_payload_format(chunk):
    """判断基准站这条连接发的是原始二进制、十六进制文本，还是别的东西。"""
    if not chunk:
        return None
    if chunk[0] == RTCM3_PREAMBLE:
        return 'binary'
    if _looks_like_hex(chunk[:256]):
        return 'hex'
    return 'text'


def strip_prefix_before_frame(chunk):
    """剥离 "device_id=1," / "1:" 这类前缀，仅在后面紧跟 RTCM3 帧头(0xD3)时才动手。

    这样 "30,31,32" 这类逗号分隔的纯十六进制不会被误伤。
    """
    for pattern in _PREFIX_PATTERNS:
        match = pattern.match(chunk)
        if not match:
            continue
        remainder = chunk[match.end():]
        if not remainder:
            continue
        try:
            text = remainder[:16].decode('ascii', 'ignore')
        except (UnicodeDecodeError, AttributeError):
            continue
        digits = ''.join(ch for ch in text if ch in _HEX_DIGITS)
        if len(digits) >= 2 and digits[:2].upper() == 'D3':
            return remainder
    return None


def decode_hex_chunk(decoder, chunk):
    """解码一段十六进制文本，按行剥离可能存在的设备前缀。"""
    if b'\n' not in chunk:
        stripped = strip_prefix_before_frame(chunk)
        return decoder.feed((stripped or chunk).decode('ascii', 'ignore'))

    output = bytearray()
    for line in chunk.split(b'\n'):
        if line:
            stripped = strip_prefix_before_frame(line)
            output += decoder.feed((stripped or line).decode('ascii', 'ignore'))
    return bytes(output)


def split_handshake(chunk):
    """取连接开头的 ASCII 握手行。

    返回 (剩余字节, 标识, 角色)。角色为 'source'(BASE) / 'client'(ROVER) / None。
    没有握手行时原样返回 chunk。
    """
    head = chunk[:64]
    newline = head.find(b'\n')
    if newline < 0:
        return chunk, None, None
    line = head[:newline].strip()
    if not line or len(line) > 40:
        return chunk, None, None
    try:
        text = line.decode('ascii')
    except UnicodeDecodeError:
        return chunk, None, None
    match = _HANDSHAKE_PATTERN.match(text)
    if not match:
        return chunk, None, None
    keyword = match.group(1).upper()
    role = 'source' if keyword in ('BASE', 'SOURCE') else 'client'
    return chunk[newline + 1:], (match.group(2).strip() or None), role


class _RateMeter:
    """滑动窗口速率统计，单位 字节/秒。"""

    __slots__ = ('_lock', '_window', '_samples', '_total')

    def __init__(self, window_seconds=5.0):
        self._lock = threading.Lock()
        self._window = window_seconds
        self._samples = collections.deque()
        self._total = 0

    def add(self, count):
        with self._lock:
            self._total += count
            self._samples.append((time.monotonic(), self._total))
            self._prune(time.monotonic())

    def _prune(self, now):
        limit = now - self._window
        while len(self._samples) > 1 and self._samples[0][0] < limit:
            self._samples.popleft()

    def rate(self):
        with self._lock:
            now = time.monotonic()
            self._prune(now)
            if len(self._samples) < 2:
                return 0.0
            (start_time, start_value) = self._samples[0]
            (end_time, end_value) = self._samples[-1]
            span = end_time - start_time
            if span <= 0:
                return 0.0
            return max(0.0, (end_value - start_value) / span)


class _Subscriber:
    """一台流动站及其待发队列。"""

    __slots__ = (
        'sid', 'conn', 'addr', 'ident', 'connected_at_ms', 'queue', 'pending_bytes',
        'lock', 'event', 'closed', 'bytes_sent', 'chunks_sent', 'dropped', 'last_send_at_ms',
    )

    def __init__(self, sid, conn, addr):
        self.sid = sid
        self.conn = conn
        self.addr = f'{addr[0]}:{addr[1]}'
        self.ident = None
        self.connected_at_ms = _now_ms()
        self.queue = collections.deque()
        self.pending_bytes = 0
        self.lock = threading.Lock()
        self.event = threading.Event()
        self.closed = False
        self.bytes_sent = 0
        self.chunks_sent = 0
        self.dropped = 0
        self.last_send_at_ms = 0

    def offer(self, chunk, max_pending_bytes):
        if not chunk:
            return
        with self.lock:
            if self.closed:
                return
            while self.queue and self.pending_bytes + len(chunk) > max_pending_bytes:
                dropped = self.queue.popleft()
                self.pending_bytes -= len(dropped)
                self.dropped += 1
            self.queue.append(chunk)
            self.pending_bytes += len(chunk)
        self.event.set()

    def take(self):
        with self.lock:
            if not self.queue:
                return b''
            data = b''.join(self.queue)
            self.queue.clear()
            self.pending_bytes = 0
            return data

    def close(self):
        with self.lock:
            self.closed = True
            self.queue.clear()
            self.pending_bytes = 0
        self.event.set()


def _close_quietly(conn):
    if conn is None:
        return
    try:
        conn.shutdown(socket.SHUT_RDWR)
    except (AttributeError, OSError):
        pass
    try:
        conn.close()
    except (AttributeError, OSError):
        pass


class RtcmRelay:
    """RTCM3 差分中继。一个基准站进、多台流动站出。"""

    def __init__(
        self,
        port_in=8017,
        port_out=8018,
        host='0.0.0.0',
        max_subscribers=32,
        max_pending_bytes=65536,
        max_epoch_bytes=16384,
        frame_detect_bytes=1536,
        validate_crc=True,
        logger=print,
    ):
        self.port_in = port_in
        self.port_out = port_out
        self.host = host
        self.max_subscribers = max_subscribers
        self.max_pending_bytes = max_pending_bytes
        self.max_epoch_bytes = max_epoch_bytes
        self.frame_detect_bytes = frame_detect_bytes
        self.validate_crc = validate_crc
        self._logger = logger
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._started = False

        self._source = None
        self._subs = collections.OrderedDict()
        self._next_sub_id = 1
        self._servers = []

        self._epoch_frames = []
        self._epoch_types = set()
        self._epoch_bytes = 0
        self._last_epoch = b''
        self._last_epoch_types = []
        self._epochs = 0

        self._frames_total = 0
        self._bytes_in_total = 0
        self._bytes_out_total = 0
        self._last_frame_at_ms = 0
        self._in_rate = _RateMeter()
        self._out_rate = _RateMeter()
        self._last_source_error = ''

    # ------------------------------------------------------------------ 生命周期

    def start(self):
        if self._started:
            return
        self._started = True
        threading.Thread(
            target=self._accept_loop, args=(self.port_in, 'source'),
            name=f'rtcm-source-{self.port_in}', daemon=True,
        ).start()
        threading.Thread(
            target=self._accept_loop, args=(self.port_out, 'client'),
            name=f'rtcm-client-{self.port_out}', daemon=True,
        ).start()

    def stop(self):
        self._stop.set()
        with self._lock:
            subs = list(self._subs.values())
            source = self._source
            servers = list(self._servers)
            self._servers.clear()
        for sub in subs:
            sub.close()
            _close_quietly(sub.conn)
        if source is not None:
            _close_quietly(source.get('conn'))
        for server in servers:
            _close_quietly(server)

    def _accept_loop(self, port, role):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server.bind((self.host, port))
            server.listen(16)
        except OSError as exc:
            self._logger(f'RTCM {role} 端口 {port} 监听失败: {exc}')
            _close_quietly(server)
            return

        with self._lock:
            self._servers.append(server)
        self._logger(f'RTCM {role} 端口已监听: {self.host}:{port}')
        while not self._stop.is_set():
            try:
                conn, addr = server.accept()
            except OSError:
                break
            try:
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            except OSError:
                pass
            target = self._run_source if role == 'source' else self._run_subscriber
            threading.Thread(target=target, args=(conn, addr), daemon=True).start()
        _close_quietly(server)

    # ------------------------------------------------------------------ 基准站侧

    def _run_source(self, conn, addr):
        label = f'{addr[0]}:{addr[1]}'
        conn.settimeout(1.0)
        state = {
            'parser': RtcmFrameParser(validate_crc=self.validate_crc),
            'decoder': HexStreamDecoder(),
            'mode': None,
            'framed': True,
            'frames': 0,
            'bytes': 0,
            'head': b'',
            'text_logged': False,
        }
        source = {
            'addr': label,
            'conn': conn,
            'ident': None,
            'mode': None,
            'connected_at_ms': _now_ms(),
            'last_frame_at_ms': 0,
            'bytes_in': 0,
            'frames': 0,
            'crc_errors': 0,
        }

        with self._lock:
            previous = self._source
            self._source = source
        if previous is not None and previous.get('conn') is not conn:
            _close_quietly(previous.get('conn'))
            self._logger(f'RTCM 基准站连接被替换，断开旧连接 {previous.get("addr")}')

        self._logger(f'RTCM 基准站({self.port_in})接入: {label}')
        try:
            while not self._stop.is_set():
                try:
                    chunk = conn.recv(4096)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not chunk:
                    break
                self._on_source_chunk(source, state, chunk)
        except Exception as exc:  # noqa: BLE001 - 单连接异常不应影响中继
            self._logger(f'RTCM 基准站异常 {label}: {exc}')
        finally:
            with self._lock:
                if self._source is source:
                    self._source = None
            _close_quietly(conn)
            self._logger(f'RTCM 基准站断开: {label}')

    def _on_source_chunk(self, source, state, chunk):
        if state['mode'] is None:
            # 首包可能被 TCP 拆开（例如 "BAS" + "E\r\n"），攒够再判定，避免把半行握手当成数据。
            pending = state['head'] + chunk
            if len(pending) < 8 and b'\n' not in pending:
                state['head'] = pending
                return
            state['head'] = b''

            rest, ident, role = split_handshake(pending)
            if role == 'client':
                self._logger(
                    f'RTCM {source["addr"]} 是流动站握手，不应连接 {self.port_in}，已断开'
                )
                _close_quietly(source['conn'])
                return
            if ident:
                with self._lock:
                    source['ident'] = ident
            chunk = rest if role == 'source' else pending
            if not chunk:
                return
            mode = detect_payload_format(chunk)
            if mode == 'text':
                # 兼容 "device_id=1,D3 00 ..." 这类带前缀的写法
                stripped = strip_prefix_before_frame(chunk)
                if stripped:
                    stripped_mode = detect_payload_format(stripped)
                    if stripped_mode in ('hex', 'binary'):
                        self._logger(f'RTCM 基准站 {source["addr"]} 已剥离设备前缀')
                        chunk = stripped
                        mode = stripped_mode
            if mode is None:
                return
            state['mode'] = mode
            with self._lock:
                source['mode'] = mode
            if mode == 'text':
                self._logger(
                    f'RTCM 基准站 {source["addr"]} 发送的不是十六进制或 RTCM3，'
                    f'已忽略。开头内容: {chunk[:60]!r}'
                )
                return
            self._logger(f'RTCM 基准站 {source["addr"]} 数据格式判定: {mode}')

        if state['mode'] == 'text':
            with self._lock:
                source['bytes_in'] += len(chunk)
            return

        if state['mode'] == 'hex':
            payload = decode_hex_chunk(state['decoder'], chunk)
        else:
            payload = chunk

        if not payload:
            return
        self._ingest(source, state, payload)

    def _ingest(self, source, state, payload):
        state['bytes'] += len(payload)
        with self._lock:
            source['bytes_in'] += len(payload)
            self._bytes_in_total += len(payload)
        self._in_rate.add(len(payload))

        if not state['framed']:
            self._broadcast(payload)
            return

        parser = state['parser']
        frames = parser.feed(payload)
        if frames:
            state['frames'] += len(frames)
            with self._lock:
                source['frames'] += len(frames)
                source['crc_errors'] = parser.crc_errors
                self._frames_total += len(frames)
            for frame in frames:
                self._publish_frame(source, frame)
            return

        with self._lock:
            source['crc_errors'] = parser.crc_errors

        if state['frames'] == 0 and state['bytes'] >= self.frame_detect_bytes:
            state['framed'] = False
            parser.reset()
            self._last_source_error = '未解析出合法 RTCM3 帧，已降级为原始透传'
            self._logger(
                f'RTCM 警告: 基准站 {source["addr"]} 已收 {state["bytes"]} 字节但仍未解析出'
                f'合法 RTCM3 帧，降级为原始字节透传（流动站仍会收到数据，但无法保证帧对齐）'
            )
            self._broadcast(payload)

    def _publish_frame(self, source, frame):
        msg_type = rtcm_message_type(frame)
        now_ms = _now_ms()
        with self._lock:
            source['last_frame_at_ms'] = now_ms
            self._last_frame_at_ms = now_ms
            if self._epoch_frames and (
                msg_type in self._epoch_types
                or self._epoch_bytes + len(frame) > self.max_epoch_bytes
            ):
                self._last_epoch = b''.join(self._epoch_frames)
                self._last_epoch_types = sorted(self._epoch_types)
                self._epoch_frames = []
                self._epoch_types = set()
                self._epoch_bytes = 0
                self._epochs += 1
            self._epoch_frames.append(frame)
            self._epoch_types.add(msg_type)
            self._epoch_bytes += len(frame)
        self._broadcast(frame)

    def _broadcast(self, chunk):
        with self._lock:
            subs = list(self._subs.values())
            relayed = len(chunk) * len(subs)
            self._bytes_out_total += relayed
        if not subs:
            return
        self._out_rate.add(relayed)
        for sub in subs:
            sub.offer(chunk, self.max_pending_bytes)

    # ------------------------------------------------------------------ 流动站侧

    def _run_subscriber(self, conn, addr):
        with self._lock:
            if len(self._subs) >= self.max_subscribers:
                over_limit = True
            else:
                over_limit = False
                sid = self._next_sub_id
                self._next_sub_id += 1
        if over_limit:
            self._logger(f'RTCM 流动站已满({self.max_subscribers})，拒绝 {addr[0]}:{addr[1]}')
            _close_quietly(conn)
            return

        sub = _Subscriber(sid, conn, addr)
        with self._lock:
            self._subs[sid] = sub
            backlog = self._last_epoch
        self._logger(f'RTCM 流动站 #{sid} 接入: {sub.addr}')

        if backlog:
            sub.offer(backlog, self.max_pending_bytes)

        conn.settimeout(10.0)
        try:
            while not self._stop.is_set() and not sub.closed:
                data = sub.take()
                if data:
                    try:
                        conn.sendall(data)
                    except (OSError, socket.timeout):
                        break
                    with self._lock:
                        sub.bytes_sent += len(data)
                        sub.chunks_sent += 1
                        sub.last_send_at_ms = _now_ms()
                else:
                    sub.event.wait(0.2)
                    sub.event.clear()
                    if sub.closed:
                        break

                try:
                    readable = select.select([conn], [], [], 0)[0]
                except (OSError, ValueError):
                    break
                if readable:
                    try:
                        inbound = conn.recv(1024)
                    except (OSError, socket.timeout):
                        break
                    if not inbound:
                        break
                    if sub.ident is None:
                        _, ident, _ = split_handshake(inbound)
                        if ident:
                            with self._lock:
                                sub.ident = ident
                            self._logger(f'RTCM 流动站 #{sid} 标识: {ident}')
        except Exception as exc:  # noqa: BLE001
            self._logger(f'RTCM 流动站 #{sid} 异常: {exc}')
        finally:
            sub.close()
            with self._lock:
                self._subs.pop(sid, None)
            _close_quietly(conn)
            self._logger(f'RTCM 流动站 #{sid} 断开: {sub.addr}')

    # ------------------------------------------------------------------ 状态快照

    def snapshot(self):
        now_ms = _now_ms()
        with self._lock:
            source = self._source
            base = None
            if source is not None:
                last_frame_at_ms = int(source.get('last_frame_at_ms') or 0)
                base = {
                    'connected': True,
                    'addr': source.get('addr'),
                    'ident': source.get('ident'),
                    'mode': source.get('mode'),
                    'connected_at_ms': int(source.get('connected_at_ms') or 0),
                    'bytes_in': int(source.get('bytes_in') or 0),
                    'frames': int(source.get('frames') or 0),
                    'crc_errors': int(source.get('crc_errors') or 0),
                    'last_frame_at_ms': last_frame_at_ms,
                    'frame_age_ms': now_ms - last_frame_at_ms if last_frame_at_ms else -1,
                }
            rovers = [
                {
                    'sid': sub.sid,
                    'addr': sub.addr,
                    'ident': sub.ident,
                    'connected_at_ms': sub.connected_at_ms,
                    'bytes_sent': sub.bytes_sent,
                    'chunks_sent': sub.chunks_sent,
                    'dropped': sub.dropped,
                    'pending_bytes': sub.pending_bytes,
                }
                for sub in self._subs.values()
            ]
            message_types = list(self._last_epoch_types)
            epochs = self._epochs
            frames_total = self._frames_total
            bytes_in_total = self._bytes_in_total
            bytes_out_total = self._bytes_out_total
            last_frame_at_ms = self._last_frame_at_ms
            warning = self._last_source_error

        return {
            'enabled': True,
            'port_in': self.port_in,
            'port_out': self.port_out,
            'base': base,
            'base_online': bool(base),
            'rovers': rovers,
            'rover_count': len(rovers),
            'message_types': message_types,
            'message_type_names': {str(t): describe_message_type(t) for t in message_types},
            'epochs': epochs,
            'frames_total': frames_total,
            'bytes_in_total': bytes_in_total,
            'bytes_out_total': bytes_out_total,
            'rate_in': round(self._in_rate.rate(), 1),
            'rate_out': round(self._out_rate.rate(), 1),
            'last_frame_at_ms': last_frame_at_ms,
            'frame_age_ms': now_ms - last_frame_at_ms if last_frame_at_ms else -1,
            'warning': warning,
            'updated_at_ms': now_ms,
        }
