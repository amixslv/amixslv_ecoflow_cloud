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
    NAME_MAP = {
        "pow_in_sum_w": "Total Input Power",
        "pow_out_sum_w": "Total Output Power",
        "pow_get_ac_in": "AC In Power",
        "pow_get_pv": "Solar/Car 1 In Power",
        "pow_get_dcp2": "Solar/Car 2 In Power",
        "pow_get_ac_out": "AC Out Power",
        "pow_get_12v": "DC 12V Out Power",
        "pow_get_typec1": "USB-C 1 Power",
        "pow_get_typec2": "USB-C 2 Power",
        "pow_get_qcusb1": "USB-A 1 Power",
        "pow_get_qcusb2": "USB-A 2 Power",
        "pow_get_bms": "Extra Battery Power",
        "bms_batt_soc": "Station Battery Level",
        "cms_batt_soc": "Extra Battery Level",
        "bms_chg_rem_time": "Charge Remaining Time",
        "bms_dsg_rem_time": "Discharge Remaining Time",
        "temp_pcs_ac": "PCS AC Temperature",
        "temp_pcs_dc": "PCS DC Temperature",
        "en_beep": "Beep",
        "xboost_en": "X-Boost",
        "cfg_ac_out_open": "AC Out Enabled",
        "cfg_dc12v_out_open": "DC 12V Out Enabled",
        "plug_in_info_ac_in_chg_pow_max": "AC Charge Power Limit",
        "cms_max_chg_soc": "Max Charge Limit",
        "cms_min_dsg_soc": "Min Discharge Limit",
        "pv_chg_type": "PV Charge Type",
        "screen_off_time": "Screen Off Time",
        "ac_standby_time": "AC Standby Time",
        "dc_standby_time": "DC Standby Time",
        "dev_standby_time": "Unit Standby Time",
        "output_power_off_memory": "Output Power-Off Memory",
    }
    UNIT_MAP = {}
    ICON_MAP = {
        "pow_in_sum_w": "mdi:transmission-tower-import",
        "pow_out_sum_w": "mdi:transmission-tower-export",
        "pow_get_ac_in": "mdi:power-plug",
        "pow_get_ac_out": "mdi:power-plug-outline",
        "pow_get_pv": "mdi:solar-power",
        "pow_get_dcp2": "mdi:solar-power-variant",
        "pow_get_12v": "mdi:car-electric",
        "pow_get_typec1": "mdi:usb-c-port",
        "pow_get_typec2": "mdi:usb-c-port",
        "pow_get_qcusb1": "mdi:usb-port",
        "pow_get_qcusb2": "mdi:usb-port",
        "pow_get_bms": "mdi:battery-sync",
    }
    DEVICE_CLASS_MAP = {
        "bms_chg_rem_time": "duration",
        "bms_dsg_rem_time": "duration",
    }
    STATE_CLASS_MAP = {
        "pow_in_sum_w": "measurement",
        "pow_out_sum_w": "measurement",
        "pow_get_ac_in": "measurement",
        "pow_get_pv": "measurement",
        "pow_get_dcp2": "measurement",
        "pow_get_ac_out": "measurement",
        "pow_get_12v": "measurement",
        "pow_get_typec1": "measurement",
        "pow_get_typec2": "measurement",
        "pow_get_qcusb1": "measurement",
        "pow_get_qcusb2": "measurement",
        "pow_get_bms": "measurement",
    }
    CATEGORY_MAP = {
        "en_beep": EntityCategory.CONFIG,
        "cms_max_chg_soc": EntityCategory.CONFIG,
        "cms_min_dsg_soc": EntityCategory.CONFIG,
        "plug_in_info_ac_in_chg_pow_max": EntityCategory.CONFIG,
        "screen_off_time": EntityCategory.CONFIG,
        "ac_standby_time": EntityCategory.CONFIG,
        "dc_standby_time": EntityCategory.CONFIG,
        "dev_standby_time": EntityCategory.CONFIG,
        "pv_chg_type": EntityCategory.CONFIG,
    }
    MIN_MAP = {
        "cms_max_chg_soc": 0,
        "cms_min_dsg_soc": 0,
        "plug_in_info_ac_in_chg_pow_max": 100,
    }
    MAX_MAP = {
        "cms_max_chg_soc": 100,
        "cms_min_dsg_soc": 100,
        "plug_in_info_ac_in_chg_pow_max": 1500,
    }
    STEP_MAP = {
        "cms_max_chg_soc": 1,
        "cms_min_dsg_soc": 1,
        "plug_in_info_ac_in_chg_pow_max": 10,
    }
    OPTIONS_MAP = {}
    CONTROL_TYPE_MAP = {
        "en_beep": "switch",
        "xboost_en": "switch",
        "cfg_ac_out_open": "switch",
        "cfg_dc12v_out_open": "switch",
        "output_power_off_memory": "switch",
    }
    DEFAULT_ENABLED_SENSOR_FIELDS = {
        "pow_in_sum_w",
        "pow_out_sum_w",
        "pow_get_ac_in",
        "pow_get_pv",
        "pow_get_dcp2",
        "pow_get_ac_out",
        "pow_get_12v",
        "pow_get_typec1",
        "pow_get_typec2",
        "pow_get_qcusb1",
        "pow_get_qcusb2",
        "pow_get_bms",
        "bms_batt_soc",
        "cms_batt_soc",
        "bms_batt_soh",
        "cms_batt_soh",
        "bms_chg_rem_time",
        "bms_dsg_rem_time",
        "temp_pcs_ac",
        "temp_pcs_dc",
        "cycles",
        "soc",
        "remain_time",
        "input_watts",
        "output_watts",
    }
    DEFAULT_ENABLED_CONTROL_FIELDS = {
        "en_beep",
        "xboost_en",
        "cfg_ac_out_open",
        "cfg_dc12v_out_open",
        "cms_max_chg_soc",
        "cms_min_dsg_soc",
        "plug_in_info_ac_in_chg_pow_max",
        "pv_chg_type",
        "cfg_energy_backup",
        "screen_off_time",
        "ac_standby_time",
        "dc_standby_time",
        "dev_standby_time",
        "output_power_off_memory",
    }
    TOKEN_LABELS = {
        "ac": "AC",
        "dc": "DC",
        "bms": "BMS",
        "cms": "CMS",
        "soc": "SOC",
        "soh": "SOH",
        "pv": "PV",
        "usb": "USB",
        "wifi": "Wi-Fi",
        "cfg": "Config",
        "eps": "EPS",
        "inv": "Inverter",
        "chg": "Charge",
    }

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
        clean = re.sub(r"^cfg_", "", clean)

        # Noņem vienību sufiksus
        clean = re.sub(r"(_mv|_ma|_v|_a|_w)$", "", clean)

        # Cilvēcīgs nosaukums ar saīsinājumu normalizāciju
        words = clean.split("_")
        pretty_words = []
        for word in words:
            if not word:
                continue
            pretty_words.append(self.TOKEN_LABELS.get(word.lower(), word.capitalize()))
        name = " ".join(pretty_words)

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
        if f.endswith("_w") or (("pow" in f or "power" in f) and not f.endswith(("_off","_on","_flag","_en","_enable"))):
            return "W"
        if "freq" in f:
            return "Hz"
        if f.endswith("_kwh"):
            return "kWh"
        if "energy" in f or f.endswith("_wh"):
            return "Wh"
        if f.endswith("_mah"):
            return "mAh"
        if f.endswith("_ah"):
            return "Ah"
        if f.endswith("_ma"):
            return "mA"
        if f.endswith("_kw"):
            return "kW"
        if f.endswith("_ms"):
            return "ms"
        if f.endswith("_sec") or f.endswith("_s"):
            return "s"
        if f.endswith("_min"):
            return "min"
        if f.endswith("_hour") or f.endswith("_hr") or f.endswith("_h"):
            return "h"
        if "temp" in f:
            return "°C"
        if f.endswith("_soc") or f.endswith("_soh") or f.endswith("_pct") or "percent" in f:
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
        if f.endswith("_w") or (("pow" in f or "power" in f) and not f.endswith(("_off","_on","_flag","_en","_enable"))):
            return "power"
        if "freq" in f:
            return "frequency"
        if f.endswith("_soc") and not any(x in f for x in ("min_","mini_","max_","backup","always_on","reserve","alarm","protect")):
            return "battery"
        if f in ("soc","soh","batt_soh","bms_batt_soh"):
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
            if "cfg_" in normalized:
                return EntityCategory.CONFIG
            _SKW = ("timeout","standby_time","off_time","utc_time","utc_zone","timezone","lcd_","_light","backup_soc","min_dsg","max_chg","screen_off")
            if any(kw in normalized for kw in _SKW):
                return EntityCategory.CONFIG
            return None

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

    def get_control_type(self, field: str):
        normalized = self._normalize_field(field)
        return self.CONTROL_TYPE_MAP.get(field, self.CONTROL_TYPE_MAP.get(normalized))

    def is_default_enabled(self, field: str, is_control: bool, source: str | None = None):
        normalized = self._normalize_field(field)

        if is_control:
            return normalized in self.DEFAULT_ENABLED_CONTROL_FIELDS

        if source in ("display", "runtime"):
            return normalized in self.DEFAULT_ENABLED_SENSOR_FIELDS

        if source in ("bms", "cms"):
            return normalized in self.DEFAULT_ENABLED_SENSOR_FIELDS

        return normalized in self.DEFAULT_ENABLED_SENSOR_FIELDS

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
