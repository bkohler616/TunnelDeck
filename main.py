import subprocess
import pprint
import logging
from os import path
from settings import SettingsManager
from helpers import get_user
import re
import json
import traceback

USER = get_user()
HOME_PATH = "/home/" + USER
HOMEBREW_PATH = HOME_PATH + "/homebrew"

logging.basicConfig(filename="/tmp/tunneldeck.log",
                    format="[TunnelDeck] %(asctime)s %(levelname)s %(message)s",
                    filemode="w+",
                    force=True)
logger = logging.getLogger()
logger.setLevel(logging.INFO)

badResponse = {
    "success": False,
    "data": 'N/A'
}

ipv6_gateways = ['IP6.GATEWAY', 'IP6.DNS[3]', 'IP6.DNS[2]', 'IP6.DNS[1]']
ipv4_gateways = ['IP4.GATEWAY', 'IP4.DNS[3]', 'IP4.DNS[2]', 'IP4.DNS[1]']
backup_gateway = ':domain_name_servers'


def connection_mapper(xn):
    # Filter out connection names like "FBI: Surveillance van" (nmcli will escape it for us)
    components = re.split(r"(?<!\\):", xn)
    return {
        "name": components[0],
        "uuid": components[1],
        "type": components[2],
        "device": components[3],
        "connected": False if not components[3] else True
    }


def gateway_finder(new_id, parser_type):
    if parser_type is 0:
        # IPV4
        item = new_id.split(':')
        item.pop(0)
        return ''.join(item)
    if parser_type is 1:
        # IPV6
        item = new_id.split(':')
        item.pop(0)
        return ':'.join(item)
    if parser_type is 2:
        # :domain_name_servers
        final_res = new_id.strip().split(":")  # 'domain_name_servers = 8.8.8.8 192.168.2.1'
        final_res.pop(0)
        final_res = ''.join(final_res).split("=") if final_res[1] else [""]  # ' 8.8.8.8 192.168.2.1'
        final_res = final_res[1].split(" ") if final_res[1] else []  # ['8.8.8.8', '192.168.2.1']
        return final_res[-1] if len(final_res) else None
    return None


def get_active_connection():
    result = subprocess.run(["nmcli", "-t", "connection", "show", "--active"],
                            text=True, capture_output=True).stdout
    connections = result.splitlines()
    # connections.pop(0)
    mapped = map(connection_mapper, connections)
    return next(filter(lambda xn: 'wireless' in xn["type"] or 'ethernet' in xn["type"], mapped), None)


def run_install_script():
    logger.info("Running Install Script")
    subprocess.run(["bash", path.dirname(__file__) + "/extensions/install"],
                   cwd=path.dirname(__file__) + "/extensions")


def run_uninstall_script():
    logger.info("Running Uninstall Script")
    subprocess.run(["bash", path.dirname(__file__) + "/extensions/uninstall"],
                   cwd=path.dirname(__file__) + "/extensions")


def log_pretty(obj):
    pp = pprint.PrettyPrinter(indent=2, sort_dicts=False)
    pretty_out = f"{pp.pformat(obj)}"
    return f'{pretty_out}'


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
        "priority_interface": {
            "success": False,
            "data": "N/A",
            "ip": '',
        },
        "ping_results": [],
    }  # Data structure template of "cached" data to prevent redundant calls.

    # region Plugin entry / exit
    async def _main(self):
        logger.info("Loading OpenVPN setting")
        await self.reset_cached_data(self)
        openvpn_enabled = self.settings.getSetting("openvpn_enabled", False)
        logger.info("OpenVPN enabled: " + "yes" if openvpn_enabled else "no")
        if openvpn_enabled:
            run_install_script()

    async def _unload(self):
        openvpn_enabled = self.settings.getSetting("openvpn_enabled", False)
        logger.info("OpenVPN enabled: " + "yes" if openvpn_enabled else "no")
        if openvpn_enabled:
            run_uninstall_script()
        pass

    # endregion

    # region Network info collectors
    # Reset all cached network information.
    async def reset_cached_data(self):
        logger.debug(f'reset_cached_data called - Seperator - Last set was {log_pretty(self.current_data)}')
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
            "priority_interface": {
                "success": False,
                "data": "N/A",
                "ip": '',
            },
            "ping_results": [],
        }

        return True

    # Collect the IP address of steam
    async def get_steam_ip(self):
        logger.debug("Collecting steam's IP")
        try:
            getent_data = subprocess.run(["getent", "ahosts", "steampowered.com"],
                                         text=True, capture_output=True, timeout=15)
        except TimeoutError:
            getent_data = {"stderr": "Timeout"}
        logger.debug(f"Collecting steam's IP - getting steam ip {getent_data}")
        if getent_data.stderr and not getent_data.stdout:
            return
        stdout_lines = getent_data.stdout.splitlines()
        for e in stdout_lines:
            if "STREAM" in e:
                res = e.split(" ")[0]
                logger.debug(f"steam's ip is {log_pretty(res)}")
                self.current_data["steam_ip"] = res
                return res

    # Collect both priority interface name and IP
    async def get_priority_interface(self):
        try:
            logger.debug("get_priority_interface - enter")
            # "ip route get 1.2.3.4 | awk '{print $3; exit}'"

            steam_ip = self.current_data["steam_ip"]
            if not steam_ip:
                steam_ip = await self.get_steam_ip(self)

            if not steam_ip:
                logger.debug("get_priority_interface - break out due to no steam IP found")

            logger.debug("get_priority_interface - got steam IP")

            try:
                ip_data = subprocess.run(["ip", "-j", "route", "get", steam_ip],
                                         text=True, capture_output=True, timeout=15)
            except TimeoutError:
                ip_data = {"stderr": "Timeout"}
            logger.debug("get_priority_interface - got ip route data")
            if ip_data.stderr or not ip_data.stdout:
                result = badResponse
            else:
                try:
                    ip_route_data = json.loads(ip_data.stdout)
                    result = {
                        "success": True,
                        "data": ip_route_data[0]["dev"],
                        "ip": ip_route_data[0]['prefsrc']
                    }
                except ValueError as e:
                    logger.error(f"get_priority_interface - JSON parsing failed due to {e}")
                    result = badResponse

            self.current_data['priority_interface'] = result
            return result
        except Exception as err:
            logger.error(f'get_priority_interface error - {log_pretty(err)}')
            return {
                "success": False,
                "data": log_pretty(err)
            }

    # Collect detailed networking information based on the prioritized interface name.
    async def get_prioritized_network_info(self):
        try:
            logger.debug("get_prioritized_network_info enter")

            connection_data = self.current_data['active_connection']
            if connection_data['connected'] is False or connection_data['name'] is "":
                connection_data = await self.active_connection(
                    self)  # I swear to god if adding self works I'mma lose it.
            logger.debug("get_prioritized_network_info connection_data %s", connection_data)

            interface_name = self.current_data["priority_interface"]
            if not interface_name['success'] or not interface_name['data']:
                interface_name = await self.get_priority_interface(self)

            logger.debug("get_prioritized_network_info interface_name %s", interface_name)

            if connection_data is None or not interface_name['success'] or not interface_name['data']:
                logger.debug("get_prioritized_network_info instant drop out due to no response or bad interface")
                return badResponse

            nmcli_res = subprocess.run(["nmcli", "-f", "all", "-t", "device", "show", interface_name['data']],
                                       text=True,
                                       capture_output=True).stdout.splitlines()
            logger.debug("get_prioritized_network_info nmcli_res %s", nmcli_res)

            network_info = []

            collected_gateway = None
            for e in nmcli_res:
                found_value = e.split(":")
                if len(found_value) > 1:
                    found_value = found_value[1]
                else:
                    found_value = None
                #region Priority network data
                if "GENERAL.DEVICE" in e and found_value:
                    network_info.append(f"DEVICE: {found_value}")
                if "GENERAL.TYPE" in e and found_value:
                    network_info.append(f"TYPE: {found_value}")
                if "GENERAL.STATE" in e and found_value:
                    network_info.append(f"STATE: {found_value}")
                if "GENERAL.REASON" in e and found_value:
                    network_info.append(f"REASON: {found_value}")
                if "GENERAL.IP4-CONNECTIVITY" in e and found_value:
                    network_info.append(f"IP4-CONN: {found_value}")
                if "GENERAL.IP6-CONNECTIVITY" in e and found_value:
                    network_info.append(f"IP6-CONN: {found_value}")
                if "GENERAL.IP-IFACE" in e and found_value:
                    network_info.append(f"IP-IFACE: {found_value}")
                if "GENERAL.CONNECTION" in e and found_value:
                    network_info.append(f"CONNECTION: {found_value}")
                if "GENERAL.METERED" in e and found_value:
                    network_info.append(f"METERED: {found_value}")
                if "CAPABILITIES.SPEED" in e and found_value:
                    network_info.append(f"SPEED: {found_value}")

                if ".ADDRESS" in e and found_value:
                    item = e.split(':')
                    network_info.append(f"{item.pop(0)}: {':'.join(item)}")
                if ".GATEWAY" in e and found_value:
                    item = e.split(':')
                    item.pop(0)
                    network_info.append(f"{e.split(':')[0]}: {':'.join(item)}")
                if ".DNS" in e and found_value:
                    item = e.split(':')
                    item.pop(0)
                    network_info.append(f"{e.split(':')[0]}: {':'.join(item)}")
                #endregion
                #region gateway data

                if not connection_data["ipv6_disabled"]:
                    for i in ipv6_gateways:
                        if collected_gateway:
                            break
                        logger.debug(f'BIG - {log_pretty(i)} :::: {log_pretty(e)} :::: {log_pretty(found_value)}')
                        if i in e and found_value:
                            collected_gateway = gateway_finder(e, 1)
                            logger.debug(f'BIG - Gateway is now {collected_gateway}')
                            break
                for i in ipv4_gateways:
                    if collected_gateway:
                        break
                    logger.debug(f'BIG - {log_pretty(i)} :::: {log_pretty(e)} :::: {log_pretty(found_value)}')
                    if i in e and found_value:
                        collected_gateway = gateway_finder(e, 0)
                        logger.debug(f'BIG - Gateway is now {collected_gateway}')

                if not collected_gateway and ":domain_name_servers" in e and found_value:
                    logger.debug(f'BIG - :domain_name_servers :::: {log_pretty(e)} :::: {log_pretty(found_value)}')
                    collected_gateway = gateway_finder(e, 2)
                #endregion
            if collected_gateway is None:
                logger.debug("get_prioritized_network_info did not find a gateway address")
                gateway_ping = False
            else:
                gateway_ping = await self.can_ping_address(self, collected_gateway)

            logger.debug("get_prioritized_network_info finished")

            ping_res = []
            for ping in self.current_data['ping_results']:
                str_builder = f'Pinging {ping["address"]}'
                str_builder = f'{str_builder} {"succeeded" if ping["could_ping"] else "failed"}'
                if ping["could_ping"]:
                    str_builder = f'{str_builder} in {ping["ping_time"]}'
                ping_res.append(str_builder)

            final_res = '\n'.join(ping_res + network_info)
            return {
                "success": bool(network_info),
                "data": final_res,
                "gateway_ping": gateway_ping,
            }
        except Exception as err:
            logger.error(f'get_prioritized_network_info error - {log_pretty(err)} - {traceback.format_exc()}')
            return {
                "success": False,
                "data": err
            }

    # Can we ping steampowered.com
    async def is_internet_available(self):
        return await self.can_ping_address(self, "steampowered.com")

    # Can we ping the provided network address
    async def can_ping_address(self, address):
        logger.debug("Pinging %s", address)
        try:
            ping_data = subprocess.run(["ping", "-c", "1", "-W", "5", address],
                                       text=True, capture_output=True, timeout=15)
        except TimeoutError:
            ping_data = {"stderr": "Timeout"}
        ping_res = not bool(ping_data.stderr)
        if not ping_res:
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
        logger.debug(f"Pinging {address} finished. Results: {ping_res}")
        return ping_res

    # endregion

    # region Collect and set current VPN
    # Lists the connections from network manager.
    # If device is -- then it's disconnected.
    async def show(self):
        result = subprocess.run(["nmcli", "-t", "connection", "show"], text=True, capture_output=True).stdout
        connections = result.splitlines()
        # connections.pop(0)
        mapped = map(connection_mapper, connections)
        logger.info(f'SHOW - found the following possible networks: {log_pretty(mapped)}')
        return list(mapped)

    # Establishes a connection to a VPN
    async def up(self, uuid):
        logger.info("OPENING connection to: " + uuid)
        await self.reset_cached_data(self)
        result = subprocess.run(["nmcli", "connection", "up", uuid], text=True, capture_output=True).stdout
        return result

    # Closes a connection to a VPN
    async def down(self, uuid):
        logger.info("CLOSING connection to: " + uuid)
        await self.reset_cached_data(self)
        result = subprocess.run(["nmcli", "connection", "down", uuid], text=True, capture_output=True,).stdout
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

        logger.debug("active_connection nmcli result collected - ipv6 disabled is %s", connection["ipv6_disabled"])
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
        subprocess.run(["nmcli", "connection", "modify", connection["uuid"], "ipv6.method", "disabled"])
        subprocess.run(["systemctl", "restart", "NetworkManager"])
        return True

    # Enable IPV6 on currently active connection
    async def enable_ipv6(self):
        await self.reset_cached_data(self)

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
