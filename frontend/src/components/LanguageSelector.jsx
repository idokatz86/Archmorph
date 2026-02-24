import React from 'react';
import { useTranslation } from 'react-i18next';
import { Globe } from 'lucide-react';

const LANGUAGES = [
  { code: 'en', label: 'English', flag: '🇺🇸' },
  { code: 'es', label: 'Español', flag: '🇪🇸' },
  { code: 'fr', label: 'Français', flag: '🇫🇷' },
];

export default function LanguageSelector() {
  const { i18n } = useTranslation();

  return (
    <div className="relative flex items-center gap-1">
      <Globe className="w-3.5 h-3.5 text-text-muted" />
      <select
        value={i18n.language?.split('-')[0] || 'en'}
        onChange={(e) => i18n.changeLanguage(e.target.value)}
        className="text-xs bg-transparent border-none text-text-secondary cursor-pointer focus:outline-none appearance-none pr-4"
        aria-label="Select language"
      >
        {LANGUAGES.map((lang) => (
          <option key={lang.code} value={lang.code}>
            {lang.flag} {lang.label}
          </option>
        ))}
      </select>
    </div>
  );
}
