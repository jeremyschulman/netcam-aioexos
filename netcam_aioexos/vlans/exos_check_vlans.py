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
from itertools import chain
from collections import defaultdict

# -----------------------------------------------------------------------------
# Public Imports
# -----------------------------------------------------------------------------

from netcad.device import Device
from netcad.checks import CheckResultsCollection, CheckStatus

from netcad.feats.vlans.checks.check_vlans import (
    VlanCheckCollection,
    VlanCheckResult,
    VlanExclusiveListCheck,
    VlanExclusiveListCheckResult,
)

# -----------------------------------------------------------------------------
# Private Imports
# -----------------------------------------------------------------------------

from ..exos_dut import EXOSDeviceUnderTest


# -----------------------------------------------------------------------------
# Exports
# -----------------------------------------------------------------------------


@EXOSDeviceUnderTest.execute_checks.register  # noqa
async def eos_check_vlans(
    self, vlan_checks: VlanCheckCollection
) -> CheckResultsCollection:
    """
    This check executor validates tha the device has the VLANs expected by the
    design.  These checks include validating the VLANs exist as they should in
    the design (for example VLAN-10 is "Printers" and not "VideoSystesms").
    This exector also validates the exclusive list of VLANs to ensure the device
    is not configured with any unexpected VLANs.
    """

    dut: EXOSDeviceUnderTest = self
    device = dut.device
    results = list()

    # -------------------------------------------------------------------------
    # read the active vlan information and produce a map by VLAN-ID
    # -------------------------------------------------------------------------

    cli_vlan_resp = await dut.exos_jrpc.cli("show vlan")
    vlan_data_map = dict()
    for rec in cli_vlan_resp:
        vlan_info = rec["vlanProc"]
        vlan_id = vlan_info["tag"]
        vlan_data_map[vlan_id] = dict(
            vlan_id=vlan_info["tag"],
            name=vlan_info["name1"],
            admin_up=vlan_info["adminState"] == 1,
            active_ports=vlan_info["activePorts"],
        )

    # -------------------------------------------------------------------------
    # we will also need to know about LAG (sharing) ports due to the nature
    # of how EXOS reports the VLAN membership.
    # -------------------------------------------------------------------------

    cli_port_sharing_resp = await dut.exos_jrpc.cli("show port sharing")
    ls_port_map = defaultdict(set)
    for rec in cli_port_sharing_resp:
        if not (port_info := rec.get("ls_ports_show")):
            continue

        ls_master = str(port_info["loadShareMaster"])
        ls_port = str(port_info["port"])
        ls_port_map[ls_master].add(ls_port)

    # -------------------------------------------------------------------------
    # keep track of the set of expectd VLAN-IDs (ints) should we need them for
    # the exclusivity check.
    # -------------------------------------------------------------------------

    expd_vlan_ids = set()

    for check in vlan_checks.checks:
        result = VlanCheckResult(device=device, check=check)

        # The check ID is the VLAN ID in string form.

        vlan_id = int(check.check_id())
        expd_vlan_ids.add(vlan_id)

        # If the VLAN data is missing from the device, then we are done.

        if not (vlan_status := vlan_data_map.get(vlan_id)):
            result.measurement = None
            results.append(result.measure())
            continue

        await _check_one_vlan(
            dut,
            exclusive=vlan_checks.exclusive,
            vlan_status=vlan_status,
            ls_port_map=ls_port_map,
            result=result,
            results=results,
        )

    # if vlan_checks.exclusive:
    #     _check_exclusive(
    #         device=device,
    #         expd_vlan_ids=expd_vlan_ids,
    #         msrd_vlan_ids=msrd_active_vlan_ids,
    #         results=results,
    #     )

    return results


# -----------------------------------------------------------------------------
#
#                            PRIVATE CODE BEGINS
#
# -----------------------------------------------------------------------------


def _check_exclusive(
    device: Device,
    expd_vlan_ids: Set,
    msrd_vlan_ids: Set,
    results: CheckResultsCollection,
):
    """
    This function checks to see if there are any VLANs measured on the device
    that are not in the expected exclusive list.  We do not need to check for
    missing VLANs since expected per-vlan checks have already been performed.
    """

    result = VlanExclusiveListCheckResult(
        device=device,
        check=VlanExclusiveListCheck(expected_results=sorted(expd_vlan_ids)),
        measurement=sorted(msrd_vlan_ids),
    )
    results.append(result.measure())


async def _check_one_vlan(
    dut: EXOSDeviceUnderTest,
    exclusive: bool,
    result: VlanCheckResult,
    vlan_status: dict,
    ls_port_map: dict[str, set],
    results: CheckResultsCollection,
):
    """
    Checks a specific VLAN to ensure that it exists on the device as expected.
    """

    check = result.check
    msrd = result.measurement

    vlan_details = await dut.exos_jrpc.cli(f"show vlan {vlan_status['name']}")
    ports = list()
    for rec in vlan_details:
        if not (vlan_rec := rec.get("vlanProc")):
            continue

        if (port := str(vlan_rec["port"])).startswith("invalid"):
            continue

        ports.append(port)

    msrd.oper_up = bool(vlan_status["active_ports"])
    msrd.name = vlan_status["name"]

    msrd.interfaces = ports
    msrd_ifs_set = set(msrd.interfaces)
    expd_ifs_set = set(check.expected_results.interfaces)

    # -------------------------------------------------------------------------
    # if an expected interface is an SVI, then discard that since EXOS does
    # not report the SVI in the VLAN membership.
    # -------------------------------------------------------------------------

    if virt_if_names := [
        if_name
        for if_name, if_info in dut.device_info["interfaces"].items()
        if if_info["profile_flags"].get("is_virtual", False)
    ]:
        expd_ifs_set -= set(virt_if_names)

    # -------------------------------------------------------------------------
    # if an expected interface is a lag, then we need to find the lag members
    # so that we can expect each of the individual members to be in the
    # measured interfaces.
    # -------------------------------------------------------------------------

    if lag_if_names := [
        if_name
        for if_name, if_info in dut.device_info["interfaces"].items()
        if if_info["profile_flags"].get("is_lag", False)
    ]:
        # remove the lag interface names from the set of expected interfaces
        expd_ifs_set -= set(lag_if_names)

        for lag_member_name in chain(
            [
                lag_intf.name
                for lag_if_name in lag_if_names
                for lag_intf in dut.device.interfaces[
                    lag_if_name
                ].profile.if_lag_members
            ]
        ):
            if lag_member_name in ls_port_map:
                expd_ifs_set -= ls_port_map[lag_member_name]
                expd_ifs_set.add(lag_member_name)

    # -------------------------------------------------------------------------

    if exclusive:
        if missing_interfaces := expd_ifs_set - msrd_ifs_set:
            result.logs.log(
                CheckStatus.FAIL, "interfaces", dict(missing=list(missing_interfaces))
            )

        if extra_interfaces := msrd_ifs_set - expd_ifs_set:
            result.logs.log(
                CheckStatus.FAIL, "interfaces", dict(extra=list(extra_interfaces))
            )

    def on_mismatch(_field, _expd, _msrd):
        if _field == "name":
            # if the VLAN name is not set, then we do not check-validate the
            # configured name.  This was added to support design-unused-vlan1;
            # but could be used for any VLAN.

            if not _expd:
                return CheckStatus.PASS

            result.logs.log(
                CheckStatus.WARN, _field, dict(expected=_expd, measured=_msrd)
            )

            return CheckStatus.PASS

        if _field == "interfaces":
            if exclusive:
                # use the sets for comparison purposes to avoid mismatch
                # due to list order.

                if msrd_ifs_set == expd_ifs_set:
                    return CheckStatus.PASS

            else:
                # if the set of measured interfaces are in the set of expected, and
                # this check is non-exclusive, then pass it.
                if msrd_ifs_set & expd_ifs_set == expd_ifs_set:
                    return CheckStatus.PASS

    results.append(result.measure(on_mismatch=on_mismatch))
