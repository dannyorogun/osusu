from models.cycle import CycleStatus


class CycleEngine:

    @staticmethod
    def start_cycle(cycle):

        if cycle.status != CycleStatus.READY:
            raise ValueError(
                "Circle is not ready."
            )

        cycle.lock()
        cycle.activate()

    @staticmethod
    def start_voting(cycle):

        if cycle.status != CycleStatus.ACTIVE:
            raise ValueError(
                "Cycle is not active."
            )

        cycle.status = CycleStatus.VOTING

    @staticmethod
    def start_payout(cycle):

        cycle.status = CycleStatus.PAYOUT

    @staticmethod
    def finish_payout(cycle):

        cycle.complete_payout()

        if cycle.completed_payouts >= cycle.total_positions:
            cycle.complete()
        else:
            cycle.next_period()
            cycle.activate()