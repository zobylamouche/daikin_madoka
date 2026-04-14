"""Custom BLE feature classes for Daikin VAM-FC9 ventilation/recuperation units.

These classes extend pymadoka's Feature/FeatureStatus pattern to support
ventilation-specific BLE commands (0x0031/0x4031) without modifying the library.
"""

from enum import Enum
from typing import Dict

from pymadoka.feature import Feature, FeatureStatus
from pymadoka.connection import Connection


class VentilationModeEnum(Enum):
    """Ventilation operating mode."""
    AUTO = 0
    ERV = 1
    BYPASS = 2

    def __str__(self):
        return self.name


class VentilationRateEnum(Enum):
    """Ventilation fan rate/speed."""
    AUTO = 0
    LOW = 1
    HIGH = 5

    def __str__(self):
        return self.name


class VentilationStatus(FeatureStatus):
    """Status class for ventilation mode and rate.

    Attributes:
        ventilation_mode (VentilationModeEnum): Current ventilation mode (AUTO/ERV/BYPASS)
        ventilation_rate (VentilationRateEnum): Current ventilation rate (AUTO/LOW/HIGH)
    """

    MODE_IDX = 0x20
    RATE_IDX = 0x21

    def __init__(self, ventilation_mode: VentilationModeEnum, ventilation_rate: VentilationRateEnum):
        self.ventilation_mode = ventilation_mode
        self.ventilation_rate = ventilation_rate

    def set_values(self, values: Dict[int, bytearray]):
        """Parse BLE response into ventilation mode and rate."""
        if self.MODE_IDX in values:
            self.ventilation_mode = VentilationModeEnum(
                int.from_bytes(values[self.MODE_IDX], "big")
            )
        if self.RATE_IDX in values:
            raw_rate = int.from_bytes(values[self.RATE_IDX], "big")
            # Map intermediate values to closest known rate
            if raw_rate >= 3:
                self.ventilation_rate = VentilationRateEnum.HIGH
            elif raw_rate >= 1:
                self.ventilation_rate = VentilationRateEnum.LOW
            else:
                self.ventilation_rate = VentilationRateEnum.AUTO

    def get_values(self) -> Dict[int, bytearray]:
        """Serialize ventilation mode and rate for BLE command."""
        values = {}
        values[self.MODE_IDX] = self.ventilation_mode.value.to_bytes(1, "big")
        values[self.RATE_IDX] = self.ventilation_rate.value.to_bytes(1, "big")
        return values


class Ventilation(Feature):
    """Feature class for querying and updating ventilation state.

    BLE Commands:
        Query: 0x0031 (decimal 49)
        Update: 0x4031 (decimal 16433)
    """

    def __init__(self, connection: Connection):
        """See base class."""
        self.status = None
        super().__init__(connection)

    def query_cmd_id(self) -> int:
        """See base class."""
        return 49  # 0x0031

    def update_cmd_id(self) -> int:
        """See base class."""
        return 16433  # 0x4031

    def new_status(self) -> FeatureStatus:
        """See base class."""
        return VentilationStatus(VentilationModeEnum.AUTO, VentilationRateEnum.AUTO)
