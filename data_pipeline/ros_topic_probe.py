#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSPresetProfiles
from rosidl_runtime_py.utilities import get_message


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Return success once one ROS message is observed on a topic.")
    parser.add_argument("--topic", required=True, help="Topic name to probe.")
    parser.add_argument("--topic-type", default="", help="ROS interface type, e.g. sensor_msgs/msg/Image.")
    parser.add_argument("--timeout", type=float, default=1.0, help="Seconds to wait for one message.")
    parser.add_argument("--min-messages", type=int, default=1, help="Minimum number of messages to observe.")
    parser.add_argument(
        "--require-float-array-change",
        action="store_true",
        help="Require a Float32MultiArray topic to change over the sampled window.",
    )
    parser.add_argument(
        "--min-max-delta",
        type=float,
        default=1e-6,
        help="Minimum absolute change required when --require-float-array-change is used.",
    )
    return parser.parse_args(argv)


def resolve_topic_type(node: Node, topic: str, timeout_s: float) -> str:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        for topic_name, type_names in node.get_topic_names_and_types():
            if topic_name == topic and type_names:
                return type_names[0]
        rclpy.spin_once(node, timeout_sec=0.1)
    raise RuntimeError(f"Topic type not found for {topic}")


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    rclpy.init(args=None)
    node = rclpy.create_node("data_pipeline_topic_probe")
    subscription = None
    received = False
    messages_seen = 0
    first_float_array = None
    last_float_array = None

    try:
        topic_type = args.topic_type or resolve_topic_type(node, args.topic, args.timeout)
        msg_type = get_message(topic_type)

        def _callback(msg: object) -> None:
            nonlocal received, messages_seen, first_float_array, last_float_array
            received = True
            messages_seen += 1
            if args.require_float_array_change:
                data = getattr(msg, "data", None)
                if isinstance(data, (list, tuple)):
                    values = [float(value) for value in data]
                else:
                    values = [float(value) for value in list(data)]
                if first_float_array is None:
                    first_float_array = values
                last_float_array = values

        subscription = node.create_subscription(
            msg_type,
            args.topic,
            _callback,
            QoSPresetProfiles.SENSOR_DATA.value,
        )

        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline and messages_seen < args.min_messages:
            remaining = max(0.0, deadline - time.monotonic())
            rclpy.spin_once(node, timeout_sec=min(0.2, remaining))
        if messages_seen < args.min_messages:
            return 1
        if args.require_float_array_change:
            if first_float_array is None or last_float_array is None:
                return 1
            max_delta = max(
                (abs(a - b) for a, b in zip(first_float_array, last_float_array)),
                default=0.0,
            )
            return 0 if max_delta >= args.min_max_delta else 1
        return 0 if received else 1
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        if subscription is not None:
            node.destroy_subscription(subscription)
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
