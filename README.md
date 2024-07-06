# NetCAM asyncio for Extreme EXOS

This package provides the NetCAM feature checks:

   * topology
   * vlans

The `netcad.toml` file would contain a configuration block similar to the
following.

```toml
[[netcam.plugins]]

    name = "Extreme EXOS"
    supports = ["exos"]
    package = "netcam_aioexos"

    features = [
        "netcam_aioexos.topology",
        "netcam_aioexos.vlans",
    ]

    # bumping timeout to 5 min for slow devices
    config.timeout = 300

    # read-only credentials
    config.env.read.username = "$NETWORK_USERNAME"
    config.env.read.password = "$NETWORK_PASSWORD"

    # admin credentials used for config-mgmt
    config.env.admin.username = "$NETWORK_RW_USERNAME"
    config.env.admin.password = "$NETWORK_RW_PASSWORD"
```
