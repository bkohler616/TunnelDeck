"""Run with: python3 -m unittest discover -s tests -v"""
import asyncio
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import types
import unittest
from unittest.mock import Mock, patch


def load_plugin():
    # Decky's runtime modules are unavailable outside the Steam Deck host.
    settings = types.ModuleType("settings")
    settings.SettingsManager = Mock()
    helpers = types.ModuleType("helpers")
    helpers.get_user = lambda: "deck"
    spec = importlib.util.spec_from_file_location(
        "tunneldeck_under_test", Path(__file__).resolve().parents[1] / "main.py"
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"settings": settings, "helpers": helpers}), \
            patch("logging.basicConfig"), patch("logging.getLogger"):
        spec.loader.exec_module(module)
    return module


plugin = load_plugin()


class NmcliEnvironmentTests(unittest.TestCase):
    def test_removes_bundled_path_without_changing_parent(self):
        original = {
            "LD_LIBRARY_PATH": "/tmp/_MEItest",
            "PATH": "/usr/bin",
            "DBUS_SYSTEM_BUS_ADDRESS": "unix:path=/run/dbus/system_bus_socket",
        }
        with patch.dict(os.environ, original, clear=True):
            result = plugin._nmcli_env()
            self.assertEqual(result, {k: v for k, v in original.items()
                                      if k != "LD_LIBRARY_PATH"})
            self.assertEqual(dict(os.environ), original)

    def test_restores_original_library_path(self):
        for original in ("/opt/system-libs", ""):
            with self.subTest(original=original), patch.dict(os.environ, {
                "LD_LIBRARY_PATH": "/tmp/_MEItest:/opt/system-libs",
                "LD_LIBRARY_PATH_ORIG": original,
            }, clear=True):
                self.assertEqual(plugin._nmcli_env(), {"LD_LIBRARY_PATH": original})
                self.assertEqual(os.environ["LD_LIBRARY_PATH_ORIG"], original)

    def test_normal_environment_is_preserved(self):
        with patch.dict(os.environ, {"PATH": "/usr/bin"}, clear=True):
            self.assertEqual(plugin._nmcli_env(), {"PATH": "/usr/bin"})

    def test_all_nmcli_operations_use_system_environment(self):
        output = ("Home:wifi-uuid:802-11-wireless:wlan0\n"
                  "TestVPN:vpn-uuid:vpn:\n")
        instance = plugin.Plugin
        cases = [
            ("show", ()), ("up", ("vpn-uuid",)), ("down", ("vpn-uuid",)),
            ("active_connection", ()), ("disable_ipv6", ()), ("enable_ipv6", ()),
        ]
        for name, args in cases:
            with self.subTest(operation=name), patch.dict(os.environ, {
                "LD_LIBRARY_PATH": "/tmp/_MEItest", "PATH": "/usr/bin",
            }, clear=True), patch.object(plugin.subprocess, "run") as run:
                run.return_value = subprocess.CompletedProcess([], 0, output, "")
                result = asyncio.run(getattr(instance, name)(instance, *args))
                nmcli_calls = [c for c in run.call_args_list if c.args[0][0] == "nmcli"]
                self.assertTrue(nmcli_calls)
                for call in nmcli_calls:
                    self.assertEqual(call.kwargs["env"], {"PATH": "/usr/bin"})
                for call in run.call_args_list:
                    if call.args[0][0] != "nmcli":
                        self.assertNotIn("env", call.kwargs)
                self.assertEqual(os.environ["LD_LIBRARY_PATH"], "/tmp/_MEItest")
                if name == "show":
                    self.assertEqual(result[1]["name"], "TestVPN")
                    self.assertEqual(result[1]["type"], "vpn")
                    self.assertFalse(result[1]["connected"])

    def test_commands_and_output_are_preserved(self):
        instance = plugin.Plugin
        for action in ("up", "down"):
            with self.subTest(action=action), patch.object(plugin.subprocess, "run") as run:
                run.return_value = subprocess.CompletedProcess([], 0, "success", "")
                self.assertEqual(asyncio.run(getattr(instance, action)(instance, "vpn-uuid")), "success")
                self.assertEqual(run.call_args.args[0],
                                 ["nmcli", "connection", action, "vpn-uuid"])


if __name__ == "__main__":
    unittest.main()
