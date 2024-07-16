#  Copyright 2021 Jeremy Schulman
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

# -----------------------------------------------------------------------------
# System Imports
# -----------------------------------------------------------------------------

from typing import Set

# -----------------------------------------------------------------------------
# Public Imports
# -----------------------------------------------------------------------------

from netcad.device import Device, DeviceInterface
from netcad.checks import CheckResultsCollection, CheckStatus

from netcad.feats.topology.checks.check_interfaces import (
    InterfaceCheckCollection,
    InterfaceExclusiveListCheck,
    InterfaceExclusiveListCheckResult,
    InterfaceCheck,
    InterfaceCheckResult,
    InterfaceCheckMeasurement,
)

# -----------------------------------------------------------------------------
# Private Imports
# -----------------------------------------------------------------------------

from ..exos_dut import EXOSDeviceUnderTest


# -----------------------------------------------------------------------------
#
#                                 CODE BEGINS
#
# -----------------------------------------------------------------------------


@EXOSDeviceUnderTest.execute_checks.register  # noqa
async def exos_check_interfaces(
    self, collection: InterfaceCheckCollection
) -> CheckResultsCollection:
    """
    This async generator is responsible for implementing the "interfaces" test
    cases for Extreme EXOS devices.

    Notes
    ------
    This function is **IMPORTED** directly into the DUT class so that these
    testcase files can be separated.

    Parameters
    ----------
    self: <!LEAVE UNHINTED!>
        The DUT instance for the EOS device

    collection: InterfaceCheckCollection
        The testcases instance that contains the specific testing details.

    Yields
    ------
    TestCasePass, TestCaseFailed
    """

    dut: EXOSDeviceUnderTest = self
    device = dut.device
    results = list()

    # -------------------------------------------------------------------------
    # read the ports data from EXOS to get information about the front panel
    # ports.  Note that we've discovered that the "show ports" does not always
    # result in all the ports.  So we use "show port information" to get the
    # complete list of all ports, and then find any missing ports.
    # -------------------------------------------------------------------------

    cli_sh_ports_info = await dut.exos_jrpc.cli("show ports information")
    cli_sh_ports = await dut.exos_jrpc.cli("show ports")

    ports_info_found = set(
        str(if_data["port"])
        for rec in cli_sh_ports_info
        if (if_data := rec.get("show_ports_info"))
    )

    ports_data_found = set(
        str(if_data["port"])
        for rec in cli_sh_ports
        if (if_data := rec.get("show_ports_info_detail"))
    )

    if missing_interfaces := ports_info_found - ports_data_found:
        for if_name in missing_interfaces:
            cli_sh_port = await dut.exos_jrpc.cli(f"show ports {if_name}")
            cli_sh_ports.extend(cli_sh_port)

    dev_if_msrds = dict()
    for if_rec in cli_sh_ports:
        if not (if_msrd_data := if_rec.get("show_ports_info_detail")):
            continue

        # need to filter out the "not present" (NP) interface ports.  This is
        # represented by "linkState (2)"

        if if_msrd_data["linkState"] == 2:
            continue

        if_name = str(if_msrd_data["port"])
        dev_if_msrds[if_name] = if_msrd_data

    # -------------------------------------------------------------------------
    # read the VLAN information to find SVIs.  That is, VLANs that have IP
    # address configured on them.  The Mgmt port will be included in this
    # output.
    # -------------------------------------------------------------------------

    cli_sh_vlans = await dut.exos_jrpc.cli("show vlan")
    for vlan_rec in cli_sh_vlans:
        if not (vlan_msrd_data := vlan_rec.get("vlanProc")):
            continue

        # if the VLAN does not have an IP address configured, then skip it.
        if not vlan_msrd_data["ipStatus"]:
            continue

        if_name = vlan_msrd_data["name1"]
        dev_if_msrds[if_name] = vlan_msrd_data

    # -------------------------------------------------------------------------
    # Check each interface for health checks
    # -------------------------------------------------------------------------

    for check in collection.checks:
        if_name = check.check_id()

        if if_name == "Mgmt" and if_name not in dev_if_msrds:
            await _check_mgmt_interface(
                dut,
                device=device,
                check=check,
                results=results,
            )
            dev_if_msrds[if_name] = True
            continue

        if if_name.startswith("lag"):
            await _check_one_lag_interface(
                dut,
                device=device,
                check=check,
                results=results,
            )
            dev_if_msrds[if_name] = True
            continue

        _check_one_interface(
            device=device,
            check=check,
            if_msrd=dev_if_msrds.get(if_name),
            results=results,
        )

    # -------------------------------------------------------------------------
    # Check for the exclusive set of interfaces expected vs actual.
    # -------------------------------------------------------------------------

    if collection.exclusive:
        _check_exclusive_interfaces_list(
            device=device,
            expd_interfaces=set(check.check_id() for check in collection.checks),
            msrd_interfaces=dev_if_msrds,
            results=results,
        )

    return results


# -----------------------------------------------------------------------------
#
#                       PRIVATE CODE BEGINS
#
# -----------------------------------------------------------------------------


def _check_exclusive_interfaces_list(
    device: Device,
    expd_interfaces: Set[str],
    msrd_interfaces: Set[str],
    results: CheckResultsCollection,
):
    """
    This check validates the exclusive list of interfaces found on the device
    against the expected list in the design.
    """

    def sort_key(i):
        return DeviceInterface(i, interfaces=device.interfaces)

    check = InterfaceExclusiveListCheck(
        expected_results=sorted(expd_interfaces, key=sort_key)
    )

    result = InterfaceExclusiveListCheckResult(
        device=device, check=check, measurement=sorted(msrd_interfaces, key=sort_key)
    )

    results.append(result.measure(sort_key=sort_key))


class EXosInterfaceMeasurement(InterfaceCheckMeasurement):
    """
    This dataclass is used to store the values as retrieved from the EOS device
    into a set of attributes that align to the test-case.
    """

    @classmethod
    def from_cli(cls, if_data: dict):
        """returns an EOS specific measurement mapping the CLI object fields"""
        desc = (
            if_data.get("descriptionString") or if_data.get("displayString", "") or ""
        )

        return cls(
            # a port is used if admin enabled or there is a description
            used=if_data["adminState"] == 1,
            # a port is Up if the linkState is 1 or there is an IP address (SVI)
            oper_up=if_data["linkState"] == 1 or if_data.get("ipStatus", 0),
            desc=desc,
            speed=if_data.get("portSpeed", 0),
        )


def _check_one_interface(
    device: Device,
    check: InterfaceCheck,
    if_msrd: dict,
    results: CheckResultsCollection,
):
    """
    Validates a specific physical interface against the expectations in the
    design.
    """
    if_name = check.check_id()
    result = InterfaceCheckResult(device=device, check=check)

    # if the interface does not exist, then no further checking.

    if not if_msrd:
        result.measurement = None
        results.append(result.measure())
        return

    # transform the CLI data into a measurment instance for consistent
    # comparison with the expected values.  The speed is encoded as a number.
    # Not sure what the mapping is.  We know 4=10Gbps.  Will fill in this match
    # table as we learn more.

    measurement = EXosInterfaceMeasurement.from_cli(if_msrd)
    match measurement.speed:
        case 1:
            measurement.speed = 10
        case 2:
            measurement.speed = 100
        case 3:
            measurement.speed = 1_000
        case 4:
            measurement.speed = 10_000
        case _:
            if if_name == "Mgmt":
                measurement.speed = 1_000

    if_flags = check.check_params.interface_flags or {}
    is_reserved = if_flags.get("is_reserved", False)

    # -------------------------------------------------------------------------
    # If the interface is marked as reserved, then report the current state in
    # an INFO report and done with this test-case.
    # -------------------------------------------------------------------------

    if is_reserved:
        result.status = CheckStatus.INFO
        result.logs.info("reserved", measurement.dict())
        results.append(result.measure())
        return results

    # override the expected condition if there is a forced unused on a port
    if is_forced_unused := if_flags.get("is_forced_unused"):
        check.expected_results.used = False

    # -------------------------------------------------------------------------
    # Check the 'used' status.  Then if the interface is not being used, then no
    # more checks are required.
    # -------------------------------------------------------------------------

    result.measurement = measurement

    def on_mismatch(_field, _expected, _measured) -> CheckStatus:
        # if the field is description, then it is a warning, and not a failure.
        if _field == "desc":
            # if the design is meant to force a shutdown on the port, then we
            # really do want to surface the description error.

            if is_forced_unused:
                return CheckStatus.FAIL

            # otherwise, the description mismatch is just a warning.
            return CheckStatus.WARN

        # if the speed is mismatched because the port is down, then this is not
        # a failure.
        if _field == "speed" and measurement.oper_up is False:
            return CheckStatus.SKIP

    results.append(result.measure(on_mismatch=on_mismatch))
    return


async def _check_one_lag_interface(
    dut: EXOSDeviceUnderTest,
    device: Device,
    check: InterfaceCheck,
    results: CheckResultsCollection,
):
    if_name = check.check_id()
    lag_id = if_name.split("lag")[-1]

    cli_rsp = await dut.exos_jrpc.cli(f"show lacp lag {lag_id}")

    result = InterfaceCheckResult(device=device, check=check)
    lacp_cfg = cli_rsp[0]["lacpLagCfg"]
    msrd = result.measurement
    msrd.desc = check.expected_results.desc  # don't care about the description
    msrd.oper_up = lacp_cfg["up"] == 1
    msrd.used = lacp_cfg["enable"] == 1
    results.append(result.measure())

    return


async def _check_mgmt_interface(
    dut: EXOSDeviceUnderTest,
    device: Device,
    check: InterfaceCheck,
    results: CheckResultsCollection,
):
    cli_rsp = await dut.exos_jrpc.cli("show mgmt")
    result = InterfaceCheckResult(device=device, check=check)
    mgmt_data = cli_rsp[0]["vlanProc"]
    msrd = result.measurement
    msrd.oper_up = mgmt_data["linkState"] == 1
    msrd.used = (mgmt_data["adminState"] == 1) and (mgmt_data["ipAddress"] != "0.0.0.0")
    results.append(result.measure())
    return
