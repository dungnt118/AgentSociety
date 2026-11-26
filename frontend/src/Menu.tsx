import {
    ApartmentOutlined,
    ApiOutlined,
    BookOutlined,
    CloudSyncOutlined,
    ExperimentOutlined,
    FormOutlined,
    GithubOutlined,
    GlobalOutlined,
    MenuOutlined,
    MoreOutlined,
    NodeIndexOutlined,
    RocketOutlined,
    SettingOutlined,
    TeamOutlined,
    ThunderboltOutlined,
} from "@ant-design/icons";
import { Button, Drawer, Dropdown, Grid, Menu, MenuProps } from "antd";
import React, { useState } from "react";
import { useTranslation } from 'react-i18next';
import { Link } from "react-router";
import Account from "./components/Account";
import { WITH_AUTH } from "./components/fetch";

const RootMenu = ({ selectedKey, style }: {
    selectedKey: string,
    style?: React.CSSProperties
}) => {
    const { t, i18n } = useTranslation();
    const screens = Grid.useBreakpoint();
    const isMobile = screens.md === false;
    const [drawerOpen, setDrawerOpen] = useState(false);

    const currentLang = (i18n.resolvedLanguage || i18n.language || 'vi').split('-')[0];
    const languageLabels: Record<string, string> = {
        vi: 'Tiếng Việt',
        en: 'English',
        zh: '中文',
    };
    const languageItems: MenuProps['items'] = [
        { key: 'vi', label: 'Tiếng Việt' },
        { key: 'en', label: 'English' },
        { key: 'zh', label: '中文' },
    ];

    const externalResourceItems: MenuProps['items'] = [
        {
            key: "/Documentation",
            icon: <BookOutlined />,
            label: (
                <a href="https://agentsociety2.readthedocs.io/" rel="noopener noreferrer" target="_blank">
                    {t('menu.documentation')}
                </a>
            ),
        },
        {
            key: "/V2",
            icon: <RocketOutlined />,
            label: (
                <a href="https://agentsociety2.fiblab.net" rel="noopener noreferrer" target="_blank">
                    {t('menu.v2')}
                </a>
            ),
        },
        {
            key: "/Github",
            icon: <GithubOutlined />,
            label: (
                <a href="https://github.com/tsinghua-fib-lab/agentsociety/" rel="noopener noreferrer" target="_blank">
                    {t('menu.github')}
                </a>
            ),
        },
    ];

    const agentSubItems: MenuProps['items'] = [
        {
            key: '/agents',
            label: <Link to="/agents">{t('menu.agents')}</Link>,
            icon: <TeamOutlined />,
        },
        {
            key: '/agent-templates',
            label: <Link to="/agent-templates">{t('menu.agentTemplates')}</Link>,
            icon: <SettingOutlined />,
        },
        {
            key: '/profiles',
            label: <Link to="/profiles">{t('menu.profiles')}</Link>,
            icon: <TeamOutlined />,
        },
        {
            key: '/skills',
            label: <Link to="/skills">{t('menu.skills')}</Link>,
            icon: <ThunderboltOutlined />,
        },
    ];

    const primaryMenuItems: MenuProps['items'] = [
        {
            key: '/urban-sim',
            label: <Link to="/urban-sim">Mô phỏng Khu đô thị</Link>,
            icon: <ApartmentOutlined />,
        },
        {
            key: '/llms',
            label: <Link to="/llms">{t('menu.llmConfigs')}</Link>,
            icon: <ApiOutlined />,
        },
        {
            key: '/maps',
            label: <Link to="/maps">{t('menu.maps')}</Link>,
            icon: <GlobalOutlined />,
        },
        {
            key: '/agents-group',
            label: t('menu.agents'),
            icon: <TeamOutlined />,
            children: agentSubItems,
        },
        {
            key: '/workflows',
            label: <Link to="/workflows">{t('menu.workflows')}</Link>,
            icon: <NodeIndexOutlined />,
        },
        {
            key: "/console",
            label: <Link to="/console">{t('menu.experiments')}</Link>,
            icon: <ExperimentOutlined />,
        },
        {
            key: "/survey",
            label: <Link to="/survey">{t('menu.survey')}</Link>,
            icon: <FormOutlined />,
        },
        {
            key: "/system-backup",
            label: <Link to="/system-backup">{t('menu.systemBackup')}</Link>,
            icon: <CloudSyncOutlined />,
        },
        ...(WITH_AUTH ? [{ key: "/bill", label: <Link to="/bill">{t('menu.bill')}</Link> }] : []),
    ];

    const mobileDrawerItems: MenuProps['items'] = [
        ...primaryMenuItems,
        { type: 'divider' },
        ...externalResourceItems,
    ];

    const activeKey = ['/agents', '/agent-templates', '/profiles', '/skills'].includes(selectedKey)
        ? selectedKey
        : selectedKey;

    const menuStyle: React.CSSProperties = {
        ...style,
        flex: 1,
        minWidth: 0,
        height: 56,
        lineHeight: '56px',
        borderBottom: 'none',
    };

    return (
        <div style={{ display: 'flex', width: '100%', minWidth: 0, height: 56, alignItems: 'center' }}>
            {!isMobile && (
                <Menu
                    className="root-top-menu"
                    theme="dark"
                    mode="horizontal"
                    items={primaryMenuItems}
                    selectedKeys={[activeKey]}
                    style={menuStyle}
                />
            )}
            <div style={{
                marginLeft: 'auto',
                display: 'flex',
                alignItems: 'center',
                gap: 4,
                flexShrink: 0,
                justifyContent: 'flex-end',
            }}>
                {!isMobile && (
                    <Dropdown
                        menu={{ items: externalResourceItems }}
                        placement="bottomRight"
                        arrow
                    >
                        <Button
                            type="text"
                            size="middle"
                            aria-label="Tài nguyên tham khảo"
                            style={{ color: 'white' }}
                            icon={<MoreOutlined />}
                        />
                    </Dropdown>
                )}
                <Dropdown
                    menu={{
                        items: languageItems,
                        selectedKeys: [currentLang],
                        onClick: ({ key }) => i18n.changeLanguage(key),
                    }}
                    placement="bottomRight"
                    arrow
                >
                    <Button type="text" size={isMobile ? 'small' : 'middle'} style={{ color: 'white' }} icon={<GlobalOutlined />}>
                        {isMobile ? currentLang.toUpperCase() : (languageLabels[currentLang] || 'Tiếng Việt')}
                    </Button>
                </Dropdown>
                {WITH_AUTH && <Account />}
                {isMobile && (
                    <Button
                        type="text"
                        aria-label="Mở menu điều hướng"
                        style={{ color: 'white' }}
                        icon={<MenuOutlined />}
                        onClick={() => setDrawerOpen(true)}
                    />
                )}
            </div>

            <Drawer
                title="Điều hướng AgentSociety"
                placement="right"
                size="default"
                styles={{ wrapper: { width: 280 } }}
                open={drawerOpen}
                onClose={() => setDrawerOpen(false)}
            >
                <Menu
                    mode="inline"
                    selectedKeys={[activeKey]}
                    items={mobileDrawerItems}
                    onClick={() => setDrawerOpen(false)}
                    style={{ borderRight: 'none' }}
                />
            </Drawer>
        </div>
    );
};

export default RootMenu;
