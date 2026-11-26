import { Divider, Flex, Grid, Layout } from "antd";
import { Content, Header } from "antd/es/layout/layout";
import RootMenu from "./Menu";
import { Link } from "react-router";
import React, { useEffect, useRef } from "react";

export default function RootLayout({
    children,
    selectedKey,
    homePage,
}: {
    children: React.ReactNode
    selectedKey: string
    homePage?: boolean
}) {
    const headerRef = useRef<HTMLDivElement>(null);
    const contentRef = useRef<HTMLDivElement>(null);
    const screens = Grid.useBreakpoint();
    const isMobile = screens.md === false;

    const headerStyle: React.CSSProperties = {
        background: '#000088',
        color: 'white',
        padding: isMobile ? '0 12px' : '0 20px',
        height: 56,
        lineHeight: '56px',
        overflow: 'hidden',
        display: 'flex',
        alignItems: 'center',
    };

    const menuStyle: React.CSSProperties = {
        background: '#000088',
        color: 'white',
        height: 56,
        lineHeight: '56px',
    };

    useEffect(() => {
        if (contentRef.current === null) {
            return;
        }
        if (headerRef.current) {
            const headerHeight = headerRef.current.clientHeight;
            contentRef.current.style.minHeight = `calc(100vh - ${headerHeight}px)`;
            return;
        }
        contentRef.current.style.minHeight = '90vh';
    }, [headerRef, contentRef]);

    const contentStyle: React.CSSProperties = homePage ? {
        width: "100%",
        background: '#000088',
        top: 0,
        left: 0,
        alignContent: "center",
        justifyContent: "center",
    } : {
        width: "100%",
        minWidth: 0,
        overflowX: "hidden",
    };

    return (
        <Layout style={{ minHeight: '100vh', overflowX: 'hidden' }}>
            <Header ref={headerRef} style={headerStyle}>
                <Flex gap='small' align='center' style={{ width: '100%', minWidth: 0, height: 56 }}>
                    <Link to="/" style={{ display: 'flex', alignItems: 'center', flexShrink: 0 }}>
                        <img src="/logo.png" alt="AgentSociety" style={{ height: '24px', display: 'block' }} />
                    </Link>
                    <Divider
                        type="vertical"
                        style={{
                            flexShrink: 0,
                            borderInlineStartColor: 'rgba(255,255,255,0.28)',
                            height: 20,
                            margin: '0 8px',
                        }}
                    />
                    <div style={{ flex: 1, minWidth: 0, height: 56, display: 'flex', alignItems: 'center' }}>
                        <RootMenu selectedKey={homePage ? "" : selectedKey} style={menuStyle} />
                    </div>
                </Flex>
            </Header>
            <Content ref={contentRef} style={contentStyle}>
                {children}
            </Content>
        </Layout>
    );
}
