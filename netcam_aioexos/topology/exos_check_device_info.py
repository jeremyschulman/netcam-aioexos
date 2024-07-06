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
    This function is used to collect device information from the Extreme EXOS.
    The primary check is the product-model.  Additional information is
    collected and returned as an informational check. This includes the
    hostname, serial number, part number, and software version.
    """
    dut: EXOSDeviceUnderTest = self

    res = await asyncio.gather(
        self.exos_restc.get("/openconfig-platform:components"),
        # get product model
        self.exos_restc.get(
            "/openconfig-platform:components/component=linecard-1/state"
        ),
        # get hostname information
        self.exos_restc.get("/openconfig-system:system/config"),
    )

    # this bit gets to the actual data of each of the openconfig request
    # responses. ick.
    comps, lc1, system = [next(iter(r.json().values())) for r in res]

    # find the software versions; which is located in one of the
    # "operating_system" response values.

    os_comps = [
        c for c in comps["component"] if c["name"].startswith("operating_system")
    ]
    os_versions = {c["state"]["id"]: c["state"]["software-version"] for c in os_comps}

    # pull out other information that we need and want to log for informational
    # purposes.

    product_model = lc1["description"]
    serial_number = lc1["serial-no"]
    part_number = lc1["part-no"]
    hostname = system["hostname"]

    # store the results.
    check = device_checks.checks[0]
    has_product_model = product_model

    return [
        # product model check
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
                software_version=os_versions,
            ),
        ),
    ]
