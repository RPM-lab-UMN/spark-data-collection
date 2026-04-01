#!/usr/bin/python3

from __future__ import annotations

import argparse
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import rosbag2_py
from rclpy.serialization import deserialize_message
from rosidl_runtime_py.utilities import get_message


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
TELEOP_ROOT = REPO_ROOT / "TeleopSoftware"
if str(TELEOP_ROOT) not in sys.path:
    sys.path.insert(0, str(TELEOP_ROOT))

from data_pipeline.pipeline_utils import DEFAULT_RAW_EPISODES_DIR, detect_bag_storage_id, normalize_active_arms
from teleop_runtime_config import build_default_runtime_config
from UR.arms import UR


TELEOP_ACTIVITY_TOPIC = "/spark/session/teleop_active"
SERVO_TIME_S = 0.001
SERVO_LOOKAHEAD_TIME_S = 0.05
SERVO_GAIN = 200
HOME_SPEED_RAD_S = 0.5
HOME_ACCEL_RAD_S2 = 0.5


@dataclass(frozen=True)
class ReplayArmConfig:
    canonical_name: str
    display_name: str
    ip_address: str
    enable_control: bool
    enable_gripper: bool
    home_joints_rad: tuple[float, ...]


@dataclass(frozen=True)
class ReplayEvent:
    timestamp_ns: int
    sequence_index: int
    kind: str
    arm: str | None
    value: Any
    topic: str


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Replay a raw V2 episode back to the UR hardware.")
    parser.add_argument("episode", help="Episode id, raw episode directory, or bag directory.")
    parser.add_argument("--arm", action="append", default=[], help="Replay only the specified arm(s).")
    parser.add_argument("--speed", type=float, default=1.0, help="Global replay speed multiplier. Default: 1.0.")
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")
    return parser


def load_runtime_arm_configs() -> dict[str, ReplayArmConfig]:
    runtime_config = build_default_runtime_config()
    result: dict[str, ReplayArmConfig] = {}
    for arm in runtime_config.arms:
        canonical = str(arm.name).strip().lower()
        result[canonical] = ReplayArmConfig(
            canonical_name=canonical,
            display_name=arm.name,
            ip_address=arm.ip_address,
            enable_control=bool(arm.enable_control),
            enable_gripper=bool(arm.enable_gripper),
            home_joints_rad=tuple(float(value) for value in arm.home_joints_rad),
        )
    return result


def resolve_episode_dir(episode_ref: str) -> Path:
    candidate = Path(str(episode_ref)).expanduser()
    if candidate.is_dir():
        if (candidate / "bag").is_dir():
            return candidate
        if (candidate / "metadata.yaml").is_file():
            return candidate.parent
    if candidate.exists():
        raise RuntimeError(f"Unsupported episode reference: {candidate}")

    episode_dir = DEFAULT_RAW_EPISODES_DIR / str(episode_ref).strip()
    if (episode_dir / "bag").is_dir():
        return episode_dir
    raise FileNotFoundError(f"Raw episode not found: {episode_ref}")


def command_topics_for_arm(arm: str) -> tuple[str, str]:
    return (
        f"/spark/{arm}/teleop/cmd_joint_state",
        f"/spark/{arm}/teleop/cmd_gripper_state",
    )


def extract_message_timestamp_ns(msg: Any, bag_timestamp_ns: int) -> int:
    header = getattr(msg, "header", None)
    stamp = getattr(header, "stamp", None)
    if stamp is None:
        return bag_timestamp_ns
    sec = int(getattr(stamp, "sec", 0))
    nanosec = int(getattr(stamp, "nanosec", 0))
    if sec == 0 and nanosec == 0:
        return bag_timestamp_ns
    return sec * 1_000_000_000 + nanosec


def load_replay_events(
    bag_dir: Path,
    replay_arms: list[str],
    *,
    storage_id: str,
) -> tuple[list[ReplayEvent], dict[str, int]]:
    reader = rosbag2_py.SequentialReader()
    storage_options = rosbag2_py.StorageOptions(uri=str(bag_dir), storage_id=storage_id)
    converter_options = rosbag2_py.ConverterOptions("", "")
    reader.open(storage_options, converter_options)

    topic_types = {topic.name: topic.type for topic in reader.get_all_topics_and_types()}
    relevant_topics = {TELEOP_ACTIVITY_TOPIC}
    arm_joint_topics: dict[str, str] = {}
    arm_gripper_topics: dict[str, str] = {}
    for arm in replay_arms:
        joint_topic, gripper_topic = command_topics_for_arm(arm)
        arm_joint_topics[arm] = joint_topic
        arm_gripper_topics[arm] = gripper_topic
        relevant_topics.add(joint_topic)
        relevant_topics.add(gripper_topic)

    missing_topics = sorted(topic for topic in relevant_topics if topic not in topic_types)
    if missing_topics:
        raise RuntimeError(f"Replay bag is missing required replay topics: {missing_topics}")

    message_types = {topic: get_message(topic_types[topic]) for topic in relevant_topics}
    counts = {"activity": 0}
    for arm in replay_arms:
        counts[f"{arm}_joint"] = 0
        counts[f"{arm}_gripper"] = 0

    events: list[ReplayEvent] = []
    sequence_index = 0
    while reader.has_next():
        topic, data, bag_timestamp_ns = reader.read_next()
        if topic not in relevant_topics:
            continue
        msg = deserialize_message(data, message_types[topic])
        if topic == TELEOP_ACTIVITY_TOPIC:
            events.append(
                ReplayEvent(
                    timestamp_ns=int(bag_timestamp_ns),
                    sequence_index=sequence_index,
                    kind="activity",
                    arm=None,
                    value=bool(msg.data),
                    topic=topic,
                )
            )
            counts["activity"] += 1
        else:
            matched_arm = next((arm for arm, name in arm_joint_topics.items() if name == topic), None)
            if matched_arm is not None:
                positions = [float(value) for value in msg.position[:6]]
                if len(positions) < 6:
                    raise RuntimeError(f"Expected 6 joint positions on {topic}, got {len(positions)}")
                events.append(
                    ReplayEvent(
                        timestamp_ns=extract_message_timestamp_ns(msg, int(bag_timestamp_ns)),
                        sequence_index=sequence_index,
                        kind="joint",
                        arm=matched_arm,
                        value=positions,
                        topic=topic,
                    )
                )
                counts[f"{matched_arm}_joint"] += 1
            else:
                matched_arm = next((arm for arm, name in arm_gripper_topics.items() if name == topic), None)
                if matched_arm is None:
                    sequence_index += 1
                    continue
                if len(msg.position) < 1:
                    raise RuntimeError(f"Expected 1 gripper position on {topic}")
                events.append(
                    ReplayEvent(
                        timestamp_ns=extract_message_timestamp_ns(msg, int(bag_timestamp_ns)),
                        sequence_index=sequence_index,
                        kind="gripper",
                        arm=matched_arm,
                        value=float(msg.position[0]),
                        topic=topic,
                    )
                )
                counts[f"{matched_arm}_gripper"] += 1
        sequence_index += 1

    if not events:
        raise RuntimeError(f"No replayable events found in {bag_dir}")

    events.sort(key=lambda event: (event.timestamp_ns, event.sequence_index))
    return events, counts


def detect_replay_arms(bag_dir: Path, requested_arms: list[str], storage_id: str) -> list[str]:
    reader = rosbag2_py.SequentialReader()
    storage_options = rosbag2_py.StorageOptions(uri=str(bag_dir), storage_id=storage_id)
    converter_options = rosbag2_py.ConverterOptions("", "")
    reader.open(storage_options, converter_options)
    topic_names = {topic.name for topic in reader.get_all_topics_and_types()}

    available_arms = []
    for arm in ("lightning", "thunder"):
        joint_topic, gripper_topic = command_topics_for_arm(arm)
        if joint_topic in topic_names and gripper_topic in topic_names:
            available_arms.append(arm)

    if requested_arms:
        requested = normalize_active_arms(requested_arms)
        missing = [arm for arm in requested if arm not in available_arms]
        if missing:
            raise RuntimeError(f"Requested replay arms are not fully replayable from this bag: {missing}")
        return requested

    if not available_arms:
        raise RuntimeError("No replayable V2 teleop command topics were found in this bag.")
    return available_arms


def confirm_replay(episode_dir: Path, replay_arms: list[str], speed: float, counts: dict[str, int], duration_s: float) -> bool:
    print("Replay summary:")
    print(f"  Episode: {episode_dir}")
    print(f"  Arms: {', '.join(replay_arms)}")
    print(f"  Speed: {speed}x")
    print(f"  Duration: {duration_s:.2f} s")
    for arm in replay_arms:
        print(
            f"  {arm}: {counts.get(f'{arm}_joint', 0)} joint commands, "
            f"{counts.get(f'{arm}_gripper', 0)} gripper commands"
        )
    print(f"  Teleop activity messages: {counts.get('activity', 0)}")
    confirm = input("Replay raw episode on hardware? [y/N] ").strip().lower()
    return confirm in {"y", "yes"}


def initialize_ur(runtime_arms: list[ReplayArmConfig]) -> UR:
    display_names = [arm.display_name for arm in runtime_arms]
    ip_addresses = [arm.ip_address for arm in runtime_arms]
    enable_gripper = {arm.display_name: arm.enable_gripper for arm in runtime_arms}
    enable_control = {arm.display_name: arm.enable_control for arm in runtime_arms}
    urs = UR(display_names, ip_addresses, enable_grippers=enable_gripper)
    for arm in runtime_arms:
        print(f"Connecting {arm.display_name}...")
        if not urs.init_arm(arm.display_name, enable_control=enable_control):
            raise RuntimeError(f"Failed to initialize {arm.display_name}.")
    return urs


def move_arms_home(urs: UR, runtime_arms: list[ReplayArmConfig]) -> None:
    print("Moving replay arm(s) to home...")

    def move_arm_home(arm: ReplayArmConfig) -> None:
        if arm.enable_gripper:
            try:
                urs.get_gripper(arm.display_name).set(0)
            except Exception:
                pass
        urs.moveJ(
            arm.display_name,
            (list(arm.home_joints_rad), HOME_SPEED_RAD_S, HOME_ACCEL_RAD_S2),
        )

    threads = [threading.Thread(target=move_arm_home, args=(arm,), daemon=True) for arm in runtime_arms]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


def stop_selected_arms(urs: UR, runtime_arms: list[ReplayArmConfig]) -> None:
    for arm in runtime_arms:
        try:
            urs.stop(arm.display_name)
        except Exception:
            pass


def replay_events(urs: UR, runtime_arms: list[ReplayArmConfig], events: list[ReplayEvent], speed: float) -> None:
    arm_lookup = {arm.canonical_name: arm for arm in runtime_arms}
    first_timestamp_ns = events[0].timestamp_ns
    teleop_active = False
    wall_start = time.monotonic()

    print("Starting raw replay...")
    for event in events:
        target_s = (event.timestamp_ns - first_timestamp_ns) / 1_000_000_000.0 / speed
        remaining_s = wall_start + target_s - time.monotonic()
        if remaining_s > 0:
            time.sleep(remaining_s)

        if event.kind == "activity":
            next_active = bool(event.value)
            if teleop_active and not next_active:
                stop_selected_arms(urs, runtime_arms)
            teleop_active = next_active
            continue

        if not teleop_active:
            continue

        if event.arm is None:
            continue
        arm = arm_lookup[event.arm]
        if event.kind == "joint":
            urs.servoJ(
                arm.display_name,
                (
                    list(event.value),
                    0.0,
                    0.0,
                    SERVO_TIME_S,
                    SERVO_LOOKAHEAD_TIME_S,
                    SERVO_GAIN,
                ),
            )
        elif event.kind == "gripper" and arm.enable_gripper:
            gripper_value = max(0.0, min(1.0, float(event.value)))
            urs.get_gripper(arm.display_name).set(int(round(gripper_value * 255.0)))

    stop_selected_arms(urs, runtime_arms)
    print("Replay finished.")


def main() -> int:
    args = build_arg_parser().parse_args()
    if float(args.speed) <= 0.0:
        raise ValueError("--speed must be greater than 0.")

    episode_dir = resolve_episode_dir(args.episode)
    bag_dir = episode_dir / "bag"
    if not bag_dir.is_dir():
        raise FileNotFoundError(f"Missing bag directory: {bag_dir}")

    storage_id = detect_bag_storage_id(bag_dir)
    replay_arms = detect_replay_arms(bag_dir, list(args.arm), storage_id)
    runtime_arm_configs = load_runtime_arm_configs()
    missing_runtime = [arm for arm in replay_arms if arm not in runtime_arm_configs]
    if missing_runtime:
        raise RuntimeError(f"Replay arm runtime config is missing for: {missing_runtime}")
    runtime_arms = [runtime_arm_configs[arm] for arm in replay_arms]

    events, counts = load_replay_events(bag_dir, replay_arms, storage_id=storage_id)
    duration_s = (events[-1].timestamp_ns - events[0].timestamp_ns) / 1_000_000_000.0

    if not args.yes and not confirm_replay(episode_dir, replay_arms, float(args.speed), counts, duration_s):
        print("Replay canceled.")
        return 0

    urs: UR | None = None
    try:
        urs = initialize_ur(runtime_arms)
        move_arms_home(urs, runtime_arms)
        replay_events(urs, runtime_arms, events, float(args.speed))
    except KeyboardInterrupt:
        print("\nReplay interrupted.")
        if urs is not None:
            stop_selected_arms(urs, runtime_arms)
        return 130
    finally:
        if urs is not None:
            stop_selected_arms(urs, runtime_arms)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
