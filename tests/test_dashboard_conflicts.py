import unittest
from unittest.mock import patch

from app_core.dashboard_service import (
    build_conflict_index,
    dashboard_overview,
    detail_results,
    dimension_stats,
    ranking,
    sample_identity,
    worker_scope_stats,
    worker_stats,
)


def result_row(
    row_id,
    worker,
    filename,
    overall,
    *,
    user_id=None,
    logic=None,
    scene="scene-1",
    v_a="model-a",
    v_b="model-b",
    task_type="T2I",
):
    return {
        "id": row_id,
        "task_type": task_type,
        "eval_mode": "full",
        "v_a": v_a,
        "v_b": v_b,
        "scene": scene,
        "filename": filename,
        "overall": overall,
        "aesthetic": None,
        "logic": logic,
        "consistency": None,
        "fidelity": None,
        "text_consistency": None,
        "structure_reasonableness": None,
        "motion_reasonableness": None,
        "dynamism": None,
        "physical_plausibility": None,
        "visual_quality": None,
        "image_consistency": None,
        "selected_dimensions": "[]",
        "worker": worker,
        "user_id": user_id,
        "timestamp": "2026-08-13T10:00:00+08:00",
        "duration_seconds": 1,
        "skipped": 0,
        "bad_case_tags_a": "[]",
        "bad_case_tags_b": "[]",
        "bad_case_categories_a": "[]",
        "bad_case_categories_b": "[]",
    }


class DashboardConflictIndexTests(unittest.TestCase):
    def conflict_dimensions(self, *rows):
        index = build_conflict_index(rows, ["overall", "logic"])
        return index.get(sample_identity(rows[0]), set())

    def test_distinct_evaluators_with_opposite_winners_conflict(self):
        rows = (
            result_row(1, "alice", "one.png", "model-a", user_id=10),
            result_row(2, "bob", "one.png", "model-b", user_id=20),
        )

        self.assertEqual(self.conflict_dimensions(*rows), {"overall"})

    def test_conflict_tolerance_uses_opposing_vote_minority_share(self):
        rows = [
            result_row(index, f"majority-{index}", "one.png", "model-a", user_id=index)
            for index in range(1, 5)
        ]
        rows.append(result_row(5, "minority", "one.png", "model-b", user_id=5))

        strict = build_conflict_index(rows, ["overall"], conflict_tolerance=0)
        below_boundary = build_conflict_index(
            rows, ["overall"], conflict_tolerance=0.19
        )
        at_boundary = build_conflict_index(
            rows, ["overall"], conflict_tolerance=0.20
        )
        fully_tolerant = build_conflict_index(
            rows, ["overall"], conflict_tolerance=0.50
        )

        sample = sample_identity(rows[0])
        self.assertEqual(strict[sample], {"overall"})
        self.assertEqual(below_boundary[sample], {"overall"})
        self.assertNotIn(sample, at_boundary)
        self.assertNotIn(sample, fully_tolerant)

    def test_ties_bad_cases_and_one_identity_do_not_conflict(self):
        ties = (
            result_row(1, "alice", "tie.png", "tie_good", user_id=10),
            result_row(2, "bob", "tie.png", "tie_bad", user_id=20),
        )
        ties[0]["bad_case_tags_a"] = '["模糊失焦"]'
        self.assertEqual(self.conflict_dimensions(*ties), set())

        duplicate_identity = (
            result_row(3, "old-name", "same-user.png", "model-a", user_id=30),
            result_row(4, "new-name", "same-user.png", "model-b", user_id=30),
        )
        self.assertEqual(self.conflict_dimensions(*duplicate_identity), set())

    def test_missing_user_id_uses_namespaced_worker_identity(self):
        rows = (
            result_row(1, "alice", "fallback.png", "model-a"),
            result_row(2, "bob", "fallback.png", "model-b"),
        )
        self.assertEqual(self.conflict_dimensions(*rows), {"overall"})

        user_and_worker_named_the_same = (
            result_row(3, "different", "namespace.png", "model-a", user_id="alice"),
            result_row(4, "alice", "namespace.png", "model-b"),
        )
        self.assertEqual(
            self.conflict_dimensions(*user_and_worker_named_the_same), {"overall"}
        )

    def test_sample_and_dimension_boundaries_are_isolated(self):
        base = result_row(
            1,
            "alice",
            "one.png",
            "model-a",
            user_id=1,
            logic="model-a",
        )
        for changed in (
            result_row(
                2,
                "bob",
                "two.png",
                "model-b",
                user_id=2,
                logic="model-a",
            ),
            result_row(
                3,
                "bob",
                "one.png",
                "model-b",
                user_id=2,
                logic="model-a",
                scene="scene-2",
            ),
            result_row(
                4,
                "bob",
                "one.png",
                "other-b",
                user_id=2,
                logic="model-a",
                v_b="other-b",
            ),
            result_row(
                5,
                "bob",
                "one.png",
                "model-b",
                user_id=2,
                logic="model-a",
                task_type="TI2I",
            ),
        ):
            with self.subTest(changed=changed):
                self.assertEqual(
                    build_conflict_index([base, changed], ["overall", "logic"]),
                    {},
                )

        same_sample = result_row(
            6,
            "bob",
            "one.png",
            "model-b",
            user_id=2,
            logic="model-a",
        )
        index = build_conflict_index([base, same_sample], ["overall", "logic"])
        self.assertEqual(index[sample_identity(base)], {"overall"})

    def test_reversed_model_columns_share_the_canonical_sample_key(self):
        rows = [
            result_row(1, "alice", "one.png", "model-a", user_id=1),
            result_row(
                2,
                "bob",
                "one.png",
                "model-b",
                user_id=2,
                v_a="model-b",
                v_b="model-a",
            ),
        ]

        index = build_conflict_index(rows, ["overall"])

        self.assertEqual(sample_identity(rows[0]), sample_identity(rows[1]))
        self.assertEqual(index[sample_identity(rows[0])], {"overall"})

    def test_dimension_stats_keep_raw_metadata_and_filter_only_that_dimension(self):
        rows = [
            result_row(
                1,
                "alice",
                "one.png",
                "model-a",
                user_id=10,
                logic="model-a",
            ),
            result_row(
                2,
                "bob",
                "one.png",
                "model-b",
                user_id=20,
                logic="model-a",
            ),
        ]
        index = build_conflict_index(rows, ["overall", "logic"])

        raw = dimension_stats(
            rows, "overall", "model-a", "model-b", conflict_index=index
        )
        self.assertEqual(raw["sample_count"], 1)
        self.assertEqual(raw["conflict_sample_count"], 1)
        self.assertEqual(raw["total"], 2)

        filtered = dimension_stats(
            rows,
            "overall",
            "model-a",
            "model-b",
            conflict_index=index,
            exclude_conflicts=True,
        )
        self.assertEqual(filtered["sample_count"], 1)
        self.assertEqual(filtered["conflict_sample_count"], 1)
        self.assertEqual(filtered["total"], 0)

        logic = dimension_stats(
            rows,
            "logic",
            "model-a",
            "model-b",
            conflict_index=index,
            exclude_conflicts=True,
        )
        self.assertEqual(logic["sample_count"], 1)
        self.assertEqual(logic["conflict_sample_count"], 0)
        self.assertEqual(logic["total"], 2)

    def test_sample_denominator_is_unique_not_vote_count(self):
        rows = [
            result_row(1, "alice", "one.png", "model-a", user_id=1),
            result_row(2, "bob", "one.png", "model-a", user_id=2),
            result_row(3, "alice", "two.png", "tie_good", user_id=1),
        ]

        stats = dimension_stats(rows, "overall", "model-a", "model-b")

        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["sample_count"], 2)
        self.assertEqual(stats["intersection_sample_count"], 1)
        self.assertEqual(stats["conflict_sample_count"], 0)

    def test_union_and_intersection_conflict_denominators_are_distinct(self):
        rows = [
            result_row(1, "alice", "conflict.png", "model-a", user_id=1),
            result_row(2, "bob", "conflict.png", "model-b", user_id=2),
            result_row(3, "alice", "agreed.png", "model-a", user_id=1),
            result_row(4, "bob", "agreed.png", "model-a", user_id=2),
            result_row(5, "alice", "alice-only.png", "tie_good", user_id=1),
            result_row(6, "bob", "bob-only.png", "model-b", user_id=2),
            result_row(7, "alice", "shared-tie.png", "tie_good", user_id=1),
            result_row(8, "bob", "shared-tie.png", "tie_bad", user_id=2),
        ]

        stats = dimension_stats(rows, "overall", "model-a", "model-b")

        self.assertEqual(stats["conflict_sample_count"], 1)
        self.assertEqual(stats["sample_count"], 5)
        self.assertEqual(stats["intersection_sample_count"], 3)


class DashboardConflictServiceTests(unittest.TestCase):
    @staticmethod
    def overview_page(rows):
        return {
            "rows": rows,
            "page": 1,
            "page_size": 10,
            "total_pairs": 1,
            "total_pages": 1,
            "scenes": sorted({row["scene"] for row in rows}),
        }

    @patch("app_core.dashboard_service.fetch_overview_page")
    @patch("app_core.dashboard_service.fetch_result_rows")
    def test_overview_and_detail_report_raw_conflict_metadata(
        self, fetch_rows, fetch_page
    ):
        rows = [
            result_row(
                1,
                "alice",
                "one.png",
                "model-a",
                user_id=10,
                logic="model-a",
            ),
            result_row(
                2,
                "bob",
                "one.png",
                "model-b",
                user_id=20,
                logic="model-a",
            ),
        ]
        fetch_rows.return_value = rows
        fetch_page.return_value = self.overview_page(rows)

        overview = dashboard_overview("T2I")
        pair = overview["pairs"][0]
        self.assertEqual(pair["dims"]["overall"]["conflict_sample_count"], 1)
        self.assertEqual(pair["dims"]["overall"]["sample_count"], 1)
        self.assertEqual(
            pair["scenes"][0]["dims"]["overall"]["conflict_sample_count"], 1
        )

        with patch(
            "app_core.dashboard_service.get_preview_prompt_text",
            return_value="prompt",
        ), patch("app_core.dashboard_service.get_ref_image_url", return_value=None):
            details = detail_results("T2I", "model-a", "model-b", "scene-1")

        self.assertEqual(len(details), 2)
        self.assertTrue(all(row["has_conflict"] for row in details))
        self.assertTrue(
            all(row["conflict_dimensions"] == ["overall"] for row in details)
        )

    @patch("app_core.dashboard_service.fetch_overview_page")
    def test_overview_excludes_conflicts_but_preserves_raw_metadata(self, fetch_page):
        rows = [
            result_row(1, "alice", "conflict.png", "model-a", user_id=1),
            result_row(2, "bob", "conflict.png", "model-b", user_id=2),
            result_row(3, "alice", "clean.png", "model-a", user_id=1),
        ]
        fetch_page.return_value = self.overview_page(rows)

        overview = dashboard_overview("T2I", exclude_conflicts=True)
        stats = overview["pairs"][0]["dims"]["overall"]

        self.assertEqual(stats["total"], 1)
        self.assertEqual(stats["v_a_wins"], 1)
        self.assertEqual(stats["sample_count"], 2)
        self.assertEqual(stats["conflict_sample_count"], 1)

    @patch("app_core.dashboard_service.fetch_result_rows")
    def test_worker_stats_excludes_conflicts_using_global_index(self, fetch_rows):
        fetch_result = [
            result_row(1, "alice", "conflict.png", "model-a", user_id=1),
            result_row(2, "bob", "conflict.png", "model-b", user_id=2),
            result_row(3, "alice", "clean.png", "model-a", user_id=1),
        ]
        fetch_rows.return_value = fetch_result

        raw = worker_stats(
            "T2I", "model-a", "model-b", exclude_conflicts=False
        )
        filtered = worker_stats(
            "T2I", "model-a", "model-b", exclude_conflicts=True
        )

        self.assertEqual(sum(item["overall"]["total"] for item in raw), 3)
        self.assertEqual(sum(item["overall"]["total"] for item in filtered), 1)

    @patch("app_core.dashboard_service.fetch_result_rows")
    def test_worker_scope_recomputes_conflicts_for_selected_evaluators(self, fetch_rows):
        fetch_rows.return_value = [
            result_row(1, "alice", "shared.png", "model-a", user_id=1),
            result_row(2, "bob", "shared.png", "model-a", user_id=2),
            result_row(3, "carol", "shared.png", "model-b", user_id=3),
        ]

        same_side = worker_scope_stats(
            "T2I", "model-a", "model-b", workers=["alice", "bob"]
        )
        opposite = worker_scope_stats(
            "T2I", "model-a", "model-b", workers=["alice", "carol"]
        )
        tolerated = worker_scope_stats(
            "T2I",
            "model-a",
            "model-b",
            workers=["alice", "carol"],
            conflict_tolerance=0.5,
        )

        self.assertEqual(same_side["available_workers"], ["alice", "bob", "carol"])
        self.assertEqual(same_side["scope"]["dims"]["overall"]["conflict_sample_count"], 0)
        self.assertEqual(opposite["scope"]["dims"]["overall"]["conflict_sample_count"], 1)
        self.assertEqual(tolerated["scope"]["dims"]["overall"]["conflict_sample_count"], 0)
        self.assertEqual([row["worker"] for row in opposite["workers"]], ["alice", "carol"])

    @patch("app_core.dashboard_service.fetch_result_rows")
    def test_ranking_excludes_conflicts_for_the_selected_dimension(self, fetch_rows):
        fetch_rows.return_value = [
            result_row(1, "alice", "conflict.png", "model-a", user_id=1),
            result_row(2, "bob", "conflict.png", "model-b", user_id=2),
            result_row(3, "alice", "clean.png", "model-a", user_id=1),
        ]

        raw = ranking("T2I", dimension="overall", exclude_conflicts=False)
        filtered = ranking("T2I", dimension="overall", exclude_conflicts=True)

        self.assertEqual({item["total"] for item in raw}, {3})
        self.assertEqual({item["total"] for item in filtered}, {1})


if __name__ == "__main__":
    unittest.main()
