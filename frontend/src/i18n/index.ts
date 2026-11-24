import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';

// Import translations
import viCommon from './locales/vi/common';
import enCommon from './locales/en/common';
import zhCommon from './locales/zh/common';
import viLLM from './locales/vi/llm';
import enLLM from './locales/en/llm';
import zhLLM from './locales/zh/llm';
import viHome from './locales/vi/home';
import enHome from './locales/en/home';
import zhHome from './locales/zh/home';
import viSurvey from './locales/vi/survey';
import enSurvey from './locales/en/survey';
import zhSurvey from './locales/zh/survey';
import viConsole from './locales/vi/console';
import enConsole from './locales/en/console';
import zhConsole from './locales/zh/console';
import viReplay from './locales/vi/replay';
import enReplay from './locales/en/replay';
import zhReplay from './locales/zh/replay';
import viBill from './locales/vi/bill';
import enBill from './locales/en/bill';
import zhBill from './locales/zh/bill';
import viAgent from './locales/vi/agent';
import enAgent from './locales/en/agent';
import zhAgent from './locales/zh/agent';
import viMap from './locales/vi/map';
import enMap from './locales/en/map';
import zhMap from './locales/zh/map';
import viWorkflow from './locales/vi/workflow';
import enWorkflow from './locales/en/workflow';
import zhWorkflow from './locales/zh/workflow';
import viTemplate from './locales/vi/template';
import enTemplate from './locales/en/template';
import zhTemplate from './locales/zh/template';
import viProfile from './locales/vi/profile';
import enProfile from './locales/en/profile';
import zhProfile from './locales/zh/profile';
import viExperiment from './locales/vi/experiment';
import enExperiment from './locales/en/experiment';
import zhExperiment from './locales/zh/experiment';
import viSkill from './locales/vi/skill';
import enSkill from './locales/en/skill';
import zhSkill from './locales/zh/skill';

// Combine translations
const resources = {
    vi: {
        translation: {
            ...viCommon,
            llm: viLLM,
            home: viHome,
            survey: viSurvey,
            console: viConsole,
            replay: viReplay,
            bill: viBill,
            agent: viAgent,
            map: viMap,
            workflow: viWorkflow,
            template: viTemplate,
            profile: viProfile,
            experiment: viExperiment,
            skill: viSkill,
        }
    },
    en: {
        translation: {
            ...enCommon,
            llm: enLLM,
            home: enHome,
            survey: enSurvey,
            console: enConsole,
            replay: enReplay,
            bill: enBill,
            agent: enAgent,
            map: enMap,
            workflow: enWorkflow,
            template: enTemplate,
            profile: enProfile,
            experiment: enExperiment,
            skill: enSkill,
        }
    },
    zh: {
        translation: {
            ...zhCommon,
            llm: zhLLM,
            home: zhHome,
            survey: zhSurvey,
            console: zhConsole,
            replay: zhReplay,
            bill: zhBill,
            agent: zhAgent,
            map: zhMap,
            workflow: zhWorkflow,
            template: zhTemplate,
            profile: zhProfile,
            experiment: zhExperiment,
            skill: zhSkill,
        }
    }
};

const savedLng = typeof window !== 'undefined' ? window.localStorage.getItem('i18nextLng') : null;
const initialLng = savedLng && ['vi', 'en', 'zh'].includes(savedLng.split('-')[0])
    ? savedLng.split('-')[0]
    : 'vi';

i18n
    .use(LanguageDetector)
    .use(initReactI18next)
    .init({
        debug: false,
        lng: initialLng,
        fallbackLng: 'vi',
        supportedLngs: ['vi', 'en', 'zh'],
        detection: {
            order: ['localStorage'],
            caches: ['localStorage'],
        },
        interpolation: {
            escapeValue: false,
        },
        resources
    });

export default i18n;
