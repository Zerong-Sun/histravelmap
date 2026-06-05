import { useFilters } from "@/api/hooks";
import { useState, useRef, useEffect } from "react";
import { SlidersHorizontal, Globe2, X, RotateCcw } from "lucide-react";
import { getLanguage, setLanguage as storeLanguage, type Language } from "@/lib/language";

export interface FilterState {
  dynasty: string;
  locationType: string;
  era: string;
}

interface FilterPanelProps {
  onChange: (filters: FilterState) => void;
  onLanguageChange?: (lang: Language) => void;
}

export function FilterPanel({ onChange, onLanguageChange }: FilterPanelProps) {
  const { data: filterOptions } = useFilters();
  const [filters, setFilters] = useState<FilterState>({ dynasty: "", locationType: "", era: "" });
  const [open, setOpen] = useState(false);
  const [lang, setLang] = useState<Language>(getLanguage);
  const panelRef = useRef<HTMLDivElement>(null);

  const activeCount = Object.values(filters).filter(Boolean).length;

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const update = (key: keyof FilterState, value: string) => {
    const next = { ...filters, [key]: value };
    setFilters(next);
    onChange(next);
  };

  const reset = () => {
    const empty = { dynasty: "", locationType: "", era: "" };
    setFilters(empty);
    onChange(empty);
  };

  const toggleLanguage = () => {
    const next: Language = lang === 'zh' ? 'en' : 'zh';
    setLang(next);
    storeLanguage(next);
    onLanguageChange?.(next);
  };

  if (!filterOptions) return null;

  return (
    <div ref={panelRef} className="relative flex items-center gap-2">
      {/* Language Toggle */}
      <button
        onClick={toggleLanguage}
        className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm transition-all duration-200 hover:scale-105"
        style={{
          background: 'rgba(255,255,255,0.08)',
          border: '1px solid rgba(255,255,255,0.1)',
          color: 'rgba(255,255,255,0.8)',
        }}
        title={lang === 'zh' ? 'Switch to English' : '切换到中文'}
      >
        <Globe2 className="h-3.5 w-3.5" />
        <span className="text-xs font-medium">{lang === 'zh' ? '中/EN' : 'EN/中'}</span>
      </button>

      {/* Filter Button */}
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm transition-all duration-200 hover:scale-105 relative"
        style={{
          background: open ? 'rgba(201,168,76,0.2)' : 'rgba(255,255,255,0.08)',
          border: open ? '1px solid rgba(201,168,76,0.4)' : '1px solid rgba(255,255,255,0.1)',
          color: open ? '#e8d5a0' : 'rgba(255,255,255,0.8)',
        }}
      >
        <SlidersHorizontal className="h-3.5 w-3.5" />
        <span className="text-xs font-medium">筛选</span>
        {activeCount > 0 && (
          <span className="absolute -top-1.5 -right-1.5 w-4 h-4 rounded-full text-[10px] font-bold flex items-center justify-center text-white"
            style={{ background: 'linear-gradient(135deg, #c9a84c, #e8b84c)' }}>
            {activeCount}
          </span>
        )}
      </button>

      {/* Filter Panel Dropdown */}
      {open && (
        <div
          className="absolute top-full right-0 mt-2 w-72 rounded-xl overflow-hidden animate-fade-in-down z-50"
          style={{
            background: 'rgba(34, 34, 64, 0.95)',
            backdropFilter: 'blur(16px)',
            border: '1px solid rgba(201,168,76,0.2)',
            boxShadow: '0 12px 40px rgba(0,0,0,0.3)',
          }}
        >
          <div className="p-4 space-y-4">
            {/* Dynasty */}
            <div>
              <label className="block text-[11px] font-medium text-amber-400/70 uppercase tracking-wider mb-1.5">朝代</label>
              <select
                value={filters.dynasty}
                onChange={(e) => update("dynasty", e.target.value)}
                className="w-full rounded-lg px-3 py-2 text-sm outline-none transition-all focus:ring-1 focus:ring-amber-500/50"
                style={{
                  background: 'rgba(255,255,255,0.06)',
                  border: '1px solid rgba(255,255,255,0.1)',
                  color: 'white',
                }}
              >
                <option value="" style={{ background: '#222240' }}>全部</option>
                {filterOptions.dynasties.map((d) => (
                  <option key={d} value={d} style={{ background: '#222240' }}>{d}</option>
                ))}
              </select>
            </div>

            {/* Location Type */}
            <div>
              <label className="block text-[11px] font-medium text-amber-400/70 uppercase tracking-wider mb-1.5">地点类型</label>
              <select
                value={filters.locationType}
                onChange={(e) => update("locationType", e.target.value)}
                className="w-full rounded-lg px-3 py-2 text-sm outline-none transition-all focus:ring-1 focus:ring-amber-500/50"
                style={{
                  background: 'rgba(255,255,255,0.06)',
                  border: '1px solid rgba(255,255,255,0.1)',
                  color: 'white',
                }}
              >
                <option value="" style={{ background: '#222240' }}>全部</option>
                {filterOptions.location_types.map((t) => (
                  <option key={t} value={t} style={{ background: '#222240' }}>{t}</option>
                ))}
              </select>
            </div>

            {/* Era */}
            <div>
              <label className="block text-[11px] font-medium text-amber-400/70 uppercase tracking-wider mb-1.5">时代背景</label>
              <select
                value={filters.era}
                onChange={(e) => update("era", e.target.value)}
                className="w-full rounded-lg px-3 py-2 text-sm outline-none transition-all focus:ring-1 focus:ring-amber-500/50"
                style={{
                  background: 'rgba(255,255,255,0.06)',
                  border: '1px solid rgba(255,255,255,0.1)',
                  color: 'white',
                }}
              >
                <option value="" style={{ background: '#222240' }}>全部</option>
                {filterOptions.era_contexts.map((e) => (
                  <option key={e} value={e} style={{ background: '#222240' }}>{e}</option>
                ))}
              </select>
            </div>

            {/* Reset */}
            {activeCount > 0 && (
              <button
                onClick={reset}
                className="w-full flex items-center justify-center gap-1.5 py-2 text-sm text-amber-300/80 hover:text-amber-200 rounded-lg transition-all hover:bg-white/5"
                style={{ border: '1px solid rgba(201,168,76,0.15)' }}
              >
                <RotateCcw className="h-3.5 w-3.5" />
                重置筛选
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
