import struct


class EcoFlowHeader:
    """
    UNIVERSAL EcoFlow header parser.
    Supports ALL EcoFlow devices:
    - Delta 2 / Max / Pro
    - River 2 series
    - Smart Home Panel / Smart Generator
    - Delta 3 / Delta 3 Plus
    - Future EcoFlow devices

    Automatically detects:
    - header format (old/new)
    - cmd_func
    - cmd_id
    - payload length
    - payload bytes (pdata)
    """

    def __init__(self, raw: bytes):
        self.raw = raw
        self.valid = False

        # Parsed fields
        self.cmd_func = None
        self.cmd_id = None
        self.data_len = None
        self.seq = None
        self.pdata = b""

        # Try both known header formats
        if self._parse_new_format():
            self.valid = True
        elif self._parse_old_format():
            self.valid = True

    # ------------------------------------------------------------------
    # NEW FORMAT (Delta 3 Plus, SHP2, PowerStream 2)
    # ------------------------------------------------------------------
    def _parse_new_format(self):
        """
        New EcoFlow header format (Delta 3 Plus):
        Offset | Size | Field
        -------+------+---------------------
        0      | 1    | src
        1      | 1    | dest
        2      | 1    | d_src
        3      | 1    | d_dest
        4      | 1    | enc_type
        5      | 1    | check_type
        6      | 1    | cmd_func
        7      | 1    | cmd_id
        8      | 2    | data_len (LE)
        10     | 1    | need_ack
        11     | 1    | is_ack
        12     | 2    | seq (LE)
        14     | ...  | pdata
        """

        if len(self.raw) < 16:
            return False

        try:
            (
                _src,
                _dest,
                _dsrc,
                _ddest,
                _enc,
                _chk,
                cmd_func,
                cmd_id,
                data_len,
                _need_ack,
                _is_ack,
                seq,
            ) = struct.unpack("<BBBBBB B B H B B H", self.raw[:14])

            # Validate cmd_func range
            if cmd_func not in (32, 254):
                return False

            self.cmd_func = cmd_func
            self.cmd_id = cmd_id
            self.data_len = data_len
            self.seq = seq

            start = 14
            end = 14 + data_len

            if end > len(self.raw):
                return False

            self.pdata = self.raw[start:end]
            return True

        except Exception:
            return False

    # ------------------------------------------------------------------
    # OLD FORMAT (Delta 2, Delta Pro, River 2, SHP1)
    # ------------------------------------------------------------------
    def _parse_old_format(self):
        """
        Old EcoFlow header format:
        Offset | Size | Field
        -------+------+---------------------
        0      | 1    | cmd_func
        1      | 1    | cmd_id
        2      | 2    | data_len (LE)
        4      | 2    | seq (LE)
        6      | ...  | pdata
        """

        if len(self.raw) < 8:
            return False

        try:
            cmd_func, cmd_id, data_len, seq = struct.unpack("<B B H H", self.raw[:6])

            if cmd_func not in (32, 254):
                return False

            self.cmd_func = cmd_func
            self.cmd_id = cmd_id
            self.data_len = data_len
            self.seq = seq

            start = 6
            end = 6 + data_len

            if end > len(self.raw):
                return False

            self.pdata = self.raw[start:end]
            return True

        except Exception:
            return False

    # ------------------------------------------------------------------
    def __repr__(self):
        return (
            f"<EcoFlowHeader func={self.cmd_func} id={self.cmd_id} "
            f"len={self.data_len} seq={self.seq} valid={self.valid}>"
        )
