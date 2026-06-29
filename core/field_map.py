import re
from homeassistant.helpers.entity import EntityCategory


class FieldMap:
    """
    PROTO-first FieldMap:
    - automātiski ģenerē cilvēkam draudzīgus nosaukumus
    - automātiski piešķir vienības
    - automātiski piešķir ikonas
    - automātiski piešķir device_class
    - automātiski piešķir state_class
    - automātiski piešķir entity_category
    - automātiski piešķir min/max/step
    - automātiski piešķir select opcijas
    - atbalsta manuālos override (NAME_MAP, UNIT_MAP, ICON_MAP, OPTIONS_MAP, MIN/MAX/STEP)
    - atbalsta nested laukus (cfg_energy_backup.energy_backup_en)
    """

    # ------------------------------------------------------------------
    # MANUĀLIE OVERRIDES
    # ------------------------------------------------------------------
    NAME_MAP = {}
    UNIT_MAP = {}
    ICON_MAP = {}
    DEVICE_CLASS_MAP = {}
    STATE_CLASS_MAP = {}
    CATEGORY_MAP = {}
    MIN_MAP = {}
    MAX_MAP = {}
    STEP_MAP = {}
    OPTIONS_MAP = {}

    _PREFIX_RE = re.compile(r"^(?:display|runtime|set_cmd|setcmd|set_reply|cms|bms)\.")
    _MSG_PREFIX_RE = re.compile(r"^msg\d+_\d+_\d+\.")

    def _normalize_field(self, field: str) -> str:
        clean = self._PREFIX_RE.sub("", field)
        clean = self._MSG_PREFIX_RE.sub("", clean)
        if "." in clean:
            clean = clean.split(".")[-1]
        return clean

    # ------------------------------------------------------------------
    # AUTO NAME
    # ------------------------------------------------------------------
    def get_name(self, field: str) -> str:
        if field in self.NAME_MAP:
            return self.NAME_MAP[field]

        normalized = self._normalize_field(field)
        if normalized in self.NAME_MAP:
            return self.NAME_MAP[normalized]

        clean = normalized

        # Noņem vienību sufiksus
        clean = re.sub(r"(_mv|_ma|_v|_a|_w)$", "", clean)

        # Cilvēcīgs nosaukums
        name = clean.replace("_", " ").title()

        self.NAME_MAP[field] = name
        return name

    # ------------------------------------------------------------------
    # AUTO UNIT
    # ------------------------------------------------------------------
    def get_unit(self, field: str):
        if field in self.UNIT_MAP:
            return self.UNIT_MAP[field]

        normalized = self._normalize_field(field)
        if normalized in self.UNIT_MAP:
            return self.UNIT_MAP[normalized]

        f = normalized.lower()

        if f.endswith("_mv"):
            return "mV"
        if f.endswith("_v") or "volt" in f:
            return "V"
        if f.endswith("_a") or "amp" in f:
            return "A"
        if f.endswith("_w") or "pow" in f:
            return "W"
        if "freq" in f:
            return "Hz"
        if "temp" in f:
            return "°C"
        if f.endswith("_soc") or f.endswith("_soh"):
            return "%"

        return None

    # ------------------------------------------------------------------
    # AUTO ICON
    # ------------------------------------------------------------------
    def get_icon(self, field: str):
        if field in self.ICON_MAP:
            return self.ICON_MAP[field]

        normalized = self._normalize_field(field)
        if normalized in self.ICON_MAP:
            return self.ICON_MAP[normalized]

        f = normalized.lower()

        if "batt" in f or "battery" in f:
            return "mdi:battery"
        if "temp" in f:
            return "mdi:thermometer"
        if "freq" in f:
            return "mdi:sine-wave"
        if "ac" in f:
            return "mdi:power-plug"
        if "dc" in f:
            return "mdi:current-dc"
        if "soc" in f or "soh" in f:
            return "mdi:battery-high"
        if "volt" in f or f.endswith("_v") or f.endswith("_mv"):
            return "mdi:flash"
        if "watt" in f or f.endswith("_w") or "pow" in f:
            return "mdi:lightning-bolt"

        return "mdi:information-outline"

    # ------------------------------------------------------------------
    # AUTO DEVICE CLASS
    # ------------------------------------------------------------------
    def get_device_class(self, field: str):
        if field in self.DEVICE_CLASS_MAP:
            return self.DEVICE_CLASS_MAP[field]

        normalized = self._normalize_field(field)
        if normalized in self.DEVICE_CLASS_MAP:
            return self.DEVICE_CLASS_MAP[normalized]

        f = normalized.lower()

        if "temp" in f:
            return "temperature"
        if "volt" in f or f.endswith("_v") or f.endswith("_mv"):
            return "voltage"
        if "amp" in f or "current" in f:
            return "current"
        if "pow" in f or f.endswith("_w"):
            return "power"
        if "freq" in f:
            return "frequency"
        if "soc" in f or "soh" in f:
            return "battery"
        if "time" in f:
            return "duration"

        return None

    # ------------------------------------------------------------------
    # AUTO STATE CLASS
    # ------------------------------------------------------------------
    def get_state_class(self, field: str):
        if field in self.STATE_CLASS_MAP:
            return self.STATE_CLASS_MAP[field]

        normalized = self._normalize_field(field)
        if normalized in self.STATE_CLASS_MAP:
            return self.STATE_CLASS_MAP[normalized]

        f = normalized.lower()

        if any(x in f for x in ["pow", "volt", "amp", "temp", "soc", "soh", "freq"]):
            return "measurement"

        if "energy" in f or "wh" in f or "kwh" in f:
            return "total_increasing"

        return None

    # ------------------------------------------------------------------
    # AUTO CATEGORY
    # ------------------------------------------------------------------
    def get_category(self, field: str, is_control: bool):
        if field in self.CATEGORY_MAP:
            return self.CATEGORY_MAP[field]

        normalized = self._normalize_field(field)
        if normalized in self.CATEGORY_MAP:
            return self.CATEGORY_MAP[normalized]

        if is_control:
            return EntityCategory.CONFIG

        f = normalized.lower()

        if any(x in f for x in ["err", "fault", "warn", "state", "flag"]):
            return EntityCategory.DIAGNOSTIC

        return None

    # ------------------------------------------------------------------
    # AUTO RANGE (min/max/step)
    # ------------------------------------------------------------------
    def guess_range(self, field: str):
        f = self._normalize_field(field).lower()

        if "soc" in f:
            return (0, 100, 1)
        if "temp" in f:
            return (-40, 125, 1)
        if "volt" in f:
            return (0, 300, 0.1)
        if "amp" in f:
            return (0, 100, 0.1)
        if "pow" in f:
            return (0, 4000, 1)

        return (0, 100, 1)

    def get_min(self, field):
        return self.MIN_MAP.get(field, self.MIN_MAP.get(self._normalize_field(field)))

    def get_max(self, field):
        return self.MAX_MAP.get(field, self.MAX_MAP.get(self._normalize_field(field)))

    def get_step(self, field):
        return self.STEP_MAP.get(field, self.STEP_MAP.get(self._normalize_field(field)))

    # ------------------------------------------------------------------
    # AUTO ENUM OPTIONS
    # ------------------------------------------------------------------
    AUTO_ENUMS = {
        "pv_chg_type": {
            0: "Auto",
            1: "Car",
            2: "Solar/Car",
            3: "Solar",
            4: "ExtraBattery/Generator",
            5: "DCP",
            6: "DCP2",
            7: "AC Charger",
            8: "MPPT Only",
            9: "DC High Voltage",
        },
        "cfg_led_mode": {
            0: "Off",
            1: "Low",
            2: "Medium",
            3: "High",
            4: "Pulse",
            5: "SOS",
            6: "Rainbow",
            7: "Auto",
        },
    }

    def get_options(self, field):
        if field in self.OPTIONS_MAP:
            return self.OPTIONS_MAP[field]

        normalized = self._normalize_field(field)
        if normalized in self.OPTIONS_MAP:
            return self.OPTIONS_MAP[normalized]

        if field in self.AUTO_ENUMS:
            return list(self.AUTO_ENUMS[field].values())

        if normalized in self.AUTO_ENUMS:
            return list(self.AUTO_ENUMS[normalized].values())

        return None
