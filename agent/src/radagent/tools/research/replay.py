from typing import Any

from radagent.tools.research.events import ResearchEvent


def for_replay(timeline: list[tuple[float, ResearchEvent]]) -> list[dict[str, Any]]:
    """
    Trim a run's events to what a reopened chat needs to show it again, as it looked when it ended

    Thoughts go, the report is kept in one piece, and each agent keeps a screenshot only of the last page it read,
    which is what its window shows once the run is over; the rest would make a saved chat megabytes larger

    Args:
        timeline: {list[tuple[float, ResearchEvent]]} Each event with the seconds since the run started

    Returns:
        events: {list[dict]} `{"t": seconds, "event": event}` in order, ready to save as JSON
    """
    final_page: dict[str, int] = {}
    for index, (_, event) in enumerate(timeline):
        if event["kind"] == "page":
            final_page[event["agent"]] = index

    kept: list[dict[str, Any]] = []
    report, report_at = "", 0.0
    for index, (at, event) in enumerate(timeline):
        if event["kind"] == "thought":
            continue
        if event["kind"] == "report_delta":
            report += event["delta"]
            report_at = at
            continue
        saved: dict[str, Any] = dict(event)
        if event["kind"] == "page" and final_page[event["agent"]] != index:
            saved["screenshot"] = None
        kept.append({"t": round(at, 2), "event": saved})

    # The report only ever accumulates, so one event for all of it lands in the same place
    if report:
        kept.append({"t": round(report_at, 2), "event": {"kind": "report_delta", "delta": report}})
    return kept
