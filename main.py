import subprocess
import logging
from os import path
from settings import SettingsManager
from helpers import get_user
import re

USER = get_user()
HOME_PATH = "/home/" + USER
HOMEBREW_PATH = HOME_PATH + "/homebrew"

logging.basicConfig(filename="/tmp/tunneldeck.log",
                    format="[TunnelDeck] %(asctime)s %(levelname)s %(message)s",
                    filemode="w+",
                    force=True)
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)


def connection_mapper(xn):
    components = re.split(r"\s{2,}", xn)
    return {
        "name": components[0],
        "uuid": components[1],
        "type": components[2],
        "device": components[3],
        "connected": False if components[3] == "--" else True
    }


def get_active_connection():
    result = subprocess.run(["nmcli", "connection", "show", "--active"], text=True, capture_output=True).stdout
    connections = result.splitlines()
    connections.pop(0)
    mapped = map(connection_mapper, connections)
    return next(filter(lambda xn: xn["type"] == 'wifi' or xn["type"] == 'ethernet', mapped), None)

def run_install_script():
    logger.info("Running Install Script")
    subprocess.run(["bash", path.dirname(__file__) + "/extensions/install"], cwd=path.dirname(__file__) + "/extensions")


def run_uninstall_script():
    logger.info("Running Uninstall Script")
    subprocess.run(["bash", path.dirname(__file__) + "/extensions/uninstall"],
                   cwd=path.dirname(__file__) + "/extensions")


class Plugin:

    settings: SettingsManager = SettingsManager("tunneldeck", path.join(HOMEBREW_PATH, "settings"))

    async def _main(self):
        logger.info("Loading OpenVPN setting")
        openvpn_enabled = self.settings.getSetting("openvpn_enabled", False)
        if openvpn_enabled:
            logger.info("OpenVPN enabled: " + "yes" if openvpn_enabled else "no")
            run_install_script()

    # Lists the connections from network manager.
    # If device is -- then it's disconnected.
    async def show(self):
        result = subprocess.run(["nmcli", "connection", "show"], text=True, capture_output=True).stdout
        connections = result.splitlines()
        connections.pop(0)
        mapped = map(connection_mapper, connections)
        return list(mapped)

    # Establishes a connection to a VPN
    async def up(self, uuid):
        logger.info("OPENING connection to: " + uuid)
        result = subprocess.run(["nmcli", "connection", "up", uuid], text=True, capture_output=True).stdout
        return result

    # Closes a connection to a VPN
    async def down(self, uuid):
        logger.info("CLOSING connection to: " + uuid)
        result = subprocess.run(["nmcli", "connection", "down", uuid], text=True, capture_output=True).stdout
        return result

    # Checks if IPV6 is disabled on Wi-Fi
    async def active_connection(self):
        logger.debug("active_connection enter")
        connection = get_active_connection()
        if connection is None:
            logger.debug("active_connection connection is none")
            return None

        logger.debug("active_connection nmcli call")
        result = subprocess.run(["nmcli", "connection", "show", connection["uuid"], "|", "grep", "ipv6.method"],
                                text=True, capture_output=True).stdout
        connection["ipv6_disabled"] = True if "disabled" in result else False

        logger.debug("active_connection nmcli result %s", result)
        return connection

    # Disables IPV6 on currently active connection
    async def disable_ipv6(self):
        connection = get_active_connection()
        if connection is None:
            return True

        logger.info("DISABLING IPV6 for: " + connection["uuid"])
        subprocess.run(["nmcli", "connection", "modify", connection["uuid"], "ipv6.method", "disabled"])
        subprocess.run(["systemctl", "restart", "NetworkManager"])
        return True

    # Enable IPV6 on currently active connection
    async def enable_ipv6(self):
        connection = get_active_connection()
        if connection is None:
            return True

        logger.info("ENABLING IPV6 for: " + connection["uuid"])
        subprocess.run(["nmcli", "connection", "modify", connection["uuid"], "ipv6.method", "auto"])
        subprocess.run(["systemctl", "restart", "NetworkManager"])
        return True

    # Checks if the OpenVPN package is installed
    async def is_openvpn_pacman_installed(self):
        try:
            subprocess.run(["pacman", "-Qi", "networkmanager-openvpn"], check=True)
            return True
        except subprocess.CalledProcessError:
            return False

    # The OpenVPN setting
    async def is_openvpn_enabled(self):
        return self.settings.getSetting("openvpn_enabled", False)

    # Enable OpenVPN
    async def enable_openvpn(self):
        logger.info("Enabling OpenVPN")
        self.settings.setSetting("openvpn_enabled", True)
        run_install_script()
        return True

    # Disable OpenVPN
    async def disable_openvpn(self):
        logger.info("Disabling OpenVPN")
        self.settings.setSetting("openvpn_enabled", False)
        run_uninstall_script()
        return True

    # Collect the current LAN ip
    async def get_priority_lan_ip(self):
        logger.debug("Collecting LAN ip")
        # "ip route get 1.2.3.4 | awk '{print $3; exit}'"
        steam_ip = self.get_steam_ip()
        logger.debug("Collecting LAN ip - got steam IP")
        ip_data = subprocess.run(["ip", "route", "get", steam_ip], text=True, capture_output=True).stdout
        if not ip_data:
            result = {"success": False, "data": "N/A"}
        else:
            result = {"success": True, "data": ip_data.split(" ")[6]}
        logger.debug("LAN ip - sendingRes: %s", result)
        logger.debug("LAN ip - IP_DATA response: %s", ip_data)
        return result

    # Figure out the priority interface name
    async def get_priority_interface_name(self):
        logger.debug("Collecting priority interface")
        steam_ip = self.get_steam_ip()
        logger.debug("Collecting priority interface - got steam ip")
        ip_data = subprocess.run(["ip", "route", "get", steam_ip], text=True, capture_output=True).stdout
        logger.debug("Priority interface response %s", ip_data)
        result = re.search(r"(?<=(dev ))(\S+)", ip_data)
        logger.debug("Priority interface response pt2 %s", result)
        if not result:
            result = {"success": False, "data": "N/A"}
        else:
            result = {"success": True, "data": result[0]}

        logger.debug("Priority interface: %s", result)
        return result

    # Can we ping steampowered.com
    async def is_internet_available(self):
        return await self.can_ping_address("steampowered.com")

    # Can we ping the priority interface's gateway or DNS.
    async def is_gateway_available(self):
        logger.debug("is_gateway_available enter")
        connection_data = await self.active_connection()
        logger.debug("is_gateway_available connection_data %s", connection_data)
        interface_name = await self.get_priority_interface_name()
        logger.debug("is_gateway_available interface_name %s", interface_name)
        if connection_data is None or not interface_name['success']:
            logger.debug("is_gateway_available instant drop out due to no response or bad interface")
            return False

        nmcli_res = subprocess.run(["nmcli", "-f", "all", "-t", "device", "show", interface_name[data]], text=True, capture_output=True).stdout.splitlines()
        logger.debug("is_gateway_available nmcli_res %s", nmcli_res)

        final_res = None
        if connection_data["ipv6_disabled"]:
            for e in nmcli_res:
                if "IP6.GATEWAY" in e and e.split(":")[1]:
                    final_res = e.split(":")[1]
                    break
                if "IP6.DNS[1]" in e and e.split(":")[1]:
                    final_res = e.split(":")[1]
                    break
        else:
            for e in nmcli_res:
                if "IP4.GATEWAY" in e and e.split(":")[1]:
                    final_res = e.split(":")[1]
                    logger.debug("is_gateway_available ip4.gateway found %s", final_res)
                    break
                if "IP4.DNS[1]" in e and e.split(":")[1]:
                    final_res = e.split(":")[1]
                    logger.debug("is_gateway_available ip4.dns found %s", final_res)
                    break
        if final_res is None:
            logger.debug("is_gateway_available did not find address")
            return False
        return await self.can_ping_address(final_res)

    async def can_ping_address(self, address):
        logger.debug("Pinging %s", address)
        ping_data = subprocess.run(["ping", "-c", "1", address], text=True, capture_output=True)
        logger.debug("Pinging %s finish", address)
        return not bool(ping_data.stderr)

    async def get_steam_ip(self):
        logger.debug("Collecting steam's IP")
        getent_data = subprocess.run(["getent", "ahosts", "steampowered.com"], text=True, capture_output=True)
        ip = ""
        logger.debug("Collecting steam's IP - getting steam ip %s", getent_data)
        if getent_data.stderr:
            return ip
        stdout_lines = getent_data.stdout.splitlines()
        for e in stdout_lines:
            if "STREAM" in e:
                res = e.split(" ")[0]
                logger.debug("steam's ip is %s", res)
                return res

    # Clean-up on aisle 5
    async def _unload(self):
        subprocess.run(["bash", path.dirname(__file__) + "/extensions/uninstall"],
                       cwd=path.dirname(__file__) + "/extensions")
        pass
