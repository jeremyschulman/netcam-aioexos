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
#

# -----------------------------------------------------------------------------
# System Imports
# -----------------------------------------------------------------------------

from typing import Set

# -----------------------------------------------------------------------------
# Public Imports
# -----------------------------------------------------------------------------
from netcad.checks import CheckResultsCollection, CheckStatus

from netcad.feats.topology.checks.check_transceivers import (
    TransceiverCheckCollection,
    TransceiverCheckResult,
    TransceiverExclusiveListCheck,
    TransceiverExclusiveListCheckResult,
)
from netcad.feats.topology import transceiver_model_matches, transceiver_type_matches
from netcad.device import Device, DeviceInterface

# -----------------------------------------------------------------------------
# Private Imports
# -----------------------------------------------------------------------------

from netcam_aioexos.exos_dut import EXOSDeviceUnderTest

# -----------------------------------------------------------------------------
# Exports
# -----------------------------------------------------------------------------

__all__ = ["exos_check_transceivers"]


# -----------------------------------------------------------------------------
#
#                                 CODE BEGINS
#
# -----------------------------------------------------------------------------


@EXOSDeviceUnderTest.execute_checks.register  # noqa
async def exos_check_transceivers(
    dut, check_collection: TransceiverCheckCollection
) -> CheckResultsCollection:
    """
    This method is imported into the ESO DUT class definition to support
    checking the status of the transceivers.

    Notes
    -----
    On EOS platforms, the XCVR inventory is stored as port _numbers-strings_ and
    not as the interface name.  For example, "Interface54/1" is represented in
    the EOS inventor as "54".
    """

    dut: EXOSDeviceUnderTest
    device = dut.device

    # retrieve the port transceiver information and create a mapping by
    # interface port value.

    cli_xcvrinv_resp_data = await dut.exos_jrpc.cli("show port transceiver information")
    dev_xcvr_ifstatus = {}
    for xcvr_rec in cli_xcvrinv_resp_data:
        data = xcvr_rec["show_ports_transceiver"]
        dev_xcvr_ifstatus[str(data["port"])] = data

    # keep a set of the interface port numbers defined in the test cases so that
    # we can match that against the exclusive list vs. the transceivers in the
    # inventory.

    if_port_numbers = set()
    results = list()

    # first run through each of the per interface test cases ensuring that the
    # expected transceiver type and model are present.  While doing this keep
    # track of the interfaces port-numbers so that we can compare them to the
    # eclusive list.

    rsvd_ports_set = set()

    for check in check_collection.checks:
        result = TransceiverCheckResult(device=device, check=check)

        if_name = check.check_id()
        dev_iface: DeviceInterface = device.interfaces[if_name]
        if_xcvr = dev_xcvr_ifstatus[if_name]

        if dev_iface.profile.is_reserved:
            result.status = CheckStatus.INFO
            result.logs.log(
                result.status,
                "reserved",
                dict(message="interface is in reserved state", status=if_xcvr),
            )
            results.append(result.measure())
            rsvd_ports_set.add(if_name)
            continue

        if_port_numbers.add(if_name)

        _check_one_interface(if_xcvr, result=result, results=results)

    # next add the test coverage for the exclusive list.
    # only include interfaces that have a serial-number to avoid false
    # failures

    dev_inv_ifxvrs = dict(
        filter(lambda _iface: _iface[1].get("slNumber"), dev_xcvr_ifstatus.items())
    )

    if check_collection.exclusive:
        _check_exclusive_list(
            device=device,
            expd_ports=if_port_numbers,
            msrd_ports=dev_inv_ifxvrs,
            rsvd_ports=rsvd_ports_set,
            results=results,
        )

    return results


# -----------------------------------------------------------------------------
#
#                            PRIVATE CODE BEGINS
#
# -----------------------------------------------------------------------------


def _check_exclusive_list(
    device: Device,
    expd_ports,
    msrd_ports,
    rsvd_ports: Set,
    results: CheckResultsCollection,
):
    """
    Check to ensure that the list of transceivers found on the device matches the exclusive list.
    This check helps to find "unused" optics; or report them so that a Designer can account for them
    in the design-notepad.
    """

    # remove the reserved ports form the used list so that we do not consider
    # them as part of the exclusive list testing.

    check = TransceiverExclusiveListCheck(expected_results=expd_ports - rsvd_ports)

    # remove the reserved ports form the used list so that we do not consider
    # them as part of the exclusive list testing.

    used_msrd_ports = set(msrd_ports) - rsvd_ports

    result = TransceiverExclusiveListCheckResult(
        device=device, check=check, measurement=used_msrd_ports
    )

    results.append(result.measure(on_extra=CheckStatus.INFO))


def _check_one_interface(
    if_xcvr: dict,
    result: TransceiverCheckResult,
    results: CheckResultsCollection,
):
    """
    This function validates that a specific interface is using the specific
    transceiver as defined in the design.
    """

    # if there is no xcvr part for this interface, then the transceiver does
    # not exist.

    if not (part_number := if_xcvr.get("partNumber")):
        result.measurement = None
        results.append(result.measure())
        return

    msrd = result.measurement
    msrd.model = part_number
    msrd.type = if_xcvr["mediaType"].split()[0]

    def on_mismatch(_field, _expd, _msrd):
        match _field:
            case "model":
                is_ok = transceiver_model_matches(
                    expected_model=_expd, given_mdoel=_msrd
                )
            case "type":
                is_ok = transceiver_type_matches(expected_type=_expd, given_type=_msrd)
            case _:
                is_ok = False

        return CheckStatus.PASS if is_ok else CheckStatus.FAIL

    results.append(result.measure(on_mismatch=on_mismatch))
