"""Parser for Green Button / ESPI (Energy Services Provider Interface) XML data."""

from __future__ import annotations

from dataclasses import dataclass, field
from xml.etree import ElementTree

ATOM_NS = "http://www.w3.org/2005/Atom"
ESPI_NS = "http://naesb.org/espi"

FLOW_FORWARD = 1
FLOW_REVERSE = 19

UOM_WH = 72
UOM_KWH = 119


@dataclass
class TimeParameters:
    """Timezone and DST parameters from the ESPI feed."""

    tz_offset: int
    dst_offset: int
    dst_start_rule: str
    dst_end_rule: str


@dataclass
class ReadingType:
    """Describes the unit and flow direction of a meter reading."""

    uom: int = UOM_WH
    power_of_ten_multiplier: int = 0
    flow_direction: int = FLOW_FORWARD
    interval_length: int = 0
    commodity: int = 0


@dataclass
class IntervalReading:
    """A single energy reading for a time period."""

    start: int
    duration: int
    value_kwh: float


@dataclass
class MeterReadingData:
    """Parsed meter reading with its type info and interval readings."""

    reading_type: ReadingType
    readings: list[IntervalReading] = field(default_factory=list)


@dataclass
class UsagePointData:
    """Parsed usage point (service location) with all its meter readings."""

    title: str
    service_kind: int = 0
    meter_readings: list[MeterReadingData] = field(default_factory=list)


@dataclass
class GreenButtonData:
    """Complete parsed Green Button download."""

    title: str
    usage_points: list[UsagePointData] = field(default_factory=list)
    time_params: TimeParameters | None = None


def _find_text(element: ElementTree.Element, path: str) -> str | None:
    """Find text content of a child element."""
    child = element.find(path)
    if child is not None and child.text is not None:
        return child.text.strip()
    return None


def _find_int(element: ElementTree.Element, path: str, default: int = 0) -> int:
    """Find integer text content of a child element."""
    text = _find_text(element, path)
    if text is not None:
        return int(text)
    return default


def _convert_to_kwh(value: int, reading_type: ReadingType) -> float:
    """Convert a raw ESPI value to kWh using unit and multiplier info."""
    scaled = value * (10 ** reading_type.power_of_ten_multiplier)
    if reading_type.uom == UOM_WH:
        return scaled / 1000.0
    if reading_type.uom == UOM_KWH:
        return float(scaled)
    return scaled / 1000.0


def _parse_time_parameters(content: ElementTree.Element) -> TimeParameters:
    """Parse LocalTimeParameters from an entry's content."""
    ltp = content.find(f"{{{ESPI_NS}}}LocalTimeParameters")
    if ltp is None:
        raise ValueError("Expected LocalTimeParameters element")
    return TimeParameters(
        tz_offset=_find_int(ltp, f"{{{ESPI_NS}}}tzOffset"),
        dst_offset=_find_int(ltp, f"{{{ESPI_NS}}}dstOffset"),
        dst_start_rule=_find_text(ltp, f"{{{ESPI_NS}}}dstStartRule") or "",
        dst_end_rule=_find_text(ltp, f"{{{ESPI_NS}}}dstEndRule") or "",
    )


def _parse_reading_type(content: ElementTree.Element) -> ReadingType:
    """Parse ReadingType from an entry's content."""
    rt = content.find(f"{{{ESPI_NS}}}ReadingType")
    if rt is None:
        raise ValueError("Expected ReadingType element")
    return ReadingType(
        uom=_find_int(rt, f"{{{ESPI_NS}}}uom", UOM_WH),
        power_of_ten_multiplier=_find_int(
            rt, f"{{{ESPI_NS}}}powerOfTenMultiplier"
        ),
        flow_direction=_find_int(rt, f"{{{ESPI_NS}}}flowDirection", FLOW_FORWARD),
        interval_length=_find_int(rt, f"{{{ESPI_NS}}}intervalLength"),
        commodity=_find_int(rt, f"{{{ESPI_NS}}}commodity"),
    )


def _parse_interval_block(
    content: ElementTree.Element, reading_type: ReadingType
) -> list[IntervalReading]:
    """Parse IntervalBlock into a list of IntervalReadings."""
    block = content.find(f"{{{ESPI_NS}}}IntervalBlock")
    if block is None:
        return []

    readings: list[IntervalReading] = []
    for ir in block.findall(f"{{{ESPI_NS}}}IntervalReading"):
        tp = ir.find(f"{{{ESPI_NS}}}timePeriod")
        if tp is None:
            continue
        start = _find_int(tp, f"{{{ESPI_NS}}}start")
        duration = _find_int(tp, f"{{{ESPI_NS}}}duration")
        raw_value = _find_int(ir, f"{{{ESPI_NS}}}value")
        readings.append(
            IntervalReading(
                start=start,
                duration=duration,
                value_kwh=_convert_to_kwh(raw_value, reading_type),
            )
        )

    readings.sort(key=lambda r: r.start)
    return readings


def _get_entry_links(entry: ElementTree.Element) -> dict[str, str]:
    """Extract link hrefs by rel from an Atom entry."""
    links: dict[str, str] = {}
    for link in entry.findall(f"{{{ATOM_NS}}}link"):
        rel = link.get("rel", "")
        href = link.get("href", "")
        if rel and href:
            links[rel] = href
    return links


def _get_self_href(entry: ElementTree.Element) -> str:
    """Get the self link href from an Atom entry."""
    return _get_entry_links(entry).get("self", "")


def _get_related_hrefs(entry: ElementTree.Element) -> list[str]:
    """Get all related link hrefs from an Atom entry."""
    hrefs: list[str] = []
    for link in entry.findall(f"{{{ATOM_NS}}}link"):
        if link.get("rel") == "related":
            href = link.get("href", "")
            if href:
                hrefs.append(href)
    return hrefs


def parse_green_button_xml(xml_content: str) -> GreenButtonData:
    """Parse a Green Button ESPI XML document.

    Follows Atom link associations to correctly map:
    UsagePoint → MeterReading → ReadingType + IntervalBlock
    """
    root = ElementTree.fromstring(xml_content)

    feed_title_el = root.find(f"{{{ATOM_NS}}}title")
    feed_title = (
        feed_title_el.text.strip() if feed_title_el is not None and feed_title_el.text else ""
    )

    entries_by_href: dict[str, ElementTree.Element] = {}
    time_params: TimeParameters | None = None
    reading_types: dict[str, ReadingType] = {}

    usage_point_entries: list[ElementTree.Element] = []
    meter_reading_entries: list[ElementTree.Element] = []
    interval_block_entries: list[ElementTree.Element] = []

    for entry in root.findall(f"{{{ATOM_NS}}}entry"):
        self_href = _get_self_href(entry)
        if self_href:
            entries_by_href[self_href] = entry

        content = entry.find(f"{{{ATOM_NS}}}content")
        if content is None:
            continue

        if content.find(f"{{{ESPI_NS}}}LocalTimeParameters") is not None:
            time_params = _parse_time_parameters(content)
        elif content.find(f"{{{ESPI_NS}}}ReadingType") is not None:
            rt = _parse_reading_type(content)
            reading_types[self_href] = rt
        elif content.find(f"{{{ESPI_NS}}}UsagePoint") is not None:
            usage_point_entries.append(entry)
        elif content.find(f"{{{ESPI_NS}}}MeterReading") is not None:
            meter_reading_entries.append(entry)
        elif content.find(f"{{{ESPI_NS}}}IntervalBlock") is not None:
            interval_block_entries.append(entry)

    mr_to_reading_type: dict[str, ReadingType] = {}
    mr_to_interval_blocks: dict[str, list[ElementTree.Element]] = {}

    for mr_entry in meter_reading_entries:
        mr_href = _get_self_href(mr_entry)
        related = _get_related_hrefs(mr_entry)
        for href in related:
            if href in reading_types:
                mr_to_reading_type[mr_href] = reading_types[href]
            ib_prefix = href.rstrip("/")
            for ib_entry in interval_block_entries:
                ib_href = _get_self_href(ib_entry)
                if ib_href.startswith(ib_prefix):
                    mr_to_interval_blocks.setdefault(mr_href, []).append(ib_entry)

    if not mr_to_reading_type and reading_types:
        default_rt = next(iter(reading_types.values()))
        for mr_entry in meter_reading_entries:
            mr_href = _get_self_href(mr_entry)
            mr_to_reading_type.setdefault(mr_href, default_rt)

    if not mr_to_interval_blocks:
        for mr_entry in meter_reading_entries:
            mr_href = _get_self_href(mr_entry)
            mr_to_interval_blocks.setdefault(mr_href, interval_block_entries)

    up_to_mrs: dict[str, list[str]] = {}
    for up_entry in usage_point_entries:
        up_href = _get_self_href(up_entry)
        related = _get_related_hrefs(up_entry)
        for href in related:
            mr_prefix = href.rstrip("/")
            for mr_entry in meter_reading_entries:
                mr_href = _get_self_href(mr_entry)
                if mr_href.startswith(mr_prefix):
                    up_to_mrs.setdefault(up_href, []).append(mr_href)

    usage_points: list[UsagePointData] = []
    for up_entry in usage_point_entries:
        up_href = _get_self_href(up_entry)
        content = up_entry.find(f"{{{ATOM_NS}}}content")

        title_el = up_entry.find(f"{{{ATOM_NS}}}title")
        up_title = title_el.text.strip() if title_el is not None and title_el.text else ""

        service_kind = 0
        if content is not None:
            up_el = content.find(f"{{{ESPI_NS}}}UsagePoint")
            if up_el is not None:
                sc = up_el.find(f"{{{ESPI_NS}}}ServiceCategory")
                if sc is not None:
                    service_kind = _find_int(sc, f"{{{ESPI_NS}}}kind")

        mr_hrefs = up_to_mrs.get(up_href, [])
        meter_readings: list[MeterReadingData] = []
        for mr_href in mr_hrefs:
            rt = mr_to_reading_type.get(mr_href, ReadingType())
            all_readings: list[IntervalReading] = []
            for ib_entry in mr_to_interval_blocks.get(mr_href, []):
                ib_content = ib_entry.find(f"{{{ATOM_NS}}}content")
                if ib_content is not None:
                    all_readings.extend(_parse_interval_block(ib_content, rt))
            all_readings.sort(key=lambda r: r.start)
            meter_readings.append(
                MeterReadingData(reading_type=rt, readings=all_readings)
            )

        usage_points.append(
            UsagePointData(
                title=up_title,
                service_kind=service_kind,
                meter_readings=meter_readings,
            )
        )

    if not usage_points and (meter_reading_entries or interval_block_entries):
        meter_readings = []
        for mr_entry in meter_reading_entries:
            mr_href = _get_self_href(mr_entry)
            rt = mr_to_reading_type.get(mr_href, ReadingType())
            all_readings: list[IntervalReading] = []
            for ib_entry in mr_to_interval_blocks.get(mr_href, []):
                ib_content = ib_entry.find(f"{{{ATOM_NS}}}content")
                if ib_content is not None:
                    all_readings.extend(_parse_interval_block(ib_content, rt))
            all_readings.sort(key=lambda r: r.start)
            meter_readings.append(
                MeterReadingData(reading_type=rt, readings=all_readings)
            )

        if not meter_readings and interval_block_entries:
            rt = next(iter(reading_types.values()), ReadingType())
            all_readings = []
            for ib_entry in interval_block_entries:
                ib_content = ib_entry.find(f"{{{ATOM_NS}}}content")
                if ib_content is not None:
                    all_readings.extend(_parse_interval_block(ib_content, rt))
            all_readings.sort(key=lambda r: r.start)
            meter_readings.append(
                MeterReadingData(reading_type=rt, readings=all_readings)
            )

        usage_points.append(
            UsagePointData(title=feed_title, meter_readings=meter_readings)
        )

    return GreenButtonData(
        title=feed_title,
        usage_points=usage_points,
        time_params=time_params,
    )
