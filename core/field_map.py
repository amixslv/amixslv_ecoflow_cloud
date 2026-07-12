import re
from homeassistant.helpers.entity import EntityCategory


class FieldMap:
    """
    PROTO-first FieldMap:
    - automÄtiski Ä£enerÄ“ cilvÄ“kam draudzÄ«gus nosaukumus
    - automÄtiski pieÅÄ·ir vienÄ«bas
    - automÄtiski pieÅÄ·ir ikonas
    - automÄtiski pieÅÄ·ir device_class
    - automÄtiski pieÅÄ·ir state_class
    - automÄtiski pieÅÄ·ir entity_category
    - automÄtiski pieÅÄ·ir min/max/step
    - automÄtiski pieÅÄ·ir select opcijas
    - atbalsta manuÄlos override (NAME_MAP, UNIT_MAP, ICON_MAP, OPTIONS_MAP, MIN/MAX/STEP)
    - atbalsta nested laukus (cfg_energy_backup.energy_backup_en)
    """

    # ------------------------------------------------------------------
    # MANUÄ€LIE OVERRIDES
    # ------------------------------------------------------------------
    NAME_MAP = {
        "pow_in_sum_w": "Total Input Power",
        "pow_out_sum_w": "Total Output Power",
        "pow_get_ac_in": "AC Input Power",
        "pow_get_ac_out": "AC Output Power",
        "pow_get_ac": "AC Power",
        "pow_get_pv": "PV Input 1 Power",
        "pow_get_pv2": "PV Input 2 Power",
        "pow_get_pv_sum": "PV Total Input Power",
        "pow_get_sys_grid": "Grid Input Power",
        "pow_get_sys_load_from_grid": "Load From Grid Power",
        "pow_get_bms": "Battery Power",
        "pow_get_dcp": "DCP Power",
        "pow_get_12v": "12V Output Power",
        "cms_batt_soc": "CMS Battery SOC",
        "bms_batt_soc": "BMS Battery SOC",
        "soc": "Battery SOC",
        "cms_chg_rem_time": "CMS Charge Remaining Time",
        "cms_dsg_rem_time": "CMS Discharge Remaining Time",
        "bms_chg_rem_time": "BMS Charge Remaining Time",
        "bms_dsg_rem_time": "BMS Discharge Remaining Time",
        "remain_time": "Remaining Time",
        "bms_batt_vol": "BMS Battery Voltage",
        "cms_batt_vol": "CMS Battery Voltage",
        "bms_batt_amp": "BMS Battery Current",
        "cms_batt_amp": "CMS Battery Current",
        "temp_pcs_dc": "PCS DC Temperature",
        "temp_pcs_ac": "PCS AC Temperature",
        "temp_pv": "PV Temperature",
        "bms_min_cell_temp": "BMS Min Cell Temperature",
        "bms_max_cell_temp": "BMS Max Cell Temperature",
        "bms_min_mos_temp": "BMS Min MOS Temperature",
        "bms_max_mos_temp": "BMS Max MOS Temperature",
        "flow_info_ac_in": "AC Input Flow State",
        "flow_info_ac_out": "AC Output Flow State",
        "flow_info_pv": "PV1 Flow State",
        "flow_info_pv2": "PV2 Flow State",
        "flow_info_bms_chg": "BMS Charge Flow State",
        "flow_info_bms_dsg": "BMS Discharge Flow State",
        "flow_info_12v": "12V Flow State",
        "flow_info_dcp_in": "DCP Input Flow State",
        "flow_info_dcp_out": "DCP Output Flow State",
        "ac_out_freq": "AC Output Frequency",
        "plug_in_info_ac_in_vol": "AC Input Voltage",
        "plug_in_info_ac_out_vol": "AC Output Voltage",
        "plug_in_info_ac_in_amp": "AC Input Current",
        "plug_in_info_ac_out_amp": "AC Output Current",
        "plug_in_info_ac_in_chg_pow_max": "AC Charge Power Limit",
        "plug_in_info_pv_vol": "PV Voltage",
        "plug_in_info_pv_amp": "PV Current",
        "plug_in_info_pv_type": "PV Input Type",
        "plug_in_info_dcp_in_flag": "DCP Input Flag",
        "plug_in_info_dcp_type": "DCP Type",
        "plug_in_info_dcp_detail": "DCP Detail",
        "plug_in_info_dcp_dsg_chg_type": "DCP Charge/Discharge Type",
        "plug_in_info_dcp_sn": "DCP Serial Number",
        "en_beep": "Beep Enabled",
        "xboost_en": "X-Boost Enabled",
        "cms_max_chg_soc": "Max Charge SOC",
        "cms_min_dsg_soc": "Min Discharge SOC",
        "output_power_off_memory": "Output Power-Off Memory",
        "dev_standby_time": "Device Standby Time",
        "screen_off_time": "Screen Off Time",
        "ac_standby_time": "AC Standby Time",
        "utc_timezone_id": "Time Zone",
        "bms_err_code": "BMS Error Code",
        "pd_err_code": "PD Error Code",
        "all_err_code": "All Error Code",
        "bms_fault_state": "BMS Fault State",
        "bms_protect_state1": "BMS Protect State 1",
        "bms_protect_state2": "BMS Protect State 2",
        "bms_alarm_state1": "BMS Alarm State 1",
        "bms_alarm_state2": "BMS Alarm State 2",
        "water_in_flag": "Water In Flag",
    }
    UNIT_MAP = {}
    ICON_MAP = {}
    DEVICE_CLASS_MAP = {}
    STATE_CLASS_MAP = {}
    CATEGORY_MAP = {}
    MIN_MAP = {}
    MAX_MAP = {}
    STEP_MAP = {}
    OPTIONS_MAP = {}
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

    _TRANSLATIONS_DIR = pathlib.Path(__file__).parent.parent / "translations"
    _translation_cache: dict[str, dict] = {}

    @classmethod
    def _load_translations(cls, lang: str) -> dict:
        if lang in cls._translation_cache:
            return cls._translation_cache[lang]
        for candidate in (lang, lang.split("-")[0], "en"):
            p = cls._TRANSLATIONS_DIR / f"{candidate}.json"
            if p.exists():
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    entity_section = data.get("entity", {})
                    flat: dict[str, str] = {}
                    for _platform, fields in entity_section.items():
                        for key, val in fields.items():
                            name = val.get("name") if isinstance(val, dict) else None
                            if name:
                                flat[key] = name
                    cls._translation_cache[lang] = flat
                    return flat
                except Exception:
                    pass
        cls._translation_cache[lang] = {}
        return {}

    def get_localized_name(self, field: str, lang: str) -> str | None:
        translations = self._load_translations(lang)
        key = self._normalize_field(field).lower()
        return translations.get(key) or translations.get(field)

    _PREFIX_RE = re.compile(r"^(?:display|runtime|set_cmd|setcmd|set_reply|cms|bms)\.")
    _MSG_PREFIX_RE = re.compile(r"^msg\d+_\d+_\d+\.")

    def _normalize_field(self, field: str) -> str:
        clean = self._PREFIX_RE.sub("", field)
        clean = self._MSG_PREFIX_RE.sub("", clean)
        if "." in clean:
            clean = clean.split(".")[-1]
        return clean

    def normalize_field(self, field: str) -> str:
        return self._normalize_field(field)

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

        # NoÅ†em vienÄ«bu sufiksus
        clean = re.sub(r"(_mv|_ma|_v|_a|_w)$", "", clean)

        # CilvÄ“cÄ«gs nosaukums ar saÄ«sinÄjumu normalizÄciju
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
        if "time" in f:
            return "min"
        if "temp" in f:
            return "Ā°C"
        if f in ("soc", "soh", "batt_soc", "batt_soh", "bms_soc", "bms_soh"):
            return "%"
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
        if f == "cms_batt_soc":
            return "battery"
        # Keep battery class explicit to avoid generic *_soc fields
        # hijacking HA's primary battery badge for the main station device.
        if f in ("bms_batt_soc", "batt_soh", "bms_batt_soh"):
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
        normalized = self._normalize_field(field)
        f = normalized.lower()

        if is_control:
            if normalized.startswith("cfg_"):
                return EntityCategory.CONFIG
            if any(x in f for x in ("timeout", "standby", "screen_off", "utc_", "timezone", "limit", "mode", "type", "beep", "xboost", "memory")):
                return EntityCategory.CONFIG
            return None

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
        normalized = self._normalize_field(field).lower()

        if normalized == "cfg_power_off":
            return "switch"
        if any(x in normalized for x in ("power_off", "reconnect", "reset", "clear", "restart", "shutdown")):
            return "button"
        if normalized.endswith(("_en", "_enable", "_enabled", "_flag", "_switch", "_open", "_close")):
            return "switch"
        if any(x in normalized for x in ("beep", "xboost", "memory")):
            return "switch"
        if self.get_options(field):
            return "select"
        if any(x in normalized for x in ("time", "timeout", "soc", "limit", "amp", "volt", "watt", "power")):
            return "number"
        return None

    def is_default_enabled(self, field: str, is_control: bool, source: str | None = None):
        if is_control:
            return True

        normalized = self._normalize_field(field).lower()
        energy_focus = {
            "pow_get_pv",
            "pow_get_pv2",
            "pow_get_pv_sum",
            "pow_get_sys_grid",
            "pow_get_sys_load_from_grid",
            "pow_get_ac_in",
        }
        return normalized in energy_focus

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

