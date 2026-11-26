import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
    Alert,
    AutoComplete,
    Button,
    Card,
    Col,
    Divider,
    Form,
    Input,
    Modal,
    Popconfirm,
    Row,
    Select,
    Space,
    Table,
    Tag,
    Tooltip,
    Typography,
    message,
} from 'antd';
import {
    ApiOutlined,
    CheckCircleOutlined,
    CopyOutlined,
    DeleteOutlined,
    EditOutlined,
    ExportOutlined,
    MinusCircleOutlined,
    PlusOutlined,
    SyncOutlined,
    ThunderboltOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { useTranslation } from 'react-i18next';
import { ConfigWrapper, LLMConfig, LLMThinkingMode } from '../../types/config';
import { fetchCustom } from '../../components/fetch';
import { LLMProviderType } from '../../utils/enums';

const { Text } = Typography;

interface ProviderPresetItem {
    provider: string;
    label: string;
    short_label: string;
    tag_color: string;
    default_base_url: string;
    default_model: string;
    api_type: 'openai' | 'anthropic';
    key_prefix_hint?: string;
    notes_vi?: string;
}

interface CatalogModelItem {
    provider: string;
    model_id: string;
    display_name: string;
    context_window: number | null;
    max_output_tokens: number | null;
    input_usd_per_1m: number;
    cached_input_usd_per_1m: number;
    output_usd_per_1m: number;
    supports_reasoning?: boolean | null;
    supports_vision?: boolean | null;
    is_recommended_default?: boolean;
    notes_vi?: string;
}

interface LlmCatalogResponse {
    defaults: {
        provider: string;
        model: string;
        thinking: LLMThinkingMode;
        reasoning_effort: string;
        reasoning_effort_when_on: string;
    };
    providers: ProviderPresetItem[];
    models: CatalogModelItem[];
    reasoning_efforts: string[];
}

interface RemoteModelItem {
    model_id: string;
    display_name: string;
    context_window: number | null;
    max_output_tokens: number | null;
    supports_reasoning?: boolean | null;
    input_usd_per_1m: number;
    cached_input_usd_per_1m: number;
    output_usd_per_1m: number;
    in_verified_catalog: boolean;
}

interface ProbeTestResult {
    ok: boolean;
    status_code: number;
    latency_ms: number;
    model_found: boolean | null;
    models_count: number;
    resolved_base_url: string;
    message: string;
}

interface LlmFormValues {
    name: string;
    description?: string;
    llm_configs: LLMConfig[];
}

const FALLBACK_CATALOG: LlmCatalogResponse = {
    defaults: {
        provider: LLMProviderType.OPENAI,
        model: 'gpt-6-luna',
        thinking: 'off',
        reasoning_effort: 'none',
        reasoning_effort_when_on: 'low',
    },
    providers: [
        {
            provider: 'openai',
            label: 'OpenAI (GPT-6 Luna / Sol / Terra / Astra & GPT-5.x)',
            short_label: 'OpenAI',
            tag_color: 'green',
            default_base_url: 'https://api.openai.com/v1',
            default_model: 'gpt-6-luna',
            api_type: 'openai',
            key_prefix_hint: 'sk-proj-...',
        },
        {
            provider: 'gemini',
            label: 'Google Gemini (Gemini 4 Argon / 3.8 Flash / 3.1 Pro)',
            short_label: 'Google Gemini',
            tag_color: 'blue',
            default_base_url: 'https://generativelanguage.googleapis.com/v1beta/openai',
            default_model: 'gemini-3.8-flash',
            api_type: 'openai',
        },
        {
            provider: 'claude',
            label: 'Anthropic Claude (Claude 5.5 Haiku / Sonnet / Opus)',
            short_label: 'Anthropic Claude',
            tag_color: 'volcano',
            default_base_url: 'https://api.anthropic.com/v1',
            default_model: 'claude-haiku-5-5',
            api_type: 'anthropic',
        },
        {
            provider: 'deepseek',
            label: 'DeepSeek (V4.1 Flash / V4 Pro / V3 Chat / R1)',
            short_label: 'DeepSeek',
            tag_color: 'purple',
            default_base_url: 'https://api.deepseek.com/v1',
            default_model: 'deepseek-v4.1-flash',
            api_type: 'openai',
        },
        {
            provider: 'xai',
            label: 'xAI Grok (Grok 4.7 / 4.6 / 4.3 / 4.20)',
            short_label: 'xAI Grok',
            tag_color: 'magenta',
            default_base_url: 'https://api.x.ai/v1',
            default_model: 'grok-4.7',
            api_type: 'openai',
        },
        {
            provider: 'qwen',
            label: 'Alibaba Qwen / DashScope',
            short_label: 'Alibaba Qwen',
            tag_color: 'orange',
            default_base_url: 'https://dashscope-intl.aliyuncs.com/compatible-mode/v1',
            default_model: 'qwen3.8-omni-flash',
            api_type: 'openai',
        },
        {
            provider: 'mistral',
            label: 'Mistral AI (Small 4 / Large 4 / Codestral)',
            short_label: 'Mistral AI',
            tag_color: 'gold',
            default_base_url: 'https://api.mistral.ai/v1',
            default_model: 'mistral-small-4-0',
            api_type: 'openai',
        },
        {
            provider: 'openai_compatible',
            label: 'OpenAI-Compatible (OpenRouter / LiteLLM / Groq)',
            short_label: 'OpenAI-Compatible',
            tag_color: 'cyan',
            default_base_url: 'https://openrouter.ai/api/v1',
            default_model: 'openai/gpt-6-luna',
            api_type: 'openai',
        },
        {
            provider: 'zhipuai',
            label: 'ZhipuAI (GLM-4)',
            short_label: 'ZhipuAI',
            tag_color: 'geekblue',
            default_base_url: 'https://open.bigmodel.cn/api/paas/v4',
            default_model: 'glm-4-flash',
            api_type: 'openai',
        },
        {
            provider: 'siliconflow',
            label: 'SiliconFlow',
            short_label: 'SiliconFlow',
            tag_color: 'lime',
            default_base_url: 'https://api.siliconflow.cn/v1',
            default_model: 'deepseek-ai/DeepSeek-V3',
            api_type: 'openai',
        },
        {
            provider: 'vllm',
            label: 'vLLM / Self-Hosted Local',
            short_label: 'vLLM / Local',
            tag_color: 'default',
            default_base_url: 'http://host.docker.internal:8000/v1',
            default_model: '',
            api_type: 'openai',
        },
    ],
    models: [
        {
            provider: 'openai',
            model_id: 'gpt-6-luna',
            display_name: 'OpenAI GPT-6 Luna (Mặc định khuyến nghị 1.05M)',
            context_window: 1050000,
            max_output_tokens: 128000,
            input_usd_per_1m: 0.1,
            cached_input_usd_per_1m: 0.01,
            output_usd_per_1m: 0.5,
            supports_reasoning: true,
            supports_vision: true,
            is_recommended_default: true,
            notes_vi: 'Mặc định ưu tiên: siêu tiết kiệm ($0.10/$0.50 per 1M), khuyến nghị tắt Reasoning (off).',
        },
        {
            provider: 'openai',
            model_id: 'gpt-5.4-mini',
            display_name: 'OpenAI GPT-5.4 Mini (400K Context)',
            context_window: 400000,
            max_output_tokens: 128000,
            input_usd_per_1m: 0.75,
            cached_input_usd_per_1m: 0.075,
            output_usd_per_1m: 4.5,
            supports_reasoning: true,
            supports_vision: true,
        },
    ],
    reasoning_efforts: ['minimal', 'low', 'medium', 'high', 'xhigh'],
};

function formatCtxWindow(tokens?: number | null): string {
    if (!tokens || tokens <= 0) return '—';
    if (tokens >= 1_000_000) {
        return `${(tokens / 1_000_000).toFixed(tokens % 1_000_000 === 0 ? 0 : 2)}M`;
    }
    return `${Math.round(tokens / 1000)}K`;
}

function getErrorText(error: unknown): string {
    if (error instanceof Error) return error.message;
    if (typeof error === 'string') return error;
    try {
        return JSON.stringify(error);
    } catch {
        return 'Unknown error';
    }
}

const LLM: React.FC = () => {
    const { t } = useTranslation();
    const [llms, setLLMs] = useState<ConfigWrapper<LLMConfig[]>[]>([]);
    const [catalog, setCatalog] = useState<LlmCatalogResponse>(FALLBACK_CATALOG);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [searchText, setSearchText] = useState('');
    const [isModalVisible, setIsModalVisible] = useState(false);
    const [currentLLM, setCurrentLLM] = useState<ConfigWrapper<LLMConfig[]> | null>(null);
    const [remoteModelsByEntry, setRemoteModelsByEntry] = useState<Record<number, RemoteModelItem[]>>({});
    const [fetchingModelsIdx, setFetchingModelsIdx] = useState<number | null>(null);
    const [testingIdx, setTestingIdx] = useState<number | null>(null);
    const [testResultsByEntry, setTestResultsByEntry] = useState<Record<number, ProbeTestResult>>({});
    const [form] = Form.useForm<LlmFormValues>();

    const watchedConfigs = Form.useWatch('llm_configs', form);

    const providerMap = useMemo(() => {
        const map = new Map<string, ProviderPresetItem>();
        for (const p of catalog.providers) {
            map.set(p.provider, p);
        }
        return map;
    }, [catalog.providers]);

    const modelsByProvider = useMemo(() => {
        const grouped = new Map<string, CatalogModelItem[]>();
        for (const m of catalog.models) {
            const list = grouped.get(m.provider) || [];
            list.push(m);
            grouped.set(m.provider, list);
        }
        return grouped;
    }, [catalog.models]);

    const findCatalogModel = useCallback(
        (provider: string | undefined, modelId: string | undefined): CatalogModelItem | undefined => {
            const clean = String(modelId || '').trim().toLowerCase();
            if (!clean) return undefined;
            const prov = String(provider || '').trim().toLowerCase();
            return (
                catalog.models.find(
                    (m) => m.provider.toLowerCase() === prov && m.model_id.toLowerCase() === clean
                ) ||
                catalog.models.find((m) => m.model_id.toLowerCase() === clean)
            );
        },
        [catalog.models]
    );

    const fetchInitialPayload = useCallback(async () => {
        const [cfgRes, catRes] = await Promise.all([
            fetchCustom('/api/llm-configs'),
            fetchCustom('/api/llm-catalog').catch(() => null),
        ]);
        if (!cfgRes.ok) {
            throw new Error(await cfgRes.text());
        }
        const cfgData = ((await cfgRes.json()) as { data?: ConfigWrapper<LLMConfig[]>[] }).data || [];
        let catData: LlmCatalogResponse | null = null;
        if (catRes && catRes.ok) {
            const catPayload = (await catRes.json()) as { data?: LlmCatalogResponse };
            if (catPayload.data?.providers?.length) {
                catData = catPayload.data;
            }
        }
        return { cfgData, catData };
    }, []);

    const loadData = useCallback(async () => {
        setLoading(true);
        try {
            const { cfgData, catData } = await fetchInitialPayload();
            setLLMs(cfgData);
            if (catData) {
                setCatalog(catData);
            }
        } catch (error) {
            message.error(t('llm.loadError', { error: getErrorText(error) }), 3);
        } finally {
            setLoading(false);
        }
    }, [fetchInitialPayload, t]);

    useEffect(() => {
        let active = true;
        async function initLoad() {
            try {
                const { cfgData, catData } = await fetchInitialPayload();
                if (!active) return;
                setLLMs(cfgData);
                if (catData) {
                    setCatalog(catData);
                }
            } catch (error) {
                if (active) {
                    message.error(t('llm.loadError', { error: getErrorText(error) }), 3);
                }
            } finally {
                if (active) {
                    setLoading(false);
                }
            }
        }
        void initLoad();
        return () => {
            active = false;
        };
    }, [fetchInitialPayload, t]);

    const defaultEntry = useCallback((): LLMConfig => {
        const defProv = catalog.defaults.provider || LLMProviderType.OPENAI;
        const preset = providerMap.get(defProv);
        return {
            provider: defProv,
            model: catalog.defaults.model || preset?.default_model || 'gpt-6-luna',
            coder_model: '',
            base_url: preset?.default_base_url || 'https://api.openai.com/v1',
            api_key: '',
            thinking: catalog.defaults.thinking || 'off',
            reasoning_effort: 'none',
            api_type: preset?.api_type || 'openai',
        };
    }, [catalog.defaults, providerMap]);

    const filteredLLMs = useMemo(() => {
        const q = searchText.trim().toLowerCase();
        if (!q) return llms;
        return llms.filter((llm) => {
            const nameMatch = llm.name.toLowerCase().includes(q);
            const descMatch = Boolean(llm.description && llm.description.toLowerCase().includes(q));
            const entryMatch = (llm.config || []).some(
                (c) =>
                    String(c.provider || '').toLowerCase().includes(q) ||
                    String(c.model || '').toLowerCase().includes(q)
            );
            return nameMatch || descMatch || entryMatch;
        });
    }, [llms, searchText]);

    const handleCreate = () => {
        setCurrentLLM(null);
        setRemoteModelsByEntry({});
        setTestResultsByEntry({});
        form.setFieldsValue({
            name: `LLM ${llms.length + 1} (GPT-6 Luna)`,
            description: 'Cấu hình AI mặc định ưu tiên gpt-6-luna (Reasoning: Off)',
            llm_configs: [defaultEntry()],
        });
        setIsModalVisible(true);
    };

    const normalizeForForm = (entries: LLMConfig[]): LLMConfig[] =>
        (entries.length > 0 ? entries : [defaultEntry()]).map((entry) => {
            const prov = String(entry.provider || catalog.defaults.provider || 'openai');
            const preset = providerMap.get(prov);
            const thinking: LLMThinkingMode =
                entry.thinking === 'on' || entry.thinking === 'inherit' || entry.thinking === 'off'
                    ? entry.thinking
                    : 'off';
            return {
                ...entry,
                provider: prov,
                model: entry.model || preset?.default_model || catalog.defaults.model,
                coder_model: entry.coder_model || '',
                base_url: entry.base_url || preset?.default_base_url || '',
                thinking,
                reasoning_effort:
                    entry.reasoning_effort || (thinking === 'on' ? 'low' : 'none'),
                api_type: entry.api_type || preset?.api_type || 'openai',
            };
        });

    const handleEdit = (llm: ConfigWrapper<LLMConfig[]>) => {
        setCurrentLLM(llm);
        setRemoteModelsByEntry({});
        setTestResultsByEntry({});
        form.setFieldsValue({
            name: llm.name,
            description: llm.description || '',
            llm_configs: normalizeForForm(llm.config || []),
        });
        setIsModalVisible(true);
    };

    const handleDuplicate = (llm: ConfigWrapper<LLMConfig[]>) => {
        setCurrentLLM(null);
        setRemoteModelsByEntry({});
        setTestResultsByEntry({});
        form.setFieldsValue({
            name: `${llm.name} (Copy)`,
            description: llm.description || '',
            llm_configs: normalizeForForm(llm.config || []).map((item) => ({
                ...item,
                api_key: '',
            })),
        });
        setIsModalVisible(true);
    };

    const handleDelete = async (id: string) => {
        try {
            const res = await fetchCustom(`/api/llm-configs/${id}`, { method: 'DELETE' });
            if (!res.ok) {
                throw new Error(await res.text());
            }
            message.success(t('llm.deleteSuccess'));
            void loadData();
        } catch (error) {
            message.error(t('llm.deleteError', { error: getErrorText(error) }), 3);
        }
    };

    const handleExport = (llm: ConfigWrapper<LLMConfig[]>) => {
        const dataStr = JSON.stringify(llm, null, 2);
        const dataUri = `data:application/json;charset=utf-8,${encodeURIComponent(dataStr)}`;
        const linkElement = document.createElement('a');
        linkElement.setAttribute('href', dataUri);
        linkElement.setAttribute('download', `${llm.name.replace(/\s+/g, '_')}_llm.json`);
        linkElement.click();
    };

    const handleModalOk = async () => {
        try {
            const values = await form.validateFields();
            setSaving(true);
            const configData = {
                name: values.name,
                description: values.description || '',
                config: (values.llm_configs || []).map((item) => {
                    const thinking: LLMThinkingMode = item.thinking || 'off';
                    return {
                        provider: item.provider,
                        model: String(item.model || '').trim(),
                        coder_model: String(item.coder_model || '').trim(),
                        base_url: String(item.base_url || '').trim(),
                        api_key: String(item.api_key || ''),
                        thinking,
                        reasoning_effort:
                            thinking === 'on'
                                ? item.reasoning_effort && item.reasoning_effort !== 'none'
                                    ? item.reasoning_effort
                                    : 'low'
                                : 'none',
                        api_type:
                            providerMap.get(String(item.provider))?.api_type ||
                            item.api_type ||
                            'openai',
                    };
                }),
            };

            const url = currentLLM?.id ? `/api/llm-configs/${currentLLM.id}` : '/api/llm-configs';
            const res = await fetchCustom(url, {
                method: currentLLM?.id ? 'PUT' : 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(configData),
            });
            if (!res.ok) {
                throw new Error(await res.text());
            }
            message.success(t(currentLLM ? 'llm.updateSuccess' : 'llm.createSuccess'));
            setIsModalVisible(false);
            void loadData();
        } catch (error) {
            if (error && typeof error === 'object' && 'errorFields' in error) {
                return;
            }
            message.error(t(currentLLM ? 'llm.updateError' : 'llm.createError', { error: getErrorText(error) }), 4);
        } finally {
            setSaving(false);
        }
    };

    const handleFetchModels = async (entryIndex: number) => {
        const entry = form.getFieldValue(['llm_configs', entryIndex]) as LLMConfig | undefined;
        if (!entry) return;
        setFetchingModelsIdx(entryIndex);
        try {
            const res = await fetchCustom('/api/llm-configs/fetch-models', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    provider: entry.provider || 'openai',
                    base_url: entry.base_url || '',
                    api_key: entry.api_key || '',
                    model: entry.model || '',
                    config_id: currentLLM?.id || null,
                    entry_index: entryIndex,
                }),
            });
            if (!res.ok) {
                throw new Error(await res.text());
            }
            const payload = (await res.json()) as {
                data?: { models?: RemoteModelItem[]; resolved_base_url?: string };
            };
            const fetched = payload.data?.models || [];
            setRemoteModelsByEntry((prev) => ({ ...prev, [entryIndex]: fetched }));
            message.success(`Đã đồng bộ ${fetched.length} mô hình từ ${payload.data?.resolved_base_url || 'endpoint'}.`);
        } catch (error) {
            message.error(`Không thể đồng bộ mô hình: ${getErrorText(error)}`, 4);
        } finally {
            setFetchingModelsIdx(null);
        }
    };

    const handleTestConnection = async (entryIndex: number) => {
        const entry = form.getFieldValue(['llm_configs', entryIndex]) as LLMConfig | undefined;
        if (!entry) return;
        setTestingIdx(entryIndex);
        try {
            const res = await fetchCustom('/api/llm-configs/test-connection', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    provider: entry.provider || 'openai',
                    base_url: entry.base_url || '',
                    api_key: entry.api_key || '',
                    model: entry.model || '',
                    config_id: currentLLM?.id || null,
                    entry_index: entryIndex,
                }),
            });
            if (!res.ok) {
                throw new Error(await res.text());
            }
            const result = ((await res.json()) as { data?: ProbeTestResult }).data;
            if (result) {
                setTestResultsByEntry((prev) => ({ ...prev, [entryIndex]: result }));
                if (result.ok) {
                    message.success(result.message);
                } else {
                    message.warning(result.message);
                }
            }
        } catch (error) {
            message.error(`Kiểm tra kết nối thất bại: ${getErrorText(error)}`, 4);
        } finally {
            setTestingIdx(null);
        }
    };

    const columns = [
        {
            title: t('common.name'),
            dataIndex: 'name',
            key: 'name',
            render: (text: string, record: ConfigWrapper<LLMConfig[]>) => (
                <div>
                    <Text strong>{text}</Text>
                    {record.description ? (
                        <div>
                            <Text type="secondary" style={{ fontSize: 12 }}>
                                {record.description}
                            </Text>
                        </div>
                    ) : null}
                </div>
            ),
        },
        {
            title: t('llm.colProviderModel'),
            key: 'provider_model',
            render: (_: unknown, record: ConfigWrapper<LLMConfig[]>) => {
                const primary = record.config?.[0];
                if (!primary) return <Text type="secondary">—</Text>;
                const preset = providerMap.get(String(primary.provider));
                return (
                    <Space direction="vertical" size={2}>
                        <Space wrap size={4}>
                            <Tag color={preset?.tag_color || 'blue'} style={{ margin: 0 }}>
                                {preset?.short_label || primary.provider}
                            </Tag>
                            <Tag color="geekblue" style={{ margin: 0 }}>
                                {primary.model}
                            </Tag>
                            {primary.coder_model ? (
                                <Tag color="cyan" style={{ margin: 0 }}>
                                    Coder: {primary.coder_model}
                                </Tag>
                            ) : null}
                        </Space>
                        <Text type="secondary" style={{ fontSize: 11 }}>
                            {primary.resolved_base_url || primary.base_url || preset?.default_base_url}
                        </Text>
                    </Space>
                );
            },
        },
        {
            title: t('llm.colReasoning'),
            key: 'reasoning',
            render: (_: unknown, record: ConfigWrapper<LLMConfig[]>) => {
                const primary = record.config?.[0];
                const thinking = primary?.thinking || 'off';
                if (thinking === 'on') {
                    return (
                        <Tag color="purple" icon={<ThunderboltOutlined />}>
                            On ({primary?.reasoning_effort || 'low'})
                        </Tag>
                    );
                }
                if (thinking === 'inherit') {
                    return <Tag color="default">Inherit</Tag>;
                }
                return <Tag color="green">Off (Tắt)</Tag>;
            },
        },
        {
            title: t('llm.colPricing'),
            key: 'pricing',
            render: (_: unknown, record: ConfigWrapper<LLMConfig[]>) => {
                const primary = record.config?.[0];
                const p = primary?.pricing;
                if (!p) return <Text type="secondary">—</Text>;
                return (
                    <Text style={{ fontSize: 12 }}>
                        In <b>${p.input_usd_per_1m}</b> · Cache <b>${p.cached_input_usd_per_1m}</b> · Out <b>${p.output_usd_per_1m}</b>
                    </Text>
                );
            },
        },
        {
            title: t('common.lastUpdated'),
            dataIndex: 'updated_at',
            key: 'updated_at',
            render: (text: string) => (text ? dayjs(text).format('YYYY-MM-DD HH:mm') : '—'),
        },
        {
            title: t('common.actions'),
            key: 'action',
            render: (_: unknown, record: ConfigWrapper<LLMConfig[]>) => (
                <Space size="small">
                    {(record.tenant_id ?? '') !== '' && (
                        <Tooltip title={t('common.edit')}>
                            <Button icon={<EditOutlined />} size="small" onClick={() => handleEdit(record)} />
                        </Tooltip>
                    )}
                    <Tooltip title={t('common.duplicate')}>
                        <Button icon={<CopyOutlined />} size="small" onClick={() => handleDuplicate(record)} />
                    </Tooltip>
                    <Tooltip title={t('common.export')}>
                        <Button icon={<ExportOutlined />} size="small" onClick={() => handleExport(record)} />
                    </Tooltip>
                    {(record.tenant_id ?? '') !== '' && record.id && (
                        <Tooltip title={t('common.delete')}>
                            <Popconfirm
                                title={t('common.deleteConfirm')}
                                onConfirm={() => void handleDelete(record.id!)}
                                okText={t('common.submit')}
                                cancelText={t('common.cancel')}
                            >
                                <Button icon={<DeleteOutlined />} size="small" danger />
                            </Popconfirm>
                        </Tooltip>
                    )}
                </Space>
            ),
        },
    ];

    return (
        <Card
            title={
                <Space wrap>
                    <span>{t('llm.title')}</span>
                    <Tag color="green">Mặc định ưu tiên: {catalog.defaults.model}</Tag>
                    <Tag color="blue">Reasoning: {catalog.defaults.thinking.toUpperCase()}</Tag>
                    <Tag color="default">{catalog.providers.length} Nhà cung cấp · {catalog.models.length}+ Mô hình</Tag>
                </Space>
            }
            extra={
                <Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>
                    {t('llm.createNew')}
                </Button>
            }
        >
            <Input.Search
                placeholder={t('llm.searchPlaceholder')}
                onChange={(e) => setSearchText(e.target.value)}
                style={{ marginBottom: 16 }}
                allowClear
            />

            <Table
                columns={columns}
                dataSource={filteredLLMs}
                rowKey="id"
                loading={loading}
                scroll={{ x: 'max-content' }}
                pagination={{ pageSize: 10 }}
            />

            <Modal
                title={currentLLM ? t('llm.editTitle') : t('llm.createTitle')}
                open={isModalVisible}
                onOk={() => void handleModalOk()}
                onCancel={() => setIsModalVisible(false)}
                confirmLoading={saving}
                width="82vw"
                destroyOnHidden
            >
                <Form form={form} layout="vertical">
                    <Card size="small" title={t('llm.metadataTitle')} style={{ marginBottom: 12 }}>
                        <Row gutter={16}>
                            <Col xs={24} md={8}>
                                <Form.Item
                                    name="name"
                                    label={t('common.name')}
                                    rules={[{ required: true, message: t('common.nameRequired') }]}
                                >
                                    <Input placeholder={t('common.namePlaceholder')} />
                                </Form.Item>
                            </Col>
                            <Col xs={24} md={16}>
                                <Form.Item name="description" label={t('common.description')}>
                                    <Input.TextArea rows={1} placeholder={t('common.descriptionPlaceholder')} />
                                </Form.Item>
                            </Col>
                        </Row>
                    </Card>

                    <Card size="small" title={t('llm.settingsTitle')}>
                        <Form.List name="llm_configs">
                            {(fields, { add, remove }) => (
                                <>
                                    {fields.map(({ key, name, ...restField }) => {
                                        const entryValue = watchedConfigs?.[name];
                                        const provKey = String(entryValue?.provider || catalog.defaults.provider || 'openai');
                                        const preset = providerMap.get(provKey);
                                        const thinkingMode: LLMThinkingMode = entryValue?.thinking || 'off';
                                        const catalogModels = modelsByProvider.get(provKey) || [];
                                        const remoteModels = remoteModelsByEntry[name] || [];

                                        const mergedModelMap = new Map<
                                            string,
                                            {
                                                model_id: string;
                                                display_name: string;
                                                context_window: number | null;
                                                input_usd_per_1m: number;
                                                output_usd_per_1m: number;
                                                is_recommended?: boolean;
                                            }
                                        >();
                                        for (const m of catalogModels) {
                                            mergedModelMap.set(m.model_id, {
                                                model_id: m.model_id,
                                                display_name: m.display_name,
                                                context_window: m.context_window,
                                                input_usd_per_1m: m.input_usd_per_1m,
                                                output_usd_per_1m: m.output_usd_per_1m,
                                                is_recommended: m.is_recommended_default,
                                            });
                                        }
                                        for (const rm of remoteModels) {
                                            if (!mergedModelMap.has(rm.model_id)) {
                                                mergedModelMap.set(rm.model_id, {
                                                    model_id: rm.model_id,
                                                    display_name: rm.display_name || rm.model_id,
                                                    context_window: rm.context_window,
                                                    input_usd_per_1m: rm.input_usd_per_1m,
                                                    output_usd_per_1m: rm.output_usd_per_1m,
                                                });
                                            }
                                        }

                                        const autoCompleteOptions = Array.from(mergedModelMap.values()).map((m) => ({
                                            value: m.model_id,
                                            label: (
                                                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                                                    <span>
                                                        <Text strong={Boolean(m.is_recommended)}>{m.model_id}</Text>{' '}
                                                        <Text type="secondary" style={{ fontSize: 12 }}>
                                                            ({formatCtxWindow(m.context_window)})
                                                        </Text>
                                                    </span>
                                                    <Text type="secondary" style={{ fontSize: 11 }}>
                                                        ${m.input_usd_per_1m}/${m.output_usd_per_1m}
                                                    </Text>
                                                </div>
                                            ),
                                        }));

                                        const selectedModelInfo = findCatalogModel(provKey, entryValue?.model);
                                        const testResult = testResultsByEntry[name];

                                        return (
                                            <Card
                                                key={key}
                                                size="small"
                                                title={
                                                    <Space>
                                                        <span>{`${t('llm.providerTitle')} #${name + 1}`}</span>
                                                        {preset ? (
                                                            <Tag color={preset.tag_color}>{preset.short_label}</Tag>
                                                        ) : null}
                                                    </Space>
                                                }
                                                style={{ marginBottom: 12 }}
                                                extra={
                                                    <Space wrap size={6}>
                                                        <Button
                                                            size="small"
                                                            icon={<SyncOutlined spin={fetchingModelsIdx === name} />}
                                                            loading={fetchingModelsIdx === name}
                                                            onClick={() => void handleFetchModels(name)}
                                                        >
                                                            {t('llm.fetchModels')}
                                                        </Button>
                                                        <Button
                                                            size="small"
                                                            type="default"
                                                            icon={<ApiOutlined />}
                                                            loading={testingIdx === name}
                                                            onClick={() => void handleTestConnection(name)}
                                                        >
                                                            {t('llm.testConnection')}
                                                        </Button>
                                                        {fields.length > 1 && (
                                                            <MinusCircleOutlined
                                                                style={{ color: '#ff4d4f', cursor: 'pointer' }}
                                                                onClick={() => remove(name)}
                                                            />
                                                        )}
                                                    </Space>
                                                }
                                            >
                                                <Row gutter={12}>
                                                    <Col xs={24} md={8}>
                                                        <Form.Item
                                                            {...restField}
                                                            name={[name, 'provider']}
                                                            label={t('llm.providerLabel')}
                                                            rules={[{ required: true, message: t('llm.providerPlaceholder') }]}
                                                        >
                                                            <Select
                                                                showSearch
                                                                optionFilterProp="label"
                                                                placeholder={t('llm.providerPlaceholder')}
                                                                options={catalog.providers.map((p) => ({
                                                                    value: p.provider,
                                                                    label: p.label,
                                                                }))}
                                                                onChange={(value: string) => {
                                                                    const nextPreset = providerMap.get(value);
                                                                    const currentConfigs = form.getFieldValue('llm_configs') || [];
                                                                    const prevItem = currentConfigs[name] || {};
                                                                    const updated = [...currentConfigs];
                                                                    updated[name] = {
                                                                        ...prevItem,
                                                                        provider: value,
                                                                        base_url: nextPreset?.default_base_url || '',
                                                                        model: nextPreset?.default_model || '',
                                                                        api_type: nextPreset?.api_type || 'openai',
                                                                    };
                                                                    form.setFieldsValue({ llm_configs: updated });
                                                                }}
                                                            />
                                                        </Form.Item>
                                                    </Col>

                                                    <Col xs={24} md={8}>
                                                        <Form.Item
                                                            {...restField}
                                                            name={[name, 'model']}
                                                            label={t('llm.model')}
                                                            rules={[
                                                                {
                                                                    required: true,
                                                                    message:
                                                                        provKey === LLMProviderType.VLLM
                                                                            ? t('llm.vllmModelPlaceholder')
                                                                            : t('llm.modelPlaceholder'),
                                                                },
                                                            ]}
                                                        >
                                                            <AutoComplete
                                                                allowClear
                                                                placeholder={
                                                                    provKey === LLMProviderType.VLLM
                                                                        ? t('llm.vllmModelPlaceholder')
                                                                        : t('llm.modelPlaceholder')
                                                                }
                                                                options={autoCompleteOptions}
                                                                filterOption={(inputValue, option) =>
                                                                    String(option?.value || '')
                                                                        .toLowerCase()
                                                                        .includes(inputValue.toLowerCase())
                                                                }
                                                            />
                                                        </Form.Item>
                                                    </Col>

                                                    <Col xs={24} md={8}>
                                                        <Form.Item
                                                            {...restField}
                                                            name={[name, 'api_key']}
                                                            label={t('llm.apiKey')}
                                                            rules={[
                                                                {
                                                                    required: !currentLLM && provKey !== LLMProviderType.VLLM,
                                                                    message: t('llm.apiKeyPlaceholder'),
                                                                },
                                                            ]}
                                                        >
                                                            <Input.Password
                                                                placeholder={
                                                                    currentLLM
                                                                        ? 'Giữ nguyên (••••••) hoặc nhập key mới'
                                                                        : preset?.key_prefix_hint || t('llm.apiKeyPlaceholder')
                                                                }
                                                            />
                                                        </Form.Item>
                                                    </Col>
                                                </Row>

                                                <Row gutter={12}>
                                                    <Col xs={24} md={10}>
                                                        <Form.Item
                                                            {...restField}
                                                            name={[name, 'base_url']}
                                                            label={t('llm.baseUrl')}
                                                        >
                                                            <Input
                                                                placeholder={
                                                                    preset?.default_base_url || t('llm.baseUrlPlaceholder')
                                                                }
                                                            />
                                                        </Form.Item>
                                                    </Col>

                                                    <Col xs={24} md={7}>
                                                        <Form.Item
                                                            {...restField}
                                                            name={[name, 'thinking']}
                                                            label={t('llm.thinkingLabel')}
                                                        >
                                                            <Select
                                                                options={[
                                                                    { value: 'off', label: t('llm.thinkingOff') },
                                                                    { value: 'on', label: t('llm.thinkingOn') },
                                                                    { value: 'inherit', label: t('llm.thinkingInherit') },
                                                                ]}
                                                                onChange={(val: LLMThinkingMode) => {
                                                                    const currentConfigs = form.getFieldValue('llm_configs') || [];
                                                                    const prevItem = currentConfigs[name] || {};
                                                                    const updated = [...currentConfigs];
                                                                    updated[name] = {
                                                                        ...prevItem,
                                                                        thinking: val,
                                                                        reasoning_effort:
                                                                            val === 'on'
                                                                                ? prevItem.reasoning_effort && prevItem.reasoning_effort !== 'none'
                                                                                    ? prevItem.reasoning_effort
                                                                                    : 'low'
                                                                                : 'none',
                                                                    };
                                                                    form.setFieldsValue({ llm_configs: updated });
                                                                }}
                                                            />
                                                        </Form.Item>
                                                    </Col>

                                                    {thinkingMode === 'on' ? (
                                                        <Col xs={24} md={7}>
                                                            <Form.Item
                                                                {...restField}
                                                                name={[name, 'reasoning_effort']}
                                                                label={t('llm.reasoningEffortLabel')}
                                                            >
                                                                <Select
                                                                    options={catalog.reasoning_efforts.map((eff) => ({
                                                                        value: eff,
                                                                        label:
                                                                            eff === 'low'
                                                                                ? 'low (Khuyên dùng)'
                                                                                : eff,
                                                                    }))}
                                                                />
                                                            </Form.Item>
                                                        </Col>
                                                    ) : (
                                                        <Col xs={24} md={7}>
                                                            <Form.Item
                                                                {...restField}
                                                                name={[name, 'coder_model']}
                                                                label={t('llm.coderModelLabel')}
                                                            >
                                                                <AutoComplete
                                                                    allowClear
                                                                    placeholder={t('llm.coderModelPlaceholder')}
                                                                    options={autoCompleteOptions}
                                                                    filterOption={(inputValue, option) =>
                                                                        String(option?.value || '')
                                                                            .toLowerCase()
                                                                            .includes(inputValue.toLowerCase())
                                                                    }
                                                                />
                                                            </Form.Item>
                                                        </Col>
                                                    )}
                                                </Row>

                                                {thinkingMode === 'on' && (
                                                    <Row gutter={12}>
                                                        <Col xs={24} md={10}>
                                                            <Form.Item
                                                                {...restField}
                                                                name={[name, 'coder_model']}
                                                                label={t('llm.coderModelLabel')}
                                                            >
                                                                <AutoComplete
                                                                    allowClear
                                                                    placeholder={t('llm.coderModelPlaceholder')}
                                                                    options={autoCompleteOptions}
                                                                    filterOption={(inputValue, option) =>
                                                                        String(option?.value || '')
                                                                            .toLowerCase()
                                                                            .includes(inputValue.toLowerCase())
                                                                    }
                                                                />
                                                            </Form.Item>
                                                        </Col>
                                                    </Row>
                                                )}

                                                {catalogModels.length > 0 && (
                                                    <div style={{ marginBottom: 8 }}>
                                                        <Text type="secondary" style={{ fontSize: 12, marginRight: 6 }}>
                                                            {t('llm.quickPicks')} ({preset?.short_label || provKey}):
                                                        </Text>
                                                        <Space wrap size={4}>
                                                            {catalogModels.slice(0, 6).map((m) => (
                                                                <Tag
                                                                    key={m.model_id}
                                                                    color={entryValue?.model === m.model_id ? 'green' : 'geekblue'}
                                                                    style={{ cursor: 'pointer', margin: 0 }}
                                                                    onClick={() => {
                                                                        const currentConfigs = form.getFieldValue('llm_configs') || [];
                                                                        const prevItem = currentConfigs[name] || {};
                                                                        const updated = [...currentConfigs];
                                                                        updated[name] = {
                                                                            ...prevItem,
                                                                            model: m.model_id,
                                                                        };
                                                                        form.setFieldsValue({ llm_configs: updated });
                                                                    }}
                                                                >
                                                                    {m.model_id} (${m.input_usd_per_1m}/${m.output_usd_per_1m})
                                                                </Tag>
                                                            ))}
                                                        </Space>
                                                    </div>
                                                )}

                                                {selectedModelInfo && (
                                                    <Alert
                                                        type="info"
                                                        showIcon
                                                        icon={<CheckCircleOutlined />}
                                                        style={{ marginTop: 6 }}
                                                        message={
                                                            <span>
                                                                <b>{selectedModelInfo.display_name}</b> · Context{' '}
                                                                <b>{formatCtxWindow(selectedModelInfo.context_window)}</b> · Max Out{' '}
                                                                <b>{formatCtxWindow(selectedModelInfo.max_output_tokens)}</b> ·{' '}
                                                                In <b>${selectedModelInfo.input_usd_per_1m}</b> / Cache{' '}
                                                                <b>${selectedModelInfo.cached_input_usd_per_1m}</b> / Out{' '}
                                                                <b>${selectedModelInfo.output_usd_per_1m}</b> per 1M tokens
                                                            </span>
                                                        }
                                                        description={selectedModelInfo.notes_vi || preset?.notes_vi}
                                                    />
                                                )}

                                                {testResult && (
                                                    <Alert
                                                        type={testResult.ok ? 'success' : 'warning'}
                                                        showIcon
                                                        style={{ marginTop: 8 }}
                                                        message={testResult.message}
                                                    />
                                                )}
                                            </Card>
                                        );
                                    })}
                                    <Divider style={{ margin: '8px 0' }} />
                                    <Form.Item style={{ marginBottom: 0 }}>
                                        <Button
                                            type="dashed"
                                            onClick={() => add(defaultEntry())}
                                            block
                                            icon={<PlusOutlined />}
                                        >
                                            {t('llm.addProvider')}
                                        </Button>
                                    </Form.Item>
                                </>
                            )}
                        </Form.List>
                    </Card>
                </Form>
            </Modal>
        </Card>
    );
};

export default LLM;
