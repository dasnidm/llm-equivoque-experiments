"""Serialize dashboard writes across local workers, never across unknown VMs."""
from .coordination import GitCoordinator
from .fast_pacing import shared_lock


class SharedBoardCoordinator(GitCoordinator):
    def __init__(self, remote, branch, cache_dir, *, shared_board_lock, **kwargs):
        self.shared_board_lock = shared_board_lock
        super().__init__(remote, branch, cache_dir, **kwargs)

    def _mutate(self, label, fn):
        # Permission reads and actual model sends do not take this lock.
        # The upstream implementation still performs remote FF verification.
        with shared_lock(self.shared_board_lock):
            return super()._mutate(label, fn)
