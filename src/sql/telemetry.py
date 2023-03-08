from ploomber_core.telemetry.telemetry import Telemetry

try:
    from importlib.metadata import version
except ModuleNotFoundError:
    from importlib_metadata import version


telemetry = Telemetry(
    api_key="phc",
    package_name="jupysql",
    version=version("jupysql"),
)
