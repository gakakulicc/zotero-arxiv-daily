"""Give later experimental/conclusion sections their own space in a finite prompt."""

import re
from collections.abc import Callable


HEADING = re.compile(
    r"\\(?:sub)*section\*?\{([^}\n]+)\}"
    r"|^#{1,6}\s+([^\n]+)"
    r"|^\s*(?:\d+(?:\.\d+)*\.?\s+)?((?:Introduction|Method\w*|Approach|Experiments?|"
    r"Evaluation|Results?|Discussion|Limitations?|Conclusions?)[^\n]{0,80})\s*$",
    re.MULTILINE | re.IGNORECASE,
)


def _tail_excerpt(text, truncate, budget):
    text = text[-30000:]
    low, high = 0, len(text)
    while low < high:
        size = (low + high + 1) // 2
        suffix = text[-size:]
        if truncate(suffix, budget) == suffix:
            low = size
        else:
            high = size - 1
    return text[-low:] if low else ""


def paper_evidence(title: str, abstract: str, full_text: str | None,
                   truncate: Callable[[str, int], str], budget: int) -> tuple[str, str]:
    if budget < 256:
        raise ValueError("Summary input_tokens must be at least 256")
    metadata = f"Title: {title}\nAbstract: {abstract}"
    if not full_text:
        return truncate(metadata, budget), "abstract_only"
    header = truncate(metadata, max(128, budget // 3))

    # References are not evidence of the current paper's experimental claims.
    body = re.split(r"\\(?:bibliography|begin\{thebibliography\})|^#{1,6}\s+References\b|^References\s*$",
                    full_text, maxsplit=1, flags=re.MULTILINE | re.IGNORECASE)[0]
    headings = list(HEADING.finditer(body))
    groups = {"Methods": [], "Experiments/results": [], "Conclusions/limitations": []}
    for index, match in enumerate(headings):
        name = next(group for group in match.groups() if group is not None)
        excerpt = body[match.start():headings[index + 1].start() if index + 1 < len(headings) else len(body)]
        if re.search(r"experiment|evaluat|result", name, re.I):
            groups["Experiments/results"].append(excerpt)
        elif re.search(r"conclu|limit|discuss", name, re.I):
            groups["Conclusions/limitations"].append(excerpt)
        elif re.search(r"method|approach", name, re.I):
            groups["Methods"].append(excerpt)
    excerpts = [(name, values) for name, values in groups.items() if values]
    matched_sections = bool(excerpts)
    # Reserve a small author/header excerpt and distribute the rest across sections.
    parts = [header, "Paper opening:\n" + truncate(body, max(32, budget // 12))]
    if not excerpts:
        excerpts = [("Unstructured body beginning", [body]), ("Unstructured body ending", [body[-12000:]])]
    allowance = max(32, int(budget * .5) // len(excerpts))
    for name, values in excerpts:
        # Give every matching section a share, so a long Discussion cannot crowd out Limitations.
        snippets = ([_tail_excerpt(body, truncate, allowance)] if name == "Unstructured body ending" else
                    [truncate(value, max(16, allowance // len(values))) for value in values])
        parts.append(name + ":\n" + truncate("\n".join(snippets), allowance))
    return truncate("\n\n".join(parts), budget), "section_excerpts" if matched_sections else "body_excerpts"
