import json
from typing import List, Optional

from .config import BAD_CASE_LABEL_TO_CATEGORY


def normalize_bad_case_tags(tags: Optional[List[str]]) -> List[str]:
    if not tags:
        return []

    result = []
    for tag in tags:
        if tag in BAD_CASE_LABEL_TO_CATEGORY and tag not in result:
            result.append(tag)
    return result


def categories_from_tags(tags: List[str]) -> List[str]:
    categories = []
    for tag in tags:
        category = BAD_CASE_LABEL_TO_CATEGORY.get(tag)
        if category and category not in categories:
            categories.append(category)
    return categories


def safe_load_json_list(value: Optional[str]) -> List[str]:
    if not value:
        return []
    try:
        data = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def derive_overall_result(dim_results: List[str]) -> str:
    counts = {}
    for result in dim_results:
        counts[result] = counts.get(result, 0) + 1
    if not counts:
        return "tie"

    best_choice = max(counts.items(), key=lambda item: item[1])[0]
    top_count = counts[best_choice]
    if top_count == 1:
        return "tie"
    if sum(1 for count in counts.values() if count == top_count) > 1:
        return "tie"
    return best_choice


def build_bad_case_stats(rows):
    stats = {
        "v_a": {"bad_count": 0, "total": 0, "rate": 0.0, "categories": {}, "tags": {}},
        "v_b": {"bad_count": 0, "total": 0, "rate": 0.0, "categories": {}, "tags": {}},
    }

    for row in rows:
        tags_a = safe_load_json_list(row["bad_case_tags_a"])
        tags_b = safe_load_json_list(row["bad_case_tags_b"])
        stats["v_a"]["total"] += 1
        stats["v_b"]["total"] += 1
        if tags_a:
            stats["v_a"]["bad_count"] += 1
        if tags_b:
            stats["v_b"]["bad_count"] += 1

        for side_key, tags in (("v_a", tags_a), ("v_b", tags_b)):
            seen_categories = set()
            for tag in tags:
                category = BAD_CASE_LABEL_TO_CATEGORY.get(tag)
                if not category:
                    continue
                stats[side_key]["tags"][tag] = stats[side_key]["tags"].get(tag, 0) + 1
                if category not in seen_categories:
                    stats[side_key]["categories"][category] = stats[side_key]["categories"].get(category, 0) + 1
                    seen_categories.add(category)

    for key in ("v_a", "v_b"):
        total = stats[key]["total"]
        stats[key]["rate"] = round(stats[key]["bad_count"] / total * 100, 1) if total else 0.0
    return stats
