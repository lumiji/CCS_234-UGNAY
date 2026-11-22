"""Read local IPv4 configuration through IP Helper, without PowerShell or CIM.

Run as an isolated helper so discovery can enforce a process deadline. Structure
layouts follow Windows' fixed-width ABI, including its alignment and padding:
https://learn.microsoft.com/en-us/windows/win32/api/iphlpapi/nf-iphlpapi-getadaptersaddresses
https://learn.microsoft.com/en-us/windows/win32/api/netioapi/ns-netioapi-mib_if_row2
https://learn.microsoft.com/en-us/windows/win32/api/netioapi/ns-netioapi-mib_unicastipaddress_row
"""

import ctypes as c
from ipaddress import IPv4Address
import json
import sys


DWORD, WORD, BYTE, ULONG64 = c.c_uint32, c.c_uint16, c.c_uint8, c.c_uint64
AF_INET = 2
ERROR_BUFFER_OVERFLOW, ERROR_NO_DATA, ERROR_NOT_FOUND = 111, 232, 1168


class _Guid(c.Structure):
    _fields_ = [("Data1", DWORD), ("Data2", WORD), ("Data3", WORD), ("Data4", BYTE * 8)]


class _SockaddrIn(c.Structure):
    _fields_ = [("Family", WORD), ("Port", WORD), ("Address", BYTE * 4), ("Zero", BYTE * 8)]


class _SockaddrIn6(c.Structure):
    _fields_ = [("Family", WORD), ("Port", WORD), ("FlowInfo", DWORD),
                ("Address", BYTE * 16), ("ScopeId", DWORD)]


class _SockaddrInet(c.Union):
    _fields_ = [("Ipv4", _SockaddrIn), ("Ipv6", _SockaddrIn6)]


class _SocketAddress(c.Structure):
    _fields_ = [("Address", c.c_void_p), ("Length", c.c_int32)]


class _UnicastAddress(c.Structure):
    pass


# Only the prefix of these variable-length linked records is read. Windows
# writes the complete structures into the separately allocated adapter buffer.
_UnicastAddress._fields_ = [
    ("Alignment", ULONG64), ("Next", c.POINTER(_UnicastAddress)), ("Socket", _SocketAddress),
]


class _AdapterAddresses(c.Structure):
    pass


_AdapterAddresses._fields_ = [
    ("Length", DWORD), ("IfIndex", DWORD), ("Next", c.POINTER(_AdapterAddresses)),
    ("AdapterName", c.c_void_p), ("FirstUnicastAddress", c.POINTER(_UnicastAddress)),
    ("FirstAnycastAddress", c.c_void_p), ("FirstMulticastAddress", c.c_void_p),
    ("FirstDnsServerAddress", c.c_void_p), ("DnsSuffix", c.c_void_p),
    ("Description", c.c_void_p), ("FriendlyName", c.c_wchar_p),
    ("PhysicalAddress", BYTE * 8), ("PhysicalAddressLength", DWORD),
    ("Flags", DWORD), ("Mtu", DWORD), ("IfType", DWORD), ("OperStatus", DWORD),
    ("Ipv6IfIndex", DWORD), ("ZoneIndices", DWORD * 16), ("FirstPrefix", c.c_void_p),
    ("TransmitLinkSpeed", ULONG64), ("ReceiveLinkSpeed", ULONG64),
    ("FirstWinsServerAddress", c.c_void_p), ("FirstGatewayAddress", c.c_void_p),
    ("Ipv4Metric", DWORD),
]


class _InterfaceRow(c.Structure):
    # GetIfEntry2 writes the entire MIB_IF_ROW2, including its trailing counters.
    _fields_ = [
        ("Luid", ULONG64), ("Index", DWORD), ("Guid", _Guid),
        ("Alias", WORD * 257), ("Description", WORD * 257),
        ("PhysicalAddressLength", DWORD), ("PhysicalAddress", BYTE * 32),
        ("PermanentPhysicalAddress", BYTE * 32), ("Mtu", DWORD), ("Type", DWORD),
        ("TunnelType", DWORD), ("MediaType", DWORD), ("PhysicalMediumType", DWORD),
        ("AccessType", DWORD), ("DirectionType", DWORD), ("StatusFlags", BYTE),
        ("OperStatus", DWORD), ("AdminStatus", DWORD), ("MediaConnectState", DWORD),
        ("NetworkGuid", _Guid), ("ConnectionType", DWORD),
    ] + [(name, ULONG64) for name in (
        "TransmitLinkSpeed", "ReceiveLinkSpeed", "InOctets", "InUcastPkts", "InNUcastPkts",
        "InDiscards", "InErrors", "InUnknownProtos", "InUcastOctets", "InMulticastOctets",
        "InBroadcastOctets", "OutOctets", "OutUcastPkts", "OutNUcastPkts", "OutDiscards",
        "OutErrors", "OutUcastOctets", "OutMulticastOctets", "OutBroadcastOctets", "OutQLen",
    )]


class _UnicastRow(c.Structure):
    _fields_ = [
        ("Address", _SockaddrInet), ("Luid", ULONG64), ("Index", DWORD),
        ("PrefixOrigin", DWORD), ("SuffixOrigin", DWORD), ("ValidLifetime", DWORD),
        ("PreferredLifetime", DWORD), ("PrefixLength", BYTE), ("SkipAsSource", BYTE),
        ("DadState", DWORD), ("ScopeId", DWORD), ("CreationTimeStamp", c.c_int64),
    ]


def _check(status, operation):
    if status:
        raise OSError(f"{operation} failed (Windows status {status}).")


def read_ipv4_interfaces():
    """Return the real adapter metadata used by DiscoveryService's selection."""
    if sys.platform != "win32":
        raise OSError("Local network detection requires Windows.")
    api = c.WinDLL("iphlpapi.dll", use_last_error=True)
    api.GetAdaptersAddresses.argtypes = [DWORD, DWORD, c.c_void_p, c.c_void_p, c.POINTER(DWORD)]
    api.GetAdaptersAddresses.restype = DWORD
    api.GetIfEntry2.argtypes = [c.POINTER(_InterfaceRow)]
    api.GetIfEntry2.restype = DWORD
    api.GetUnicastIpAddressEntry.argtypes = [c.POINTER(_UnicastRow)]
    api.GetUnicastIpAddressEntry.restype = DWORD

    size = DWORD(15_000)
    # An adapter may change between calls; honor Windows' updated buffer size.
    for _ in range(3):
        buffer = c.create_string_buffer(size.value)
        status = api.GetAdaptersAddresses(AF_INET, 0x000E, None, buffer, c.byref(size))
        if status == ERROR_NO_DATA:
            return []
        if status != ERROR_BUFFER_OVERFLOW:
            _check(status, "GetAdaptersAddresses")
            break
    else:
        raise OSError("Windows adapter configuration kept changing. Try scanning again.")

    records = []
    pointer = c.cast(buffer, c.POINTER(_AdapterAddresses))
    while pointer:
        adapter = pointer.contents
        pointer = adapter.Next
        if adapter.OperStatus != 1 or adapter.IfType == 24 or not adapter.FirstUnicastAddress:
            continue
        if adapter.Length < _AdapterAddresses.Ipv4Metric.offset + c.sizeof(DWORD):
            raise OSError("Windows returned an unsupported adapter configuration structure.")
        interface = _InterfaceRow(Index=adapter.IfIndex)
        status = api.GetIfEntry2(c.byref(interface))
        if status == ERROR_NOT_FOUND:
            continue  # Adapter disconnected during enumeration.
        _check(status, "GetIfEntry2")
        if interface.OperStatus != 1:
            continue
        unicast = adapter.FirstUnicastAddress
        while unicast:
            entry = unicast.contents
            unicast = entry.Next
            if not entry.Socket.Address or entry.Socket.Length < c.sizeof(_SockaddrIn):
                continue
            address = c.cast(entry.Socket.Address, c.POINTER(_SockaddrIn)).contents
            if address.Family != AF_INET:
                continue
            row = _UnicastRow(Index=adapter.IfIndex)
            row.Address.Ipv4 = address
            status = api.GetUnicastIpAddressEntry(c.byref(row))
            if status == ERROR_NOT_FOUND:
                continue  # Address removed while reading the adapter.
            _check(status, "GetUnicastIpAddressEntry")
            records.append({
                "InterfaceAlias": adapter.FriendlyName or "",
                "InterfaceIndex": adapter.IfIndex,
                "InterfaceType": adapter.IfType,
                "HardwareInterface": bool(interface.StatusFlags & 1),
                "Status": "Up",
                "InterfaceMetric": adapter.Ipv4Metric,
                "IPAddress": str(IPv4Address(bytes(address.Address))),
                "PrefixLength": row.PrefixLength,
                "AddressState": "Preferred" if row.DadState == 4 else "Unavailable",
                "SkipAsSource": bool(row.SkipAsSource),
            })
    return records


def main():
    try:
        records = read_ipv4_interfaces()
    except (OSError, ValueError) as error:
        print(f"Native Windows network detection failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(records))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
