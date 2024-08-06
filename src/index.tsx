import {
  definePlugin,
  PanelSection,
  PanelSectionRow,
  ServerAPI,
  staticClasses,
  ToggleField,
  ButtonItem,
  Navigation,
  Field
} from "decky-frontend-lib";

import {
  VFC,
  useEffect,
  useState
} from "react";

import { FaShieldAlt } from "react-icons/fa";

type Connection = {
  name: string,
  uuid: string,
  type: string,
  connected: boolean,
  ipv6_disabled?: boolean
}

interface PluginResponse {
  success: boolean,
  data: string,
}

interface InterfaceResponse extends PluginResponse {
  ip: string,
}

interface NetworkResponse extends PluginResponse {
  gateway_ping: boolean,
}

const funcMap = {
  show: 'show',
  up: 'up',
  down: 'down',
  activeConnection: 'active_connection',
  resetCachedData: 'reset_cached_data',
  disableIpv6: 'disable_ipv6',
  enableIpv6: 'enable_ipv6',
  getSteamIp: 'get_steam_ip',
  isOpenvpnPacmanInstalled: 'is_openvpn_pacman_installed',
  isOpenvpnEnabled: 'is_openvpn_enabled',
  enableOpenvpn: 'enable_openvpn',
  disableOpenvpn: 'disable_openvpn',

  getPriorityInterface: 'get_priority_interface',

  // getPriorityLanIp: 'get_priority_lan_ip',
  // getPriorityInterfaceName: 'get_priority_interface_name', // Remove this in favour of new method:

  isInternetAvailable: 'is_internet_available', // to remove
  getPrioritizedNetworkInfo: 'get_prioritized_network_info',// to remove

  // isGatewayAvailable: 'is_gateway_available',
  canPingAddress: 'can_ping_address', // Unused externally.
  setLoggingType: 'set_logging_type', // Need better testing
}


let interfaceCheckerId: number;
// For some reason, setting setIsRefreshing doesn't update the code side of the understanding.
// So have to make my own variable that does the exact same thing... lol...
let isActuallyRefreshing = true;
const Content: VFC<{ serverAPI: ServerAPI }> = ({ serverAPI }) => {

  const [ loaded, setLoaded ] = useState(false);
  const [ connections, setConnections ] = useState<Connection[]>([]);
  const [ priorityInterface, setPriorityInterface ] = useState('N/A');
  const [ priorityInterfaceLanIp, setPriorityInterfaceLanIp ] = useState('N/A');
  const [ canReachGateway, setCanReachGateway ] = useState('N/A');
  const [ canReachSteam, setCanReachSteam ] = useState('N/A');
  const [ priorityNetworkInfo, setPriorityNetworkInfo ] = useState(['N/A']);
  const [ activeConnection, setActiveConnection ] = useState<Connection>();
  const [ ipv6Disabled, setIpv6Disabled ] = useState(false);
  const [ openVPNEnabled, setOpenVPNEnabled ] = useState(false);
  const [ openVPNDisabled, setOpenVPNDisabled ] = useState(false);
  const [ isRefreshing, setIsRefreshing ] = useState(true); // This is always true on the code-side... idk why.


  const interfaceChecker = () => {
    clearTimeout(interfaceCheckerId);
    interfaceCheckerId = window.setTimeout(() => {
      if (isActuallyRefreshing) {
        return interfaceChecker();
      }

      getInterfaceData().finally(interfaceChecker);
    }, 5000);
  }

  const collectNetworkInfo = () => {
    if (isActuallyRefreshing && loaded) {
      return;
    }
    isActuallyRefreshing = true;

    clearTimeout(interfaceCheckerId);
    window.setTimeout(() => {
      getInterfaceData().finally(interfaceChecker);
    }, 1000);
  }

  const tryCatchHandler = async (name: String, func: Function, methodName: String, args: Object, defaultRes: Object) => {
    try {
      return await func(methodName, args);
    } catch (e) {
      console.error('Error handling function', name, methodName);
      return defaultRes;
    }
  }

  const setRefreshState = () => {
    clearTimeout(interfaceCheckerId);
    setIsRefreshing(true);
    setPriorityInterface('N/A');
    setPriorityInterfaceLanIp('N/A');
    setCanReachSteam('N/A');
    setCanReachGateway('N/A');
    setPriorityNetworkInfo(['N/A']);
  }

  const getInterfaceData = async () => {
    setIsRefreshing(true);
    isActuallyRefreshing = true;
    console.log('TunnelDeck - Collecting interface data');
    try {


    await tryCatchHandler(funcMap.resetCachedData, serverAPI.callPluginMethod<{}, boolean>, funcMap.resetCachedData, {}, true)

    const pPriorityInterfaceLaneIp = tryCatchHandler(funcMap.getPriorityInterface, serverAPI.callPluginMethod<{}, InterfaceResponse>, funcMap.getPriorityInterface, {}, {result: {success:false, data: 'N/A'}})
        .then((priorityInterfaceLanIpResponse) => {
          const interfaceResponse = priorityInterfaceLanIpResponse.result as InterfaceResponse;
          setPriorityInterfaceLanIp(interfaceResponse.success ? interfaceResponse.ip : 'N/A');
          setPriorityInterface(interfaceResponse.success ? interfaceResponse.data : 'N/A');
        });

    const pIsSteamAvailable = tryCatchHandler(funcMap.isInternetAvailable, serverAPI.callPluginMethod<{}, PluginResponse>, funcMap.isInternetAvailable, {}, {result: {success:false, data: 'N/A'}})
        .then((isSteamAvailableResponse)  => {
          setCanReachSteam(isSteamAvailableResponse.result && isSteamAvailableResponse.success ? 'Yes' : 'No');
        });

    const pPriorityNetworkInfo = tryCatchHandler(funcMap.getPrioritizedNetworkInfo, serverAPI.callPluginMethod<{}, NetworkResponse>, funcMap.getPrioritizedNetworkInfo, {}, {result: {success:false, data: 'N/A'}})
        .then((priorityNetworkInfo) => {
          const networkResponse = priorityNetworkInfo.result as NetworkResponse;
          setPriorityNetworkInfo(networkResponse.success ? networkResponse.data.split('\n') : ['N/A']);
          setCanReachGateway(networkResponse.success && networkResponse.gateway_ping ? 'Yes' : 'No');
        });


    await Promise.all([pIsSteamAvailable, pPriorityInterfaceLaneIp, pPriorityNetworkInfo])
    } catch (e) {
      console.error('TunnelDeck - Error: ', e);
    } finally {
      console.log('TunnelDeck - Finished refreshing');
      setIsRefreshing(false);
      isActuallyRefreshing = false;
    }
  }

  const loadConnections = async () => {
    try {
      const activeConnectionResponse = await serverAPI.callPluginMethod<{}, Connection>(funcMap.activeConnection, {});
      const activeConnection = activeConnectionResponse.result as Connection;
      setActiveConnection(activeConnection);
      setIpv6Disabled(!!(activeConnection.ipv6_disabled));
    } catch (error) {
      console.error(error);
    }

    try {
      const openVPNDisabled = await serverAPI.callPluginMethod<{}, boolean>(funcMap.isOpenvpnPacmanInstalled, {});
      setOpenVPNDisabled(openVPNDisabled.result as boolean);
    } catch (error) {
      console.error(error);
    }

    if(!openVPNDisabled) {
      try {
        const openVPNEnabledResponse = await serverAPI.callPluginMethod<{}, boolean>(funcMap.isOpenvpnEnabled, {});
        setOpenVPNEnabled(openVPNEnabledResponse.result as boolean);
      } catch (error) {
        console.error(error);
      }
    }

    try {
      const response = await serverAPI.callPluginMethod<{}, Connection[]>(funcMap.show, {});
      const connections = response.result as Connection[];
      const filtered = connections
      .filter((connection) => ['vpn', 'wireguard'].includes(connection.type))
      .sort((a, b) => {
        if(a.name < b.name) return -1;
        if(a.name > b.name) return 1;
        return 0;
      });

      setConnections(filtered);
    } catch (error) {
      console.error(error);
    }

    collectNetworkInfo();
    setLoaded(true);
  }

  const toggleConnection = async (connection: Connection, switchValue: boolean) => {
    setRefreshState();
    await serverAPI.callPluginMethod((switchValue) ? funcMap.up : funcMap.down, { uuid: connection.uuid });
    collectNetworkInfo();
  }

  const toggleIpv6 = async(switchValue: boolean) => {
    setIpv6Disabled(switchValue);
    setRefreshState();
    await serverAPI.callPluginMethod((switchValue) ? funcMap.disableIpv6 : funcMap.enableIpv6, {});
    collectNetworkInfo();
  }

  const toggleOpenVPN = async(switchValue: boolean) => {
    setOpenVPNEnabled(switchValue);
    setRefreshState();
    await serverAPI.callPluginMethod((switchValue) ? funcMap.enableOpenvpn : funcMap.disableOpenvpn, {});
    collectNetworkInfo();
  }

  useEffect(() => {
    loadConnections();
    return () => {
      clearTimeout(interfaceCheckerId);
    }
  }, []);

  return (
    <>
      <PanelSection title="Connections">

        {loaded && connections.length == 0 && <PanelSectionRow>
          No Connections Found
        </PanelSectionRow>}

        {connections.length > 0 && connections.map((connection) => (
          <PanelSectionRow>
            <ToggleField
            bottomSeparator='standard'
            checked={connection.connected}
            label={connection.name}
            description={`Type: ${connection.type}`}
            onChange={(switchValue: boolean) => {
              toggleConnection(connection, switchValue);
            }} />
          </PanelSectionRow>
        ))}

        <PanelSectionRow>
          <ButtonItem onClick={() => {
            Navigation.NavigateToExternalWeb('https://github.com/bkohler616/TunnelDeck#readme');
            Navigation.CloseSideMenus();
          }}>
            How Do I Add Connections?
          </ButtonItem>
        </PanelSectionRow>

      </PanelSection>

      <PanelSection title="Network Info" spinner={isRefreshing}>
        <PanelSectionRow>
          <Field
            label='Prioritized Network Interface'
            description={priorityInterface}
            focusable={true}>
          </Field>
        </PanelSectionRow>
        <PanelSectionRow>
          <Field
              label='Prioritized Interface LAN IP'
              description={priorityInterfaceLanIp}
              focusable={true}>
          </Field>
        </PanelSectionRow>
        <PanelSectionRow>
          <Field
              label='Can reach gateway'
              description={canReachGateway}
              focusable={true}>
          </Field>
        </PanelSectionRow>
        <PanelSectionRow>
          <Field
              label='Can reach steampowered.com'
              description={canReachSteam}
              focusable={true}>
          </Field>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Settings">
        <PanelSectionRow>
          <ToggleField
          bottomSeparator='standard'
          checked={openVPNEnabled || openVPNDisabled}
          label='Enable OpenVPN'
          disabled={!loaded || openVPNDisabled}
          description='Installs OpenVPN support for Network Manager'
          onChange={toggleOpenVPN} />
        </PanelSectionRow>

        <PanelSectionRow>
          <ToggleField
          bottomSeparator='standard'
          checked={ipv6Disabled}
          label='Disable IPV6'
          disabled={!activeConnection || !loaded}
          description='Disables IPV6 support for the current connection. Required for some VPNs.'
          onChange={toggleIpv6} />
        </PanelSectionRow>
      </PanelSection>
      <PanelSection title="Additional network info" spinner={isRefreshing}>

        {loaded && priorityNetworkInfo.length == 0 && <PanelSectionRow>
          No Network Info found
        </PanelSectionRow>}

        {priorityNetworkInfo.length > 0 && priorityNetworkInfo.map((infoItem) => (
            <PanelSectionRow>
              <Field
                  description={infoItem}
                  focusable={true}
                  padding={"none"}/>
            </PanelSectionRow>
        ))}
      </PanelSection>
    </>
  );
};

export default definePlugin((serverApi: ServerAPI) => {
  return {
    title: <div className={staticClasses.Title}>TunnelDeck</div>,
    content: <Content serverAPI={serverApi} />,
    icon: <FaShieldAlt />,
    onDismount() {
      clearTimeout(interfaceCheckerId);
    }
  };
});
