"""One isolated Windows ICMP probe, without starting PowerShell.

Executed with ``python -I icmp_probe.py`` by discovery.py. Isolation lets the
parent terminate an unexpectedly stalled native call or interpreter startup.
The JSON status contract is independent of Windows' display language.

API reference: https://learn.microsoft.com/en-us/windows/win32/api/icmpapi/nf-icmpapi-icmpsendecho
"""

import ctypes
from ipaddress import IPv4Address
import json
import struct
import sys


def probe(address, timeout_ms):
    address = IPv4Address(address)
    if type(timeout_ms) is not int or not 1 <= timeout_ms <= 2**31 - 1:
        raise ValueError("TimeoutMs must be a positive 32-bit integer.")
    if sys.platform != "win32":
        raise OSError("The native ICMP probe requires Windows.")

    api = ctypes.WinDLL("iphlpapi.dll", use_last_error=True)
    api.IcmpCreateFile.argtypes = []
    api.IcmpCreateFile.restype = ctypes.c_void_p
    api.IcmpCloseHandle.argtypes = [ctypes.c_void_p]
    api.IcmpCloseHandle.restype = ctypes.c_int
    api.IcmpSendEcho.argtypes = [
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint16,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
    ]
    api.IcmpSendEcho.restype = ctypes.c_uint32
    handle = api.IcmpCreateFile()
    if handle is None or handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())

    try:
        payload = ctypes.create_string_buffer(b"UGNAY discovery")
        # More than ICMP_ECHO_REPLY + payload + 8 error bytes on both 32/64-bit
        # Windows. Only the fixed header is read, never native pointer fields.
        reply = ctypes.create_string_buffer(4096)
        replies = api.IcmpSendEcho(
            handle, int.from_bytes(address.packed, "little"), payload,
            len(payload.raw) - 1, None, reply, ctypes.sizeof(reply), timeout_ms,
        )
        if not replies:
            status = ctypes.get_last_error()
            if not status:
                raise OSError("IcmpSendEcho returned no reply and no Windows error status.")
            return {"Status": status, "Address": None}
        # Address, Status, RoundTripTime precede the architecture-dependent
        # fields in both ICMP_ECHO_REPLY and ICMP_ECHO_REPLY32.
        return {
            "Status": struct.unpack_from("<I", reply.raw, 4)[0],
            "Address": str(IPv4Address(reply.raw[:4])),
        }
    finally:
        api.IcmpCloseHandle(handle)


def main():
    try:
        request = json.load(sys.stdin)
        result = probe(request["IPAddress"], request["TimeoutMs"])
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Native ICMP probe failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
