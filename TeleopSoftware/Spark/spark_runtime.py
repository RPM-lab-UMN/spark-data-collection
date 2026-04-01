from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import pickle
import time
from typing import Any

import numpy as np
import serial

JOINT_COUNT = 7
ENCODER_MODULUS = 2**14


@dataclass(frozen=True)
class SparkRuntimeConfig:
    device_path: str
    buffered_topic: bool = False
    baudrate: int = 921600
    timeout_s: float = 1.0
    boot_settle_s: float = 1.5
    identify_max_packets: int = 20
    runtime_max_packets: int = 5
    reconnect_delay_s: float = 1.0
    offsets_dir: Path | None = None

    def resolved_offsets_dir(self) -> Path:
        if self.offsets_dir is not None:
            return self.offsets_dir
        return Path(__file__).resolve().parent


@dataclass(frozen=True)
class SparkPacket:
    device_id: str
    raw_values: list[int]
    status: list[bool]
    enable_switch: bool

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "SparkPacket":
        raw_values = payload.get("values")
        if not isinstance(raw_values, list) or len(raw_values) < JOINT_COUNT:
            raise ValueError(f"Spark packet has invalid values payload: {raw_values!r}")

        status = payload.get("status")
        if not isinstance(status, list) or len(status) < JOINT_COUNT:
            status = [True] * JOINT_COUNT

        return cls(
            device_id=str(payload["ID"]).strip().lower(),
            raw_values=[int(value) for value in raw_values[:JOINT_COUNT]],
            status=[bool(value) for value in status[:JOINT_COUNT]],
            enable_switch=bool(payload.get("enable_switch", False)),
        )


@dataclass(frozen=True)
class SparkSample:
    device_id: str
    angles_rad: list[float]
    status: list[bool]
    enable_switch: bool


class SparkDisconnectedError(RuntimeError):
    pass


def load_offsets_pickle(offsets_dir: Path, device_id: str) -> tuple[list[int], list[int]]:
    pickle_path = offsets_dir / f"offsets_{device_id}.pickle"
    with pickle_path.open("rb") as handle:
        payload = pickle.load(handle)

    if isinstance(payload, tuple) and len(payload) >= 2:
        offsets_raw = [int(value) for value in payload[0][:JOINT_COUNT]]
        invert = [int(value) for value in payload[1][:JOINT_COUNT]]
        return offsets_raw, invert

    offsets_raw = [int(value) for value in payload[:JOINT_COUNT]]
    invert = [-1, -1, 1, -1, -1, -1, -1]
    return offsets_raw, invert


class SparkAngleUnwrapper:
    def __init__(self, offsets_raw: list[int], invert: list[int], modulus: int = ENCODER_MODULUS):
        if len(offsets_raw) != JOINT_COUNT:
            raise ValueError(f"offsets_raw must have length {JOINT_COUNT}, got {len(offsets_raw)}")
        if len(invert) != JOINT_COUNT:
            raise ValueError(f"invert must have length {JOINT_COUNT}, got {len(invert)}")
        self._previous_raw_angles = np.asarray(offsets_raw, dtype=np.int64)
        self._invert = np.asarray(invert, dtype=np.float64)
        self._modulus = int(modulus)
        self._calculated_angles = np.zeros(JOINT_COUNT, dtype=np.float64)

    def update(self, raw_values: list[int]) -> list[float]:
        raw = np.asarray(raw_values[:JOINT_COUNT], dtype=np.int64)
        dist = raw - self._previous_raw_angles
        half = self._modulus / 2
        dist = np.where(dist > half, dist - self._modulus, dist)
        dist = np.where(dist < -half, dist + self._modulus, dist)
        self._calculated_angles += self._invert * (dist.astype(np.float64) / float(self._modulus)) * (2.0 * np.pi)
        self._previous_raw_angles = raw
        return self._calculated_angles.tolist()


class SparkSerialTransport:
    def __init__(self, config: SparkRuntimeConfig):
        self._config = config
        self._connection: serial.Serial | None = None

    def connect(self) -> None:
        self.close()
        self._connection = serial.Serial(
            self._config.device_path,
            self._config.baudrate,
            timeout=self._config.timeout_s,
        )
        time.sleep(self._config.boot_settle_s)
        self._connection.reset_input_buffer()
        self._connection.reset_output_buffer()

    def close(self) -> None:
        if self._connection is not None:
            try:
                self._connection.close()
            finally:
                self._connection = None

    def read_packet(self, max_packets: int) -> SparkPacket:
        if self._connection is None:
            raise RuntimeError("Spark serial transport is not connected.")

        for _ in range(max_packets):
            payload = self._connection.read_until(b"\x00")
            if payload.endswith(b"\x00"):
                payload = payload[:-1]
            if not payload:
                continue
            text = payload.decode("utf-8", errors="ignore").strip()
            if not text or not text.startswith("{"):
                continue
            try:
                parsed = json.loads(text)
                return SparkPacket.from_payload(parsed)
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
        raise RuntimeError("no JSON payload received")


class SparkDeviceRunner:
    def __init__(self, config: SparkRuntimeConfig):
        self.config = config
        self._transport = SparkSerialTransport(config)
        self.device_id: str | None = None
        self._unwrapper: SparkAngleUnwrapper | None = None

    def connect_until_identified(self) -> str:
        while True:
            try:
                self._transport.connect()
                packet = self._transport.read_packet(self.config.identify_max_packets)
                self.device_id = packet.device_id
                offsets_raw, invert = load_offsets_pickle(
                    self.config.resolved_offsets_dir(),
                    self.device_id,
                )
                self._unwrapper = SparkAngleUnwrapper(offsets_raw=offsets_raw, invert=invert)
                return self.device_id
            except RuntimeError:
                print(f"Waiting for Spark JSON on {self.config.device_path}")
                time.sleep(self.config.reconnect_delay_s)

    def reconnect(self) -> None:
        time.sleep(self.config.reconnect_delay_s)
        self._transport.connect()

    def read_sample(self) -> SparkSample | None:
        if self._unwrapper is None or self.device_id is None:
            raise RuntimeError("Spark device runner must be identified before reading samples.")
        try:
            packet = self._transport.read_packet(self.config.runtime_max_packets)
        except serial.SerialException as exc:
            raise SparkDisconnectedError(str(exc)) from exc
        except RuntimeError:
            return None

        angles = self._unwrapper.update(packet.raw_values)
        return SparkSample(
            device_id=self.device_id,
            angles_rad=angles,
            status=packet.status,
            enable_switch=packet.enable_switch,
        )

    def close(self) -> None:
        self._transport.close()
