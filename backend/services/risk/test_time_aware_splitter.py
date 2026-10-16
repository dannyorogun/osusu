from datetime import datetime, timedelta, timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from circles.models import Circle, CircleStatus

from risk.models import (
    MemberRiskFeatureSnapshot,
    MemberRiskOutcome,
    RiskOutcomeType,
)

from services.risk.dataset_builder import (
    RiskDataset,
    RiskDatasetBuilder,
)

from services.risk.time_aware_splitter import (
    TimeAwareDatasetSplitter,
    TimeAwareSplit,
)


User = get_user_model()

BASE_TIME = datetime(2026, 1, 1, tzinfo=dt_timezone.utc)


def make_dataset(timestamps):
    """Build a RiskDataset whose row i carries id "s{i}" and feature i."""
    return RiskDataset(
        feature_names=["f"],
        X=[[float(i)] for i in range(len(timestamps))],
        y=[i % 2 for i in range(len(timestamps))],
        snapshot_ids=[f"s{i}" for i in range(len(timestamps))],
        snapshot_created_at=list(timestamps),
    )


def days(n):
    return BASE_TIME + timedelta(days=n)


class TimeAwareDatasetSplitterTests(SimpleTestCase):

    def assert_no_leakage(self, split):
        if split.train.snapshot_created_at and split.test.snapshot_created_at:
            self.assertLess(
                max(split.train.snapshot_created_at),
                min(split.test.snapshot_created_at),
            )

    # Empty / tiny datasets

    def test_empty_dataset_returns_empty_train_and_test(self):
        split = TimeAwareDatasetSplitter.split(make_dataset([]))

        self.assertIsInstance(split, TimeAwareSplit)
        self.assertEqual(split.train.X, [])
        self.assertEqual(split.train.snapshot_ids, [])
        self.assertEqual(split.test.X, [])
        self.assertEqual(split.test.snapshot_ids, [])
        self.assertIsNone(split.split_timestamp)
        self.assertEqual(split.train.feature_names, ["f"])
        self.assertEqual(split.test.feature_names, ["f"])

    def test_single_record_goes_to_train(self):
        split = TimeAwareDatasetSplitter.split(make_dataset([days(0)]))

        self.assertEqual(split.train.snapshot_ids, ["s0"])
        self.assertEqual(split.test.snapshot_ids, [])
        self.assertIsNone(split.split_timestamp)

    def test_two_records_split_one_and_one(self):
        split = TimeAwareDatasetSplitter.split(
            make_dataset([days(0), days(1)])
        )

        self.assertEqual(split.train.snapshot_ids, ["s0"])
        self.assertEqual(split.test.snapshot_ids, ["s1"])
        self.assertEqual(split.split_timestamp, days(1))

    # Ratio and ordering

    def test_splits_eighty_twenty(self):
        split = TimeAwareDatasetSplitter.split(
            make_dataset([days(i) for i in range(10)])
        )

        self.assertEqual(len(split.train.snapshot_ids), 8)
        self.assertEqual(len(split.test.snapshot_ids), 2)
        self.assertEqual(split.split_timestamp, days(8))

    def test_custom_train_ratio(self):
        split = TimeAwareDatasetSplitter.split(
            make_dataset([days(i) for i in range(10)]),
            train_ratio=0.5,
        )

        self.assertEqual(len(split.train.snapshot_ids), 5)
        self.assertEqual(len(split.test.snapshot_ids), 5)

    def test_train_precedes_test_chronologically(self):
        split = TimeAwareDatasetSplitter.split(
            make_dataset([days(i) for i in range(20)])
        )

        self.assert_no_leakage(split)
        self.assertEqual(
            split.train.snapshot_created_at,
            sorted(split.train.snapshot_created_at),
        )
        self.assertEqual(
            split.test.snapshot_created_at,
            sorted(split.test.snapshot_created_at),
        )
        self.assertTrue(
            all(
                ts < split.split_timestamp
                for ts in split.train.snapshot_created_at
            )
        )
        self.assertTrue(
            all(
                ts >= split.split_timestamp
                for ts in split.test.snapshot_created_at
            )
        )

    def test_unsorted_input_is_ordered_by_created_at(self):
        timestamps = [days(4), days(0), days(3), days(1), days(2)]

        split = TimeAwareDatasetSplitter.split(make_dataset(timestamps))

        self.assertEqual(
            split.train.snapshot_ids,
            ["s1", "s3", "s4", "s2"],
        )
        self.assertEqual(split.test.snapshot_ids, ["s0"])
        self.assert_no_leakage(split)

    def test_ordering_is_deterministic_for_equal_timestamps(self):
        dataset = make_dataset([days(0)] * 3 + [days(1)])

        first = TimeAwareDatasetSplitter.split(dataset)
        second = TimeAwareDatasetSplitter.split(dataset)

        self.assertEqual(first.train.snapshot_ids, second.train.snapshot_ids)
        self.assertEqual(first.test.snapshot_ids, second.test.snapshot_ids)

    # Overlap and alignment

    def test_no_overlap_and_full_coverage(self):
        dataset = make_dataset([days(i % 7) for i in range(25)])

        split = TimeAwareDatasetSplitter.split(dataset)

        train_ids = set(split.train.snapshot_ids)
        test_ids = set(split.test.snapshot_ids)

        self.assertEqual(train_ids & test_ids, set())
        self.assertEqual(train_ids | test_ids, set(dataset.snapshot_ids))
        self.assertEqual(
            len(split.train.snapshot_ids) + len(split.test.snapshot_ids),
            len(dataset.snapshot_ids),
        )

    def test_features_labels_and_timestamps_stay_aligned(self):
        timestamps = [days(9 - i) for i in range(10)]
        dataset = make_dataset(timestamps)

        split = TimeAwareDatasetSplitter.split(dataset)

        for part in (split.train, split.test):
            for row, snapshot_id in enumerate(part.snapshot_ids):
                original = dataset.snapshot_ids.index(snapshot_id)
                self.assertEqual(part.X[row], dataset.X[original])
                self.assertEqual(part.y[row], dataset.y[original])
                self.assertEqual(
                    part.snapshot_created_at[row],
                    dataset.snapshot_created_at[original],
                )

    def test_input_dataset_is_not_mutated(self):
        timestamps = [days(3), days(1), days(2), days(0)]
        dataset = make_dataset(timestamps)

        split = TimeAwareDatasetSplitter.split(dataset)
        split.train.X[0].append(99.0)

        self.assertEqual(dataset.snapshot_ids, ["s0", "s1", "s2", "s3"])
        self.assertEqual(dataset.snapshot_created_at, timestamps)
        self.assertEqual(dataset.X, [[0.0], [1.0], [2.0], [3.0]])

    # Boundary timestamp protection

    def test_ties_at_boundary_move_to_test(self):
        # Target cut is 8; rows 6-9 share a timestamp, so the cut
        # moves back to 6 rather than splitting the tie.
        timestamps = [days(i) for i in range(6)] + [days(6)] * 4

        split = TimeAwareDatasetSplitter.split(make_dataset(timestamps))

        self.assertEqual(len(split.train.snapshot_ids), 6)
        self.assertEqual(len(split.test.snapshot_ids), 4)
        self.assertEqual(split.split_timestamp, days(6))
        self.assert_no_leakage(split)

    def test_ties_spanning_whole_train_move_cut_forward(self):
        # Rows 0-8 share a timestamp; moving back would empty train,
        # so the cut moves forward past the tie instead.
        timestamps = [days(0)] * 9 + [days(1)]

        split = TimeAwareDatasetSplitter.split(make_dataset(timestamps))

        self.assertEqual(len(split.train.snapshot_ids), 9)
        self.assertEqual(split.test.snapshot_ids, ["s9"])
        self.assertEqual(split.split_timestamp, days(1))
        self.assert_no_leakage(split)

    def test_all_identical_timestamps_yield_empty_test(self):
        split = TimeAwareDatasetSplitter.split(make_dataset([days(0)] * 5))

        self.assertEqual(len(split.train.snapshot_ids), 5)
        self.assertEqual(split.test.snapshot_ids, [])
        self.assertIsNone(split.split_timestamp)

    def test_sub_second_timestamps_are_respected(self):
        timestamps = [
            BASE_TIME + timedelta(microseconds=i) for i in range(5)
        ]

        split = TimeAwareDatasetSplitter.split(make_dataset(timestamps))

        self.assertEqual(len(split.train.snapshot_ids), 4)
        self.assertEqual(split.test.snapshot_ids, ["s4"])
        self.assert_no_leakage(split)

    # Validation

    def test_invalid_train_ratio_raises(self):
        dataset = make_dataset([days(0), days(1)])

        for ratio in (0, 1, -0.2, 1.5):
            with self.subTest(ratio=ratio):
                with self.assertRaises(ValueError):
                    TimeAwareDatasetSplitter.split(
                        dataset,
                        train_ratio=ratio,
                    )

    def test_mismatched_column_lengths_raise(self):
        dataset = make_dataset([days(0), days(1)])
        dataset.snapshot_created_at = [days(0)]

        with self.assertRaises(ValueError):
            TimeAwareDatasetSplitter.split(dataset)

    def test_duplicate_snapshot_ids_raise(self):
        dataset = make_dataset([days(0), days(1)])
        dataset.snapshot_ids = ["dup", "dup"]

        with self.assertRaises(ValueError):
            TimeAwareDatasetSplitter.split(dataset)


class TimeAwareSplitterWithDatasetBuilderTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="splitter",
            email="splitter@example.com",
            password="StrongPassword123!",
        )

        self.circle = Circle.objects.create(
            creator=self.user,
            name="Splitter Circle",
            description="Time-aware split test",
            status=CircleStatus.ACTIVE,
        )

    def create_labelled_snapshot(self, *, created_at, outcome_type):
        snapshot = MemberRiskFeatureSnapshot.objects.create(
            circle=self.circle,
            member=self.user,
        )

        # created_at is auto_now_add, so pin it with an update.
        MemberRiskFeatureSnapshot.objects.filter(
            pk=snapshot.pk
        ).update(created_at=created_at)

        MemberRiskOutcome.objects.create(
            snapshot=snapshot,
            circle=self.circle,
            member=self.user,
            outcome_type=outcome_type,
            observed_at=created_at + timedelta(days=30),
        )

        return snapshot

    def test_builder_output_splits_chronologically(self):
        snapshots = [
            self.create_labelled_snapshot(
                created_at=days(i),
                outcome_type=(
                    RiskOutcomeType.DEFAULTED
                    if i % 3 == 0
                    else RiskOutcomeType.PAID_ON_TIME
                ),
            )
            for i in range(10)
        ]

        dataset = RiskDatasetBuilder.build_member_default_dataset()

        self.assertEqual(len(dataset.snapshot_created_at), 10)

        split = TimeAwareDatasetSplitter.split(dataset)

        self.assertEqual(
            split.train.snapshot_ids,
            [str(s.id) for s in snapshots[:8]],
        )
        self.assertEqual(
            split.test.snapshot_ids,
            [str(s.id) for s in snapshots[8:]],
        )
        self.assertEqual(split.split_timestamp, days(8))
        self.assertEqual(split.test.y, [0, 1])
