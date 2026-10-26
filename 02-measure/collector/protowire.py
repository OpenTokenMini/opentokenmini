"""N-pb: stdlib decoder for OTLP protobuf logs/traces requests -> OTLP JSON (MessageToDict shape, hex ids).

Only the fields normalize and redaction need are mapped; unknown fields are skipped. Enums stay ints.
"""
import base64, struct

AV = {}  # AnyValue, filled below (recursive)
KV = {1: ("key", "str"), 2: ("value", AV)}
AV.update({1: ("stringValue", "str"), 2: ("boolValue", "bool"), 3: ("intValue", "i64"), 4: ("doubleValue", "dbl"),
           5: ("arrayValue", {1: ("values", AV)}), 6: ("kvlistValue", {1: ("values", KV)}), 7: ("bytesValue", "b64")})
RES = {1: ("attributes", KV), 2: ("droppedAttributesCount", "u")}
SCOPE = {1: ("name", "str"), 2: ("version", "str"), 3: ("attributes", KV), 4: ("droppedAttributesCount", "u")}
LOG = {1: ("timeUnixNano", "f64"), 11: ("observedTimeUnixNano", "f64"), 2: ("severityNumber", "u"),
       3: ("severityText", "str"), 5: ("body", AV), 6: ("attributes", KV), 7: ("droppedAttributesCount", "u"),
       8: ("flags", "f32"), 9: ("traceId", "hex"), 10: ("spanId", "hex"), 12: ("eventName", "str")}
EVENT = {1: ("timeUnixNano", "f64"), 2: ("name", "str"), 3: ("attributes", KV), 4: ("droppedAttributesCount", "u")}
SPAN = {1: ("traceId", "hex"), 2: ("spanId", "hex"), 3: ("traceState", "str"), 4: ("parentSpanId", "hex"),
        16: ("flags", "f32"), 5: ("name", "str"), 6: ("kind", "u"), 7: ("startTimeUnixNano", "f64"),
        8: ("endTimeUnixNano", "f64"), 9: ("attributes", KV), 10: ("droppedAttributesCount", "u"),
        11: ("events", EVENT), 15: ("status", {2: ("message", "str"), 3: ("code", "u")})}
REQUEST = {
    "logs": {1: ("resourceLogs", {1: ("resource", RES), 3: ("schemaUrl", "str"),
                                  2: ("scopeLogs", {1: ("scope", SCOPE), 2: ("logRecords", LOG), 3: ("schemaUrl", "str")})})},
    "traces": {1: ("resourceSpans", {1: ("resource", RES), 3: ("schemaUrl", "str"),
                                     2: ("scopeSpans", {1: ("scope", SCOPE), 2: ("spans", SPAN), 3: ("schemaUrl", "str")})})},
}
REPEATED = {"attributes", "values", "events", "resourceLogs", "scopeLogs", "logRecords", "resourceSpans", "scopeSpans", "spans"}


def varint(b, i):
    n = s = 0
    while True:
        c = b[i]
        i += 1
        n |= (c & 0x7F) << s
        s += 7
        if c < 0x80:
            return n, i


def _fixed(n):
    return lambda b, i: (b[i:i + n], i + n)


def _len_delim(b, i):
    n, i = varint(b, i)
    return b[i:i + n], i + n


# wire type -> reader(b, i) -> (raw value, next i)
WIRE = {0: varint, 1: _fixed(8), 5: _fixed(4), 2: _len_delim}
# spec scalar type -> raw value -> JSON value; types not listed ("u") pass through
CONVERT = {"str": lambda v: v.decode(), "bool": bool, "i64": lambda v: str(v - (1 << 64) if v >= 1 << 63 else v),
           "f64": lambda v: str(struct.unpack("<Q", v)[0]), "f32": lambda v: struct.unpack("<I", v)[0],
           "dbl": lambda v: struct.unpack("<d", v)[0], "hex": lambda v: v.hex(), "b64": lambda v: base64.b64encode(v).decode()}


def _field(b, i):
    """Read one (field number, raw value, next i); raises on bad wire type or truncation."""
    tag, i = varint(b, i)
    wt = tag & 7
    if wt not in WIRE:
        raise ValueError(f"wire type {wt}")
    v, i = WIRE[wt](b, i)
    if i > len(b):
        raise ValueError("truncated")
    return tag >> 3, v, i


def decode(b, spec):
    """Parse one message; raises ValueError/IndexError on malformed input."""
    out, i = {}, 0
    while i < len(b):
        f, v, i = _field(b, i)
        if f not in spec:
            continue
        name, t = spec[f]
        v = decode(v, t) if isinstance(t, dict) else CONVERT.get(t, lambda x: x)(v)
        if name in REPEATED:
            out.setdefault(name, []).append(v)
        else:
            out[name] = v
    return out
