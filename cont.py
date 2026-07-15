DOMAIN = "ecoflow"
LEGACY_DOMAIN = "amixslv_ecoflow_cloud"

PLATFORMS = [
    "sensor",
    "switch",
    "number",
    "select",
    "binary_sensor",
]

API_HOST = "api.ecoflow.com"
API_LOGIN_PATH = "/auth/login"
API_CERTIFICATION_PATH = "/iot-auth/app/certification"
API_DEVICE_LIST_PATHS = (
    "/iot-open/user/device/list",
    "/user/device/list",
)

MQTT_TOPIC_DEVICE_PROPERTY = "/app/device/property/{sn}"
MQTT_TOPIC_DEVICE_PROP_LEGACY = "/app/device/prop/{sn}"
MQTT_TOPIC_USER_DEVICE_PROPERTY = "/app/{user_id}/device/property/{sn}"
MQTT_TOPIC_USER_THING_PROPERTY_GET = "/app/{user_id}/{sn}/thing/property/get"
MQTT_TOPIC_USER_THING_PROPERTY_GET_REPLY = "/app/{user_id}/{sn}/thing/property/get_reply"
MQTT_TOPIC_USER_THING_PROPERTY_SET = "/app/{user_id}/{sn}/thing/property/set"
MQTT_TOPIC_USER_THING_PROPERTY_SET_REPLY = "/app/{user_id}/{sn}/thing/property/set_reply"

PROTO_SET_CMD_FUNC = 254
PROTO_SET_CMD_ID = 17
PROTO_HEADER_SRC_CLOUD = 32
PROTO_HEADER_DEST_MAIN = 5
PROTO_HEADER_D_SRC = 0
PROTO_HEADER_D_DEST = 0
PROTO_HEADER_IS_RW_CMD = 1
PROTO_HEADER_NEED_ACK = 1

PROTO_MESSAGE_SUFFIXES = (
    "DisplayPropertyUpload",
    "RuntimePropertyUpload",
    "CMSHeartBeatReport",
    "BMSHeartBeatReport",
    "SetCommand",
    "SetReply",
)

PROTO_MESSAGE_SOURCE_BY_SUFFIX = {
    "DisplayPropertyUpload": "display",
    "RuntimePropertyUpload": "runtime",
    "CMSHeartBeatReport": "cms",
    "BMSHeartBeatReport": "bms",
    "SetCommand": "set_cmd",
    "SetReply": "set_reply",
}
