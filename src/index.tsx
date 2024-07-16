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

type PluginResponse = {
  success: boolean,
  data: string,
}


let interfaceCheckerId: number;
const Content: VFC<{ serverAPI: ServerAPI }> = ({ serverAPI }) => {

  const [ loaded, setLoaded ] = useState(false);
  const [ connections, setConnections ] = useState<Connection[]>([]);
  const [ priorityInterface, setPriorityInterface ] = useState('N/A');
  const [ priorityInterfaceLanIp, setPriorityInterfaceLanIp ] = useState('N/A');
  const [ canReachGateway, setCanReachGateway ] = useState('N/A');
  const [ canReachSteam, setCanReachSteam ] = useState('N/A');
  const [ activeConnection, setActiveConnection ] = useState<Connection>();
  const [ ipv6Disabled, setIpv6Disabled ] = useState(false);
  const [ openVPNEnabled, setOpenVPNEnabled ] = useState(false);
  const [ openVPNDisabled, setOpenVPNDisabled ] = useState(false);
  const [ isRefreshing, setIsRefreshing ] = useState(false);

  const interfaceChecker = () => {
    clearTimeout(interfaceCheckerId);
    interfaceCheckerId = window.setTimeout(() => {
      getInterfaceData().finally(interfaceChecker);
    }, 5000);
  }

  const collectNetworkInfo = () => {
    clearTimeout(interfaceCheckerId);
    window.setTimeout(() => {
      getInterfaceData().finally(interfaceChecker);
    }, 300);
  }

  const tryCatchHandler = async (name: String, func: Function, methodName: String, args: Object, defaultRes: Object) => {
    try {
      return await func(methodName, args);
    } catch (e) {
      console.error('Error handling function', name, methodName);
      return defaultRes;
    }
  }

  const getInterfaceData = async () => {
    setIsRefreshing(true);
    debugger;

    const priorityInterfaceLanIpResponse = await tryCatchHandler('priorityInterfaceLaneIpResponse', serverAPI.callPluginMethod<{}, PluginResponse>, 'get_priority_lan_ip', {}, {result: {success:false, data: 'N/A'}});
    const lanIpRes = priorityInterfaceLanIpResponse.result as PluginResponse;
    setPriorityInterfaceLanIp(lanIpRes.data);

    const isSteamSteamAvailableResponse = await tryCatchHandler('isSteamSteamAvailableResponse', serverAPI.callPluginMethod<{}, PluginResponse>, 'is_internet_available', {}, {result: {success:false, data: 'N/A'}});
    setCanReachSteam(isSteamSteamAvailableResponse.result && isSteamSteamAvailableResponse.success ? 'Yes' : 'No');

    const priorityInterfaceResponse = await tryCatchHandler('priorityInterfaceResponse', serverAPI.callPluginMethod<{}, PluginResponse>, 'get_priority_interface_name', {}, {result: false});
    const interfaceRes = priorityInterfaceResponse.result as PluginResponse;
    setPriorityInterface(interfaceRes.data);

    const isGatewayAvailableResponse = await tryCatchHandler('isGatewayAvailableResponse', serverAPI.callPluginMethod<{}, PluginResponse>, 'is_gateway_available', {}, {result: false});
    setCanReachGateway(isGatewayAvailableResponse.result && isGatewayAvailableResponse.success ? 'Yes' : 'No');

    setIsRefreshing(false);
  }

  const loadConnections = async () => {

    try {
      const activeConnectionResponse = await serverAPI.callPluginMethod<{}, Connection>('active_connection', {});
      const activeConnection = activeConnectionResponse.result as Connection;
      setActiveConnection(activeConnection);
      setIpv6Disabled((activeConnection.ipv6_disabled) ? true : false);
    } catch (error) {
      console.error(error);
    }

    try {
      const openVPNDisabled = await serverAPI.callPluginMethod<{}, boolean>('is_openvpn_pacman_installed', {});
      setOpenVPNDisabled(openVPNDisabled.result as boolean);
    } catch (error) {
      console.error(error);
    }

    if(!openVPNDisabled) {
      try {
        const openVPNEnabledResponse = await serverAPI.callPluginMethod<{}, boolean>('is_openvpn_enabled', {});
        setOpenVPNEnabled(openVPNEnabledResponse.result as boolean);
      } catch (error) {
        console.error(error);
      }
    }

    try {
      const response = await serverAPI.callPluginMethod<{}, Connection[]>('show', {});
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

    setLoaded(true);
    collectNetworkInfo();
  }

  const toggleConnection = async (connection: Connection, switchValue: boolean) => {
    await serverAPI.callPluginMethod((switchValue) ? 'up' : 'down', { uuid: connection.uuid });
    collectNetworkInfo();
  }

  const toggleIpv6 = async(switchValue: boolean) => {
    setIpv6Disabled(switchValue);
    await serverAPI.callPluginMethod((switchValue) ? 'disable_ipv6' : 'enable_ipv6', {});
    collectNetworkInfo();
  }

  const toggleOpenVPN = async(switchValue: boolean) => {
    setOpenVPNEnabled(switchValue);
    await serverAPI.callPluginMethod((switchValue) ? 'enable_openvpn' : 'disable_openvpn', {});
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
    </>
  );
};

export default definePlugin((serverApi: ServerAPI) => {
  return {
    title: <div className={staticClasses.Title}>TunnelDeck</div>,
    content: <Content serverAPI={serverApi} />,
    icon: <FaShieldAlt />,
    onDismount() {
      console.log('sup!');
      clearTimeout(interfaceCheckerId);
    }
  };
});
