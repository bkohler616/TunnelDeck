import subprocess
import pprint
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
    result = subprocess.run(["nmcli", "connection", "show", "--active"],
                            text=True, capture_output=True, timeout=15).stdout
    connections = result.splitlines()
    connections.pop(0)
    mapped = map(connection_mapper, connections)
    return next(filter(lambda xn: xn["type"] == 'wifi' or xn["type"] == 'ethernet', mapped), None)


def run_install_script():
    logger.info("Running Install Script")
    subprocess.run(["bash", path.dirname(__file__) + "/extensions/install"],
                   cwd=path.dirname(__file__) + "/extensions", timeout=200)


def run_uninstall_script():
    logger.info("Running Uninstall Script")
    subprocess.run(["bash", path.dirname(__file__) + "/extensions/uninstall"],
                   cwd=path.dirname(__file__) + "/extensions", timeout=200)


pp = pprint.PrettyPrinter(indent=2, sort_dicts=False)


def log_pretty(obj):
    pretty_out = f"{pp.pformat(obj)}"

    return f'{pretty_out}\n'


class Plugin:
    settings: SettingsManager = SettingsManager("tunneldeck", path.join(HOMEBREW_PATH, "settings"))
    current_data = {
        "steam_ip": "",
        "active_connection": {
            "name": "",
            "uuid": "",
            "type": "",
            "device": "",
            "connected": False,
            "ipv6_disabled": False,
        },
        "priority_lan_ip": {
            "success": False,
            "data": "N/A"
        },
        "priority_interface_name": {
            "success": False,
            "data": "N/A"
        },
        "ping_results": [],
    }

    # region Plugin entry / exit
    async def _main(self):
        logger.info("Loading OpenVPN setting")
        await self.reset_cached_data(self)
        openvpn_enabled = self.settings.getSetting("openvpn_enabled", False)
        if openvpn_enabled:
            logger.info("OpenVPN enabled: " + "yes" if openvpn_enabled else "no")
            run_install_script()

    async def _unload(self):
        subprocess.run(["bash", path.dirname(__file__) + "/extensions/uninstall"],
                       cwd=path.dirname(__file__) + "/extensions", timeout=200)
        pass

    # endregion

    # region Network info collectors
    # Reset all cached network information.
    async def reset_cached_data(self):
        self.current_data = {
            "steam_ip": "",
            "active_connection": {
                "name": "",
                "uuid": "",
                "type": "",
                "device": "",
                "connected": False,
                "ipv6_disabled": False,
            },
            "priority_lan_ip": {
                "success": False,
                "data": "N/A"
            },
            "priority_interface_name": {
                "success": False,
                "data": "N/A"
            },
            "ping_results": [],
        }
        return True
    # Collect the IP address of steam
    async def get_steam_ip(self):
        logger.debug("Collecting steam's IP")
        getent_data = subprocess.run(["getent", "ahosts", "steampowered.com"],
                                     text=True, capture_output=True, timeout=15)
        logger.debug(f"Collecting steam's IP - getting steam ip {getent_data}")
        if getent_data.stderr:
            return
        stdout_lines = getent_data.stdout.splitlines()
        for e in stdout_lines:
            if "STREAM" in e:
                res = e.split(" ")[0]
                logger.debug(f"steam's ip is {log_pretty(res)}")
                self.current_data["steam_ip"] = res
                return res
    # Collect the current LAN ip
    async def get_priority_lan_ip(self):
        logger.debug("Collecting LAN ip")
        # "ip route get 1.2.3.4 | awk '{print $3; exit}'"

        steam_ip = self.current_data["steam_ip"]
        if steam_ip is "":
            steam_ip = await self.get_steam_ip(self)

        logger.debug("Collecting LAN ip - got steam IP")
        ip_data = subprocess.run(["ip", "route", "get", steam_ip], text=True, capture_output=True, timeout=15).stdout

        if not ip_data:
            result = {"success": False, "data": "N/A"}
        else:
            regex_result = re.search(r"(?<=(src ))(\S+)", ip_data)
            result = {"success": bool(regex_result[0]), "data": regex_result[0]}

        logger.debug("Collecting LAN ip - sendingRes: %s", result)
        logger.debug("Collecting LAN ip - IP_DATA response: %s", ip_data)
        self.current_data["priority_lan_ip"] = result
        return result
    # Collect the priority interface name based on the steam IP
    async def get_priority_interface_name(self):
        logger.debug("Collecting priority interface")

        steam_ip = self.current_data["steam_ip"]
        if steam_ip is "":
            steam_ip = await self.get_steam_ip(self)

        logger.debug("Collecting priority interface - got steam ip")
        ip_data = subprocess.run(["ip", "route", "get", steam_ip], text=True, capture_output=True, timeout=15).stdout

        logger.debug("Priority interface response %s", ip_data)
        result = re.search(r"(?<=(dev ))(\S+)", ip_data)

        logger.debug("Priority interface response pt2 %s", result)
        if not result:
            result = {"success": False, "data": "N/A"}
        else:
            result = {"success": True, "data": result[0]}

        logger.debug("Priority interface: %s", result)
        self.current_data["priority_interface_name"] = result
        return result

    # Collect detailed networking information based on the prioritized interface name.
    async def get_prioritized_network_info(self):
        logger.debug("get_prioritized_network_info enter")

        connection_data = self.current_data['active_connection']
        if connection_data['connected'] is False or connection_data['name'] is "":
            connection_data = await self.active_connection(self)  # I swear to god if adding self works I'mma lose it.
        logger.debug("get_prioritized_network_info connection_data %s", connection_data)

        interface_name = self.current_data["priority_interface_name"]
        if not interface_name['success']:
            interface_name = await self.get_priority_interface_name(self)
        logger.debug("get_prioritized_network_info interface_name %s", interface_name)

        if connection_data is None or not interface_name['success']:
            logger.debug("get_prioritized_network_info instant drop out due to no response or bad interface")
            return False

        nmcli_res = subprocess.run(["nmcli", "-f", "all", "-t", "device", "show", interface_name['data']], text=True,
                                   capture_output=True, timeout=15).stdout.splitlines()
        logger.debug("get_prioritized_network_info nmcli_res %s", nmcli_res)

        ping_res = []
        for ping in self.current_data['ping_results']:
            str_builder = f'Pinging {ping["address"]}'
            str_builder = f'{str_builder} {"succeeded" if ping["could_ping"] else "failed"}'
            if ping["could_ping"]:
                str_builder = f'{str_builder} in {ping["ping_time"]}'
            ping_res.append(str_builder)

        final_res = '\n'.join(ping_res)
        for e in nmcli_res:
            if "GENERAL.DEVICE" in e and e.split(":")[1]:
                final_res = f"{final_res}\nDEVICE: {e.split(':')[1]}"
            if "GENERAL.TYPE" in e and e.split(":")[1]:
                final_res = f"{final_res}\nTYPE: {e.split(':')[1]}"
            if "GENERAL.STATE" in e and e.split(":")[1]:
                final_res = f"{final_res}\nSTATE: {e.split(':')[1]}"
            if "GENERAL.REASON" in e and e.split(":")[1]:
                final_res = f"{final_res}\nREASON: {e.split(':')[1]}"
            if "GENERAL.IP4-CONNECTIVITY" in e and e.split(":")[1]:
                final_res = f"{final_res}\nIP4-CONN: {e.split(':')[1]}"
            if "GENERAL.IP6-CONNECTIVITY" in e and e.split(":")[1]:
                final_res = f"{final_res}\nIP6-CONN: {e.split(':')[1]}"
            if "GENERAL.IP-IFACE" in e and e.split(":")[1]:
                final_res = f"{final_res}\nIP-IFACE: {e.split(':')[1]}"
            if "GENERAL.CONNECTION" in e and e.split(":")[1]:
                final_res = f"{final_res}\nCONNECTION: {e.split(':')[1]}"
            if "GENERAL.METERED" in e and e.split(":")[1]:
                final_res = f"{final_res}\nMETERED: {e.split(':')[1]}"
            if "CAPABILITIES.SPEED" in e and e.split(":")[1]:
                final_res = f"{final_res}\nSPEED: {e.split(':')[1]}"

            if ".ADDRESS" in e and e.split(":")[1]:
                item = e.split(':')
                final_res = f"{final_res}\n{item.pop(0)}: {''.join(item)}"
            if ".GATEWAY" in e and e.split(":")[1]:
                item = e.split(':')
                item.pop(0)
                final_res = f"{final_res}\n{e.split(':')[0]}: {''.join(item)}"
            if ".DNS" in e and e.split(":")[1]:
                item = e.split(':')
                item.pop(0)
                final_res = f"{final_res}\n{e.split(':')[0]}: {''.join(item)}"

        if final_res is '':
            logger.debug("get_prioritized_network_info could not get info")
            return 'N/A'
        return final_res

    # Can we ping steampowered.com
    async def is_internet_available(self):
        return await self.can_ping_address(self, "steampowered.com")

    # Can we ping the priority interface's gateway or DNS
    async def is_gateway_available(self):
        logger.debug("is_gateway_available enter")

        connection_data = self.current_data['active_connection']
        if connection_data['connected'] is False or connection_data['name'] is "":
            connection_data = await self.active_connection(self)  # I swear to god if adding self works I'mma lose it.
        logger.debug("is_gateway_available connection_data %s", connection_data)

        interface_name = self.current_data["priority_interface_name"]
        if not interface_name['success']:
            interface_name = await self.get_priority_interface_name(self)

        logger.debug("is_gateway_available interface_name %s", interface_name)
        if connection_data is None or not interface_name['success']:
            logger.debug("is_gateway_available instant drop out due to no response or bad interface")
            return False

        nmcli_res = subprocess.run(["nmcli", "-f", "all", "-t", "device", "show", interface_name['data']], text=True,
                                   capture_output=True, timeout=15).stdout.splitlines()
        logger.debug("is_gateway_available nmcli_res %s", nmcli_res)

        final_res = None
        for e in nmcli_res:
            if not connection_data["ipv6_disabled"]:
                if "IP6.GATEWAY" in e and e.split(":")[1]:
                    item = e.split(':')
                    item.pop(0)
                    final_res = ''.join(item)
                    break
                if "IP6.DNS[3]" in e and e.split(":")[1]:
                    item = e.split(':')
                    item.pop(0)
                    final_res = ''.join(item)
                    break
                if "IP6.DNS[2]" in e and e.split(":")[1]:
                    item = e.split(':')
                    item.pop(0)
                    final_res = ''.join(item)
                    break
                if "IP6.DNS[1]" in e and e.split(":")[1]:
                    item = e.split(':')
                    item.pop(0)
                    final_res = ''.join(item)
                    break

            if "IP4.GATEWAY" in e and e.split(":")[1]:
                # 'IP4.GATEWAY:192.168.2.1'
                item = e.split(':')
                item.pop(0)
                final_res = ''.join(item)
                logger.debug("is_gateway_available ip4.gateway found %s", final_res)
                break
            if "IP4.DNS[3]" in e and e.split(":")[1]:
                item = e.split(':')
                item.pop(0)
                final_res = ''.join(item)
                logger.debug("is_gateway_available ip4.dns3 found %s", final_res)
                break
            if "IP4.DNS[2]" in e and e.split(":")[1]:
                # 'IP4.DNS[2]:192.168.2.1'
                item = e.split(':')
                item.pop(0)
                final_res = ''.join(item)
                logger.debug("is_gateway_available ip4.dns2 found %s", final_res)
                break
            if "IP4.DNS[1]" in e and e.split(":")[1]:
                # 'IP4.DNS[1]:8.8.8.8'
                item = e.split(':')
                item.pop(0)
                final_res = ''.join(item)
                logger.debug("is_gateway_available ip4.dns1 found %s", final_res)
                break

            if ":domain_name_servers" in e and e.split(":")[1]:
                # 'DHCP4.OPTION[5]:domain_name_servers = 8.8.8.8 192.168.2.1'
                final_res = e.strip().split(":")  # 'domain_name_servers = 8.8.8.8 192.168.2.1'
                final_res.pop(0)
                final_res = ''.join(final_res).split("=") if final_res[1] else [""]  # ' 8.8.8.8 192.168.2.1'
                final_res = final_res[1].split(" ") if final_res[1] else []  # ['8.8.8.8', '192.168.2.1']
                final_res = final_res[-1] if len(final_res) else None

        if final_res is None:
            logger.debug("is_gateway_available did not find address")
            return False
        return await self.can_ping_address(self, final_res)

    # Can we ping the provided network address
    async def can_ping_address(self, address):
        logger.debug("Pinging %s", address)
        ping_data = subprocess.run(["ping", "-c", "1", "-W", "5", address], text=True, capture_output=True, timeout=15)
        logger.debug("Pinging %s finish", address)
        ping_res = bool(ping_data.stderr)
        if ping_res:
            self.current_data['ping_results'].append({
                'address': address,
                'could_ping': False
            })
        else:
            ping_lines = ping_data.stdout.splitlines()
            ping_time = ''
            for item in ping_lines:
                if 'rtt' in item.lower():
                    ping_time = item.split('=')[1].split('/')[1]
            self.current_data['ping_results'].append({
                'address': address,
                'could_ping': True,
                'ping_time': f'{ping_time} ms'
            })
        return not ping_res
    # endregion

    # region Collect and set current VPN
    # Lists the connections from network manager.
    # If device is -- then it's disconnected.
    async def show(self):
        result = subprocess.run(["nmcli", "connection", "show"], text=True, capture_output=True, timeout=15).stdout
        connections = result.splitlines()
        connections.pop(0)
        mapped = map(connection_mapper, connections)
        return list(mapped)

    # Establishes a connection to a VPN
    async def up(self, uuid):
        logger.info("OPENING connection to: " + uuid)
        await self.reset_cached_data(self)
        result = subprocess.run(["nmcli", "connection", "up", uuid], text=True, capture_output=True, timeout=15).stdout
        return result

    # Closes a connection to a VPN
    async def down(self, uuid):
        logger.info("CLOSING connection to: " + uuid)
        await self.reset_cached_data(self)
        result = subprocess.run(["nmcli", "connection", "down", uuid], text=True, capture_output=True, timeout=15).stdout
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
                                text=True, capture_output=True, timeout=15).stdout
        connection["ipv6_disabled"] = True if "disabled" in result else False

        logger.debug("active_connection nmcli result %s", result)
        self.current_data['active_connection'] = connection
        return connection
    # endregion

    # region Collect and modify connection settings
    # Disables IPV6 on currently active connection
    async def disable_ipv6(self):
        await self.reset_cached_data(self)

        connection = get_active_connection()
        if connection is None:
            return True

        logger.info("DISABLING IPV6 for: " + connection["uuid"])
        subprocess.run(["nmcli", "connection", "modify", connection["uuid"], "ipv6.method", "disabled"], timeout=30)
        subprocess.run(["systemctl", "restart", "NetworkManager"], timeout=30)
        return True

    # Enable IPV6 on currently active connection
    async def enable_ipv6(self):
        await self.reset_cached_data(self)

        connection = get_active_connection()
        if connection is None:
            return True

        logger.info("ENABLING IPV6 for: " + connection["uuid"])
        subprocess.run(["nmcli", "connection", "modify", connection["uuid"], "ipv6.method", "auto"], timeout=30)
        subprocess.run(["systemctl", "restart", "NetworkManager"], timeout=30)
        return True

    # Checks if the OpenVPN package is installed
    async def is_openvpn_pacman_installed(self):
        try:
            subprocess.run(["pacman", "-Qi", "networkmanager-openvpn"], check=True, timeout=15)
            return True
        except subprocess.CalledProcessError:
            return False

    # The OpenVPN setting
    async def is_openvpn_enabled(self):
        return self.settings.getSetting("openvpn_enabled", False)

    # Enable OpenVPN
    async def enable_openvpn(self):
        logger.info("Enabling OpenVPN")
        await self.reset_cached_data(self)
        self.settings.setSetting("openvpn_enabled", True)
        run_install_script()
        return True

    # Disable OpenVPN
    async def disable_openvpn(self):
        logger.info("Disabling OpenVPN")
        await self.reset_cached_data(self)
        self.settings.setSetting("openvpn_enabled", False)
        run_uninstall_script()
        return True

    # endregion

    async def set_logging_type(self, logging_type):
        if 'I' in logging_type.upper():
            logger.setLevel(logging.INFO)
            return

        if 'D' in logging_type.upper():
            logger.setLevel(logging.INFO)
            return

        logger.setLevel(logging.INFO if logger.level is logging.DEBUG else logging.DEBUG)
