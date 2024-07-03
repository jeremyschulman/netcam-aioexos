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
# System Impors
# -----------------------------------------------------------------------------
import asyncio

# -----------------------------------------------------------------------------
# Public Impors
# -----------------------------------------------------------------------------

from netcad.checks import CheckResultsCollection, CheckResult, CheckStatus
from netcad.feats.topology.checks.check_device_info import (
    DeviceInformationCheckCollection,
    DeviceInformationCheckResult,
)

# -----------------------------------------------------------------------------
# Private Improts
# -----------------------------------------------------------------------------

from netcam_aioexos.exos_dut import EXOSDeviceUnderTest

# -----------------------------------------------------------------------------
# Exports (None)
# -----------------------------------------------------------------------------

__all__ = ()

# -----------------------------------------------------------------------------
#
#                                 CODE BEGINS
#
# -----------------------------------------------------------------------------


@EXOSDeviceUnderTest.execute_checks.register  # noqa
async def exos_check_device_info(
    self, device_checks: DeviceInformationCheckCollection
) -> CheckResultsCollection:
    """
    The check executor to validate the device information.  Presently this
    function validates the product-model value.  It also captures the results
    of the 'show version' into a check-inforamation.
    """
    dut: EXOSDeviceUnderTest = self

    res = await asyncio.gather(
        # find the active operating system image version
        self.exos_restc.get(
            "/openconfig-platform:components/component=operating_system-1/state"
        ),
        self.exos_restc.get(
            "/openconfig-platform:components/component=operating_system-2/state"
        ),
        # get product model
        self.exos_restc.get(
            "/openconfig-platform:components/component=linecard-1/state"
        ),
        # get hostname
        self.exos_restc.get("/openconfig-system:system/config"),
    )

    os1, os2, lc1, system = [next(iter(r.json().values())) for r in res]
    active_os = next((os for os in (os1, os2) if os["oper-status"] == "ACTIVE"))
    sw_ver = active_os["software-version"]
    product_model = lc1["description"]
    serial_number = lc1["serial-no"]
    part_number = lc1["part-no"]
    hostname = system["hostname"]

    # store the results.
    check = device_checks.checks[0]
    has_product_model = product_model

    return [
        DeviceInformationCheckResult(
            device=dut.device,
            check=check,
            measurement=DeviceInformationCheckResult.Measurement(
                product_model=has_product_model
            ),
        ),
        # add an informational block with the device details.
        CheckResult(
            device=dut.device,
            check=check,
            status=CheckStatus.INFO,
            measurement=dict(
                hostname=hostname,
                serial_number=serial_number,
                part_number=part_number,
                software_version=sw_ver,
            ),
        ),
    ]
