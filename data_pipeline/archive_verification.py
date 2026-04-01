#!/usr/bin/python3

"""Verification helpers for archive-bag generation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import rosbag2_py
from rclpy.serialization import deserialize_message
from sensor_msgs.msg import CompressedImage
from sensor_msgs.msg import Image

from data_pipeline.pipeline_utils import read_bag_metadata


@dataclass(frozen=True)
class ArchiveImageTopicPair:
    source_topic: str
    archive_topic: str
    modality: str


def header_stamp_ns(msg: Any) -> int:
    stamp = msg.header.stamp
    return int(stamp.sec) * 1_000_000_000 + int(stamp.nanosec)


def topic_count_map(bag_dir: Path) -> dict[str, int]:
    metadata = read_bag_metadata(bag_dir)
    bag_info = metadata.get("rosbag2_bagfile_information", {})
    return {
        entry["topic_metadata"]["name"]: int(entry["message_count"])
        for entry in bag_info.get("topics_with_message_count", [])
    }


def collect_topic_messages(
    bag_dir: Path,
    storage_id: str,
    topic_type_map: dict[str, type[Any]],
) -> dict[str, list[Any]]:
    return {
        topic: [record["message"] for record in records]
        for topic, records in collect_topic_message_records(bag_dir, storage_id, topic_type_map).items()
    }


def collect_topic_message_records(
    bag_dir: Path,
    storage_id: str,
    topic_type_map: dict[str, type[Any]],
    *,
    trim_start_ns: int | None = None,
    trim_end_ns: int | None = None,
) -> dict[str, list[dict[str, Any]]]:
    reader = rosbag2_py.SequentialReader()
    reader.open(
        rosbag2_py.StorageOptions(uri=str(bag_dir), storage_id=storage_id),
        rosbag2_py.ConverterOptions("", ""),
    )
    messages: dict[str, list[dict[str, Any]]] = {topic: [] for topic in topic_type_map}
    while reader.has_next():
        topic, data, bag_timestamp_ns = reader.read_next()
        msg_type = topic_type_map.get(topic)
        if msg_type is None:
            continue
        bag_timestamp_ns = int(bag_timestamp_ns)
        if trim_start_ns is not None and bag_timestamp_ns < trim_start_ns:
            continue
        if trim_end_ns is not None and bag_timestamp_ns > trim_end_ns:
            continue
        messages[topic].append(
            {
                "bag_timestamp_ns": bag_timestamp_ns,
                "message": deserialize_message(data, msg_type),
            }
        )
    return messages


def compare_image_header_stamps(
    source_bag_dir: Path,
    source_storage_id: str,
    archive_bag_dir: Path,
    archive_storage_id: str,
    image_pairs: list[ArchiveImageTopicPair],
) -> tuple[list[dict[str, Any]], list[str]]:
    source_messages = collect_topic_messages(
        source_bag_dir,
        source_storage_id,
        {pair.source_topic: Image for pair in image_pairs},
    )
    archive_messages = collect_topic_messages(
        archive_bag_dir,
        archive_storage_id,
        {pair.archive_topic: CompressedImage for pair in image_pairs},
    )

    results: list[dict[str, Any]] = []
    errors: list[str] = []
    for pair in image_pairs:
        src = source_messages[pair.source_topic]
        arc = archive_messages[pair.archive_topic]
        if len(src) != len(arc):
            errors.append(
                f"image topic count mismatch for {pair.source_topic} -> {pair.archive_topic}: "
                f"{len(src)} vs {len(arc)}"
            )
            continue

        mismatch_index: int | None = None
        mismatch_source_ns: int | None = None
        mismatch_archive_ns: int | None = None
        for index, (src_msg, arc_msg) in enumerate(zip(src, arc)):
            src_ns = header_stamp_ns(src_msg)
            arc_ns = header_stamp_ns(arc_msg)
            if src_ns != arc_ns:
                mismatch_index = index
                mismatch_source_ns = src_ns
                mismatch_archive_ns = arc_ns
                errors.append(
                    f"image header stamp mismatch for {pair.source_topic} -> {pair.archive_topic} "
                    f"at index {index}: {src_ns} vs {arc_ns}"
                )
                break

        results.append(
            {
                "source_topic": pair.source_topic,
                "archive_topic": pair.archive_topic,
                "modality": pair.modality,
                "message_count": len(src),
                "status": "ok" if mismatch_index is None else "mismatch",
                "first_mismatch_index": mismatch_index,
                "first_source_stamp_ns": mismatch_source_ns,
                "first_archive_stamp_ns": mismatch_archive_ns,
            }
        )
    return results, errors


def verify_archive_structure(
    source_bag_dir: Path,
    source_storage_id: str,
    archive_bag_dir: Path,
    archive_storage_id: str,
    passthrough_topics: list[str],
    image_pairs: list[ArchiveImageTopicPair],
) -> dict[str, Any]:
    source_counts = topic_count_map(source_bag_dir)
    archive_counts = topic_count_map(archive_bag_dir)
    expected_archive_topics = sorted(set(passthrough_topics).union(pair.archive_topic for pair in image_pairs))
    actual_archive_topics = sorted(archive_counts)

    errors: list[str] = []
    missing_topics = sorted(set(expected_archive_topics) - set(actual_archive_topics))
    unexpected_topics = sorted(set(actual_archive_topics) - set(expected_archive_topics))
    if missing_topics:
        errors.append(f"archive is missing expected topics: {missing_topics}")
    if unexpected_topics:
        errors.append(f"archive has unexpected topics: {unexpected_topics}")

    passthrough_checks: list[dict[str, Any]] = []
    for topic in sorted(passthrough_topics):
        source_count = int(source_counts.get(topic, 0))
        archive_count = int(archive_counts.get(topic, 0))
        status = "ok" if source_count == archive_count else "mismatch"
        if status != "ok":
            errors.append(f"passthrough topic count mismatch for {topic}: {source_count} vs {archive_count}")
        passthrough_checks.append(
            {
                "topic": topic,
                "source_count": source_count,
                "archive_count": archive_count,
                "status": status,
            }
        )

    image_count_checks: list[dict[str, Any]] = []
    for pair in image_pairs:
        source_count = int(source_counts.get(pair.source_topic, 0))
        archive_count = int(archive_counts.get(pair.archive_topic, 0))
        status = "ok" if source_count == archive_count else "mismatch"
        if status != "ok":
            errors.append(
                f"image topic count mismatch for {pair.source_topic} -> {pair.archive_topic}: "
                f"{source_count} vs {archive_count}"
            )
        image_count_checks.append(
            {
                "source_topic": pair.source_topic,
                "archive_topic": pair.archive_topic,
                "modality": pair.modality,
                "source_count": source_count,
                "archive_count": archive_count,
                "status": status,
            }
        )

    image_header_checks, header_errors = compare_image_header_stamps(
        source_bag_dir,
        source_storage_id,
        archive_bag_dir,
        archive_storage_id,
        image_pairs,
    )
    errors.extend(header_errors)

    return {
        "mode": "lightweight_v1",
        "status": "ok" if not errors else "mismatch",
        "source_message_count": int(read_bag_metadata(source_bag_dir)["rosbag2_bagfile_information"].get("message_count", 0)),
        "archive_message_count": int(read_bag_metadata(archive_bag_dir)["rosbag2_bagfile_information"].get("message_count", 0)),
        "expected_archive_topics": expected_archive_topics,
        "actual_archive_topics": actual_archive_topics,
        "missing_archive_topics": missing_topics,
        "unexpected_archive_topics": unexpected_topics,
        "passthrough_topic_checks": passthrough_checks,
        "image_topic_count_checks": image_count_checks,
        "image_header_stamp_checks": image_header_checks,
        "errors": errors,
    }


def raw_image_to_array(msg: Image) -> np.ndarray:
    if msg.encoding == "rgb8":
        row_width = int(msg.width) * 3
        return np.frombuffer(msg.data, dtype=np.uint8).reshape(int(msg.height), int(msg.step))[:, :row_width].reshape(
            int(msg.height), int(msg.width), 3
        )
    if msg.encoding == "bgr8":
        row_width = int(msg.width) * 3
        return np.frombuffer(msg.data, dtype=np.uint8).reshape(int(msg.height), int(msg.step))[:, :row_width].reshape(
            int(msg.height), int(msg.width), 3
        )
    if msg.encoding == "16UC1":
        dtype = np.dtype(">u2") if bool(msg.is_bigendian) else np.dtype("<u2")
        row_width = int(msg.width)
        return np.frombuffer(msg.data, dtype=dtype).reshape(int(msg.height), int(msg.step) // 2)[:, :row_width]
    raise RuntimeError(f"Unsupported raw archive verification encoding: {msg.encoding}")


def decode_archive_image_to_array(msg: CompressedImage, modality: str) -> np.ndarray:
    encoded = np.frombuffer(msg.data, dtype=np.uint8)
    if modality == "depth":
        if "compressedDepth" not in msg.format or "png" not in msg.format:
            raise RuntimeError(f"Unsupported archive depth format: {msg.format}")
        if len(encoded) < 12:
            raise RuntimeError("compressedDepth payload shorter than expected ConfigHeader.")
        image = cv2.imdecode(encoded[12:], cv2.IMREAD_UNCHANGED)
    else:
        image = cv2.imdecode(encoded, cv2.IMREAD_UNCHANGED)
    if image is None:
        raise RuntimeError(f"Failed to decode archive image payload for format: {msg.format}")
    if modality != "depth":
        original_encoding = msg.format.split(";", 1)[0].strip().lower()
        if original_encoding == "rgb8":
            image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    return image


def verify_archive_payload_roundtrip(
    source_bag_dir: Path,
    source_storage_id: str,
    archive_bag_dir: Path,
    archive_storage_id: str,
    image_pairs: list[ArchiveImageTopicPair],
    *,
    source_trim_start_ns: int | None = None,
    source_trim_end_ns: int | None = None,
) -> dict[str, Any]:
    source_messages = collect_topic_message_records(
        source_bag_dir,
        source_storage_id,
        {pair.source_topic: Image for pair in image_pairs},
        trim_start_ns=source_trim_start_ns,
        trim_end_ns=source_trim_end_ns,
    )
    archive_messages = collect_topic_message_records(
        archive_bag_dir,
        archive_storage_id,
        {pair.archive_topic: CompressedImage for pair in image_pairs},
    )

    results: list[dict[str, Any]] = []
    errors: list[str] = []
    total_frames = 0

    for pair in image_pairs:
        src_records = source_messages[pair.source_topic]
        arc_records = archive_messages[pair.archive_topic]
        src = [record["message"] for record in src_records]
        arc = [record["message"] for record in arc_records]
        if len(src) != len(arc):
            errors.append(
                f"payload verification count mismatch for {pair.source_topic} -> {pair.archive_topic}: "
                f"{len(src)} vs {len(arc)}"
            )
            continue

        mismatch: dict[str, Any] | None = None
        for index, (src_msg, arc_msg) in enumerate(zip(src, arc)):
            src_ns = header_stamp_ns(src_msg)
            arc_ns = header_stamp_ns(arc_msg)
            if src_ns != arc_ns:
                mismatch = {
                    "index": index,
                    "reason": "header_stamp_mismatch",
                    "source_stamp_ns": src_ns,
                    "archive_stamp_ns": arc_ns,
                }
                errors.append(
                    f"payload verification header mismatch for {pair.source_topic} -> {pair.archive_topic} "
                    f"at frame {index}: {src_ns} vs {arc_ns}"
                )
                break

            raw_array = raw_image_to_array(src_msg)
            decoded_array = decode_archive_image_to_array(arc_msg, pair.modality)
            if raw_array.shape != decoded_array.shape or raw_array.dtype != decoded_array.dtype:
                mismatch = {
                    "index": index,
                    "reason": "shape_or_dtype_mismatch",
                    "raw_shape": list(raw_array.shape),
                    "raw_dtype": str(raw_array.dtype),
                    "decoded_shape": list(decoded_array.shape),
                    "decoded_dtype": str(decoded_array.dtype),
                }
                errors.append(
                    f"payload verification shape/dtype mismatch for {pair.source_topic} -> {pair.archive_topic} "
                    f"at frame {index}: raw {raw_array.shape}/{raw_array.dtype} vs "
                    f"decoded {decoded_array.shape}/{decoded_array.dtype}"
                )
                break
            if not np.array_equal(raw_array, decoded_array):
                diff_count = int(np.count_nonzero(raw_array != decoded_array))
                mismatch = {
                    "index": index,
                    "reason": "pixel_mismatch",
                    "diff_elements": diff_count,
                }
                errors.append(
                    f"payload verification pixel mismatch for {pair.source_topic} -> {pair.archive_topic} "
                    f"at frame {index}: {diff_count} differing elements"
                )
                break

            total_frames += 1

        results.append(
            {
                "source_topic": pair.source_topic,
                "archive_topic": pair.archive_topic,
                "modality": pair.modality,
                "frame_count": len(src),
                "status": "ok" if mismatch is None else "mismatch",
                "first_mismatch": mismatch,
            }
        )

    return {
        "mode": "full_payload_v1",
        "status": "ok" if not errors else "mismatch",
        "total_verified_frames": total_frames,
        "image_topic_checks": results,
        "errors": errors,
    }
