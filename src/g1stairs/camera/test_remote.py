# Author: Codex (IIC)
from array import array
from contextlib import ExitStack
from io import BytesIO, StringIO
import socket
import struct
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from . import remote


def image(width, height, encoding, data, step, big=False):
    return SimpleNamespace(width=width, height=height, encoding=encoding, data=array("B", data),
                           step=step, is_bigendian=big, header=SimpleNamespace(stamp=SimpleNamespace(sec=12, nanosec=34)))


class RemoteTests(unittest.TestCase):
    def test_tty_shows_bgr_pixels_with_padded_rows(self):
        msg = image(2, 1, "bgr8", bytes([255, 0, 0, 0, 0, 255, 84, 19]), 8)
        self.assertEqual(remote.render_image(msg, 2, 1), ".-")

    def test_depth_respects_endian_and_distinguishes_missing_near_and_far(self):
        for big in (True, False):
            data = struct.pack((">" if big else "<") + "4H", 0, 300, 900, 177)
            self.assertEqual(remote.render_image(image(3, 1, "16UC1", data, 8, big), 3, 1), " @.")

    def test_infinite_and_nan_float_depth_are_blank(self):
        data = struct.pack("<3f", float("inf"), 0.7, float("nan"))
        self.assertEqual(remote.render_image(image(3, 1, "32FC1", data, 12), 3, 1), " @ ")

    def test_invalid_image_does_not_read_across_rows(self):
        with self.assertRaisesRegex(ValueError, "stride"):
            remote.render_image(image(2, 1, "rgb8", b"abc", 3), 2, 1)

    def test_packet_rejects_unknown_channel_oversize_empty_and_truncation(self):
        for channel, size in [(77, 0), (5, 65537), (2, remote.IMAGE_LIMIT + 1), (1, 0)]:
            with self.assertRaises(ValueError):
                remote.read_packet(BytesIO(remote.HEADER.pack(channel, size)))
        with self.assertRaises(EOFError):
            remote.read_packet(BytesIO(remote.HEADER.pack(3, 100) + b"short"))
        self.assertEqual(remote.read_packet(BytesIO(remote.KEEPALIVE)), (0, b""))

    def test_socket_forwarder_and_local_sensor_only_publication(self):
        # Exercise actual socket I/O and callback routing. The ROS runtime is
        # replaced here so this regression can also run without an SDK or camera.
        incoming = {}
        expected = {"/usb/color": b"color", "/lowstate": b"state"}
        ros = Mock()
        ros.ok.side_effect = [True, False]
        node = Mock()

        def subscribe(msg_type, topic, callback, qos, *, raw):
            self.assertTrue(raw)
            incoming[topic] = callback
            return topic
        node.create_subscription.side_effect = subscribe

        def spin(node, timeout_sec):
            for topic, data in expected.items():
                incoming[topic](data)
                incoming[topic](data)  # second camera/state update is rate limited
        ros.spin_once.side_effect = spin

        args = SimpleNamespace(**{ch.option: ch.default_topic for ch in remote.CHANNELS.values()},
                               hz=5, port=remote.PORT)
        args.color_topic = "/usb/color"
        sender, receiver = socket.socketpair()
        types = {name: type(name, (), {}) for name in ("Image", "CameraInfo", "LowState")}
        sent = image(1, 1, "mono8", b"x", 1)
        state = object()
        deserializer = Mock(side_effect=lambda payload, cls: {b"color": sent, b"state": state}[payload])
        modules = {"rclpy.qos": SimpleNamespace(QoSProfile=Mock(), QoSReliabilityPolicy=SimpleNamespace(BEST_EFFORT=2)),
                   "rclpy.serialization": SimpleNamespace(deserialize_message=deserializer)}
        local_ros, local_node = Mock(), Mock()
        local_ros.ok.side_effect = [True, True, False]
        pubs = {}
        def publisher(msg_type, topic, qos):
            pubs[topic] = Mock()
            return pubs[topic]
        local_node.create_publisher.side_effect = publisher

        with ExitStack() as stack:
            stack.enter_context(receiver)
            stack.enter_context(sender)
            stack.enter_context(patch.dict("sys.modules", modules))
            stack.enter_context(patch.object(remote, "message_types", return_value=types))
            stack.enter_context(patch("sys.stdout", new=StringIO()))
            stack.enter_context(patch.object(socket, "create_connection", return_value=receiver))
            remote.send_samples(ros, node, sender, args, types)
            sender.shutdown(socket.SHUT_WR)
            remote.receive(local_ros, local_node, args)
        self.assertEqual(set(pubs), {"/g1_remote/color/image_raw", "/g1_remote/lowstate"})
        pubs["/g1_remote/color/image_raw"].publish.assert_called_once_with(sent)
        pubs["/g1_remote/lowstate"].publish.assert_called_once_with(state)
        self.assertEqual(node.destroy_subscription.call_count, 5)

    def test_packet_accepts_partial_network_writes(self):
        packet = remote.HEADER.pack(5, 128) + b"B" * 128
        tx, rx = socket.socketpair()
        with tx, rx, rx.makefile("rb") as stream:
            def send_split():
                for offset in range(0, len(packet), 3):
                    tx.sendall(packet[offset:offset+3])
            writer = threading.Thread(target=send_split)
            writer.start()
            try:
                self.assertEqual(remote.read_packet(stream), (5, b"B" * 128))
            finally:
                writer.join(2)
        self.assertFalse(writer.is_alive())


if __name__ == "__main__":
    unittest.main()
