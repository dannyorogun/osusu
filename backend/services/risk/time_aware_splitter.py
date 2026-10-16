import math
from dataclasses import dataclass
from datetime import datetime

from services.risk.dataset_builder import RiskDataset


@dataclass
class TimeAwareSplit:
    train: RiskDataset
    test: RiskDataset

    # Every train row was created strictly before this instant and every
    # test row at or after it. None when the test set is empty.
    split_timestamp: datetime | None


class TimeAwareDatasetSplitter:
    """
    Chronological train/test split for risk datasets.

    Random splits leak the future into training: a model can learn from
    snapshots taken after the ones it is evaluated on. This splitter
    orders rows by snapshot creation time and trains only on the past.

    Guarantees:
    - rows are ordered by (created_at, snapshot_id), so output is
      deterministic even when the input is unsorted;
    - train and test never overlap and together cover every row;
    - max(train.created_at) < min(test.created_at), strictly: rows that
      share a timestamp are never divided across the boundary.
    """

    DEFAULT_TRAIN_RATIO = 0.8

    @classmethod
    def split(
        cls,
        dataset: RiskDataset,
        *,
        train_ratio: float = DEFAULT_TRAIN_RATIO,
    ) -> TimeAwareSplit:

        if not 0 < train_ratio < 1:
            raise ValueError(
                "train_ratio must be between 0 and 1 (exclusive)."
            )

        cls._validate(dataset)

        row_count = len(dataset.snapshot_ids)

        if row_count == 0:
            return TimeAwareSplit(
                train=cls._subset(dataset, []),
                test=cls._subset(dataset, []),
                split_timestamp=None,
            )

        order = sorted(
            range(row_count),
            key=lambda i: (
                dataset.snapshot_created_at[i],
                dataset.snapshot_ids[i],
            ),
        )

        timestamps = [
            dataset.snapshot_created_at[i] for i in order
        ]

        cut = cls._boundary_safe_cut(
            timestamps,
            target=cls._target_cut(row_count, train_ratio),
        )

        split_timestamp = (
            timestamps[cut] if cut < row_count else None
        )

        return TimeAwareSplit(
            train=cls._subset(dataset, order[:cut]),
            test=cls._subset(dataset, order[cut:]),
            split_timestamp=split_timestamp,
        )

    @staticmethod
    def _target_cut(row_count, train_ratio):
        # Train always gets at least one row; test gets at least one
        # whenever there are two or more rows.
        if row_count == 1:
            return 1

        cut = math.floor(row_count * train_ratio)

        return min(max(cut, 1), row_count - 1)

    @staticmethod
    def _boundary_safe_cut(timestamps, *, target):
        """
        Move the cut so no timestamp appears on both sides.

        Prefer moving backward (a smaller train set never leaks). If every
        row before the target shares the boundary timestamp, move forward
        past the tie instead, which may leave the test set empty.
        """
        row_count = len(timestamps)

        if target >= row_count:
            return row_count

        boundary = timestamps[target]

        cut = target
        while cut > 0 and timestamps[cut - 1] == boundary:
            cut -= 1

        if cut > 0:
            return cut

        cut = target
        while cut < row_count and timestamps[cut] == boundary:
            cut += 1

        return cut

    @staticmethod
    def _validate(dataset):
        lengths = {
            "X": len(dataset.X),
            "y": len(dataset.y),
            "snapshot_ids": len(dataset.snapshot_ids),
            "snapshot_created_at": len(dataset.snapshot_created_at),
        }

        if len(set(lengths.values())) != 1:
            raise ValueError(
                f"RiskDataset columns have mismatched lengths: {lengths}"
            )

        if len(set(dataset.snapshot_ids)) != len(dataset.snapshot_ids):
            raise ValueError(
                "RiskDataset contains duplicate snapshot_ids."
            )

    @staticmethod
    def _subset(dataset, indices):
        return RiskDataset(
            feature_names=list(dataset.feature_names),
            X=[list(dataset.X[i]) for i in indices],
            y=[dataset.y[i] for i in indices],
            snapshot_ids=[dataset.snapshot_ids[i] for i in indices],
            snapshot_created_at=[
                dataset.snapshot_created_at[i] for i in indices
            ],
        )
