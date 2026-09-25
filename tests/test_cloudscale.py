import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import cloudscale


def instance(i, state="InService", protected=True):
    return {"InstanceId": i, "LifecycleState": state, "ProtectedFromScaleIn": protected}


class Fleet:
    def __init__(self, desired=0, instances=()):
        self.group = {"DesiredCapacity": desired, "MaxSize": 4, "Instances": list(instances)}
        self.calls = []

    def describe_auto_scaling_groups(self, **kwargs):
        return {"AutoScalingGroups": [copy.deepcopy(self.group)]}

    def set_desired_capacity(self, **kwargs):
        self.calls.append(("resize", kwargs["DesiredCapacity"]))
        self.group["DesiredCapacity"] = kwargs["DesiredCapacity"]

    def terminate_instance_in_auto_scaling_group(self, **kwargs):
        assert kwargs["ShouldDecrementDesiredCapacity"]
        self.calls.append(("retire", kwargs["InstanceId"]))
        self.group["Instances"] = [i for i in self.group["Instances"] if i["InstanceId"] != kwargs["InstanceId"]]
        self.group["DesiredCapacity"] -= 1


class CloudScaleTests(unittest.TestCase):
    def test_zero_to_parallel_and_idempotent_notifications(self):
        fleet = Fleet()
        jobs = [{"user": u, "status": "queued"} for u in ["alice", "ALICE", "alice", "bob"]]
        with patch.object(cloudscale.cloudqueue, "active", return_value=jobs):
            self.assertEqual(cloudscale.reconcile(fleet, "test")["desired"], 2)
            cloudscale.reconcile(fleet, "test")
        self.assertEqual(fleet.calls, [("resize", 2)])

    def test_bursts_respect_fleet_cap(self):
        self.assertEqual(cloudscale.capacity([{"user": str(i)} for i in range(30)], [], 4), 4)

    def test_no_jobs_does_not_kill_boot_or_final_publication(self):
        fleet = Fleet(2, [instance("boot", "Pending:Wait"), instance("finishing")])
        with patch.object(cloudscale.cloudqueue, "active", return_value=[]):
            self.assertEqual(cloudscale.reconcile(fleet, "test")["desired"], 2)
        self.assertEqual(fleet.calls, [])

    def test_last_worker_retires_without_replacement_and_duplicate_is_safe(self):
        fleet = Fleet(1, [instance("last")])
        with patch.object(cloudscale.cloudqueue, "active", return_value=[]):
            self.assertEqual(cloudscale.reconcile(fleet, "test", retire="last")["desired"], 0)
            cloudscale.reconcile(fleet, "test", retire="last")
        self.assertEqual(fleet.calls, [("retire", "last")])

    def test_retirement_wakes_capacity_for_next_users_job(self):
        fleet = Fleet(1, [instance("used")])
        with patch.object(cloudscale.cloudqueue, "active", return_value=[{"user": "alice", "status": "queued"}]):
            cloudscale.reconcile(fleet, "test", retire="used")
        self.assertEqual(fleet.calls, [("retire", "used"), ("resize", 1)])

    def test_callback_cannot_terminate_another_fleets_instance(self):
        fleet = Fleet()
        with patch.object(cloudscale.cloudqueue, "active", return_value=[]):
            cloudscale.reconcile(fleet, "test", retire="someone-elses-instance")
        self.assertEqual(fleet.calls, [])

    def test_expired_attempt_is_failed_before_capacity_is_calculated(self):
        fleet = Fleet()
        with patch.object(cloudscale.cloudqueue, "active", side_effect=[
                [{"id": "lost", "user": "alice", "status": "running", "lease_until": 1}], []]), \
                patch.object(cloudscale.cloudqueue, "expire") as expire:
            self.assertEqual(cloudscale.reconcile(fleet, "test")["desired"], 0)
            expire.assert_called_once_with("lost")

    def test_disabled_dispatch_still_retires_used_workers(self):
        fleet = Fleet(1, [instance("last")])
        with patch.object(cloudscale.cloudqueue, "active") as active:
            self.assertEqual(cloudscale.reconcile(fleet, "test", "last", enabled=False)["desired"], 0)
            active.assert_not_called()


if __name__ == "__main__": unittest.main()
